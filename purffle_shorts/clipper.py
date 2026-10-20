"""Clip a long video (podcast, interview, lecture, stream) into Shorts:

    purffle-shorts clip talk.mp4 --count 3
    purffle-shorts clip "https://..." --crop blur        (URLs need: pip install yt-dlp)

The audio is transcribed with word timings (faster-whisper locally, or OpenAI's API), the LLM reads the
timestamped transcript and picks the moments that work on their own — a hook in the first seconds and a
complete thought at the end — and each one is cropped to 9:16, captioned word by word and rendered.

Only clip videos you own or have permission to reuse.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from statistics import median

from . import ffmpeg, tts
from .config import Settings
from .llm import LLMConfigError
from .overlays import build_overlays
from .render import _encode_args, compose, pick_cover
from .script import normalize
from .timing import Word, caption_chunks, srt
from .utils import PermanentError, download, slugify

log = logging.getLogger("purffle")

CLIP_SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "title": {"type": "string"},
                    "hook_text": {"type": "string"},
                    "description": {"type": "string"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "score": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["start", "end", "title", "hook_text", "description", "hashtags", "tags", "score",
                             "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["clips"],
    "additionalProperties": False,
}
CROPS = ("center", "blur", "face")
YUNET_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
             "face_detection_yunet_2023mar.onnx")
MAX_TRANSCRIPT_CHARS = 60_000


@dataclass
class Sentence:
    start: float
    end: float
    text: str


@dataclass
class ClipPlan:
    start: float
    end: float
    title: str
    hook_text: str = ""
    description: str = ""
    hashtags: list[str] | None = None
    tags: list[str] | None = None
    score: int | None = None     # the LLM's retention estimate; None when no LLM chose the clip
    reason: str = ""

    @property
    def duration(self) -> float:
        return self.end - self.start


# ------------------------------------------------------------------------------------------ source & transcript
def fetch_source(src: str, dest_dir: Path) -> Path:
    if re.match(r"^https?://", src):
        try:
            import yt_dlp
        except ImportError as e:
            raise PermanentError("Clipping from a URL needs yt-dlp:  pip install yt-dlp  "
                                 "(or download the video yourself and pass the file)") from e
        dest_dir.mkdir(parents=True, exist_ok=True)
        opts = {"outtmpl": str(dest_dir / "source.%(ext)s"), "quiet": True, "noprogress": True,
                "format": "bv*[height<=1080]+ba/b[height<=1080]/b", "merge_output_format": "mp4"}
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([src])
        found = sorted(dest_dir.glob("source.*"), key=lambda p: p.stat().st_size, reverse=True)
        if not found:
            raise RuntimeError(f"yt-dlp downloaded nothing from {src}")
        return found[0]
    p = Path(src).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"video not found: {p}")
    return p


def transcribe(video: Path, work: Path, settings: Settings) -> list[Word]:
    work.mkdir(parents=True, exist_ok=True)
    audio = work / "audio.mp3"
    ffmpeg.run(["-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(audio)], label="extract audio")
    lang = settings.language.split("-")[0]
    try:
        model = tts.whisper_model(settings)
        words = tts._align_faster_whisper(audio, lang, model, vad=True)
        log.info("Transcribed %d words with faster-whisper (%s)", len(words), model)
        return words
    except ImportError:
        pass
    if settings.openai_api_key:
        if audio.stat().st_size > 24 * 1024 * 1024:
            raise PermanentError("That video is too long for OpenAI transcription (25 MB audio limit, about "
                                 "70 minutes). Install faster-whisper to clip it locally: pip install faster-whisper")
        words = tts._align_openai(audio, lang, settings.openai_api_key)
        log.info("Transcribed %d words with OpenAI", len(words))
        return words
    raise PermanentError("Clipping needs a transcript: pip install faster-whisper (free, local) "
                         "or set OPENAI_API_KEY")


def sentences(words: list[Word], max_words: int = 30) -> list[Sentence]:
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        pause = (nxt.start - w.end) if nxt else 9.0
        if w.text.rstrip()[-1:] in ".!?" or pause > 0.9 or len(cur) >= max_words:
            out.append(Sentence(cur[0].start, cur[-1].end, " ".join(x.text.strip() for x in cur)))
            cur = []
    return out


def transcript_block(sents: list[Sentence]) -> str:
    lines, size = [], 0
    for s in sents:
        line = f"[{s.start:.1f}-{s.end:.1f}] {s.text}"
        size += len(line) + 1
        if size > MAX_TRANSCRIPT_CHARS:
            lines.append("[...transcript truncated...]")
            break
        lines.append(line)
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------ choosing moments
def clip_prompt(sents: list[Sentence], count: int, min_s: int, max_s: int, settings: Settings,
                brief: str = "") -> tuple[str, str]:
    system = ("You are a short-form video editor who turns long videos into viral YouTube Shorts. You reply with a "
              "single JSON object and nothing else.")
    ask = (f"\nThe creator's brief, which comes first: {brief.strip()}\nOnly pick moments that fit this brief.\n"
           if brief.strip() else "")
    user = f"""Below is the transcript of a long video, one sentence per line with [start-end] times in seconds.
{ask}
Pick the {count} best moments to publish as standalone YouTube Shorts:
- each {min_s}-{max_s} seconds long, starting at a sentence start and ending at a sentence end;
- the first sentence must hook a viewer who has NOT seen the rest (a bold claim, a question, a surprising fact);
- the moment must make complete sense on its own and end on a payoff or complete thought;
- no overlapping moments; prefer emotional, funny, surprising or highly useful moments.

For each: start, end (seconds, copied from the transcript), title (max 60 characters, honest, curiosity-driven),
hook_text (max 6 words shown on screen at the start), description (2 sentences + a question), 3-5 hashtags,
8-12 tags, score (0-100: how well it will hold viewers), reason (one sentence). Language of the video: {settings.language}.

Transcript:
{transcript_block(sents)}

Return JSON: {{"clips": [...]}}"""
    return system, user


def _title_from(text: str) -> str:
    """A title from a spoken sentence (no LLM): without the "um" or "uh" the jump cuts remove anyway."""
    words = text.split()
    while words and re.sub(r"[^\w]", "", words[0].lower()) in FILLERS:
        words.pop(0)
    t = " ".join(words)[:60].rstrip(" ,.")
    return t[:1].upper() + t[1:]


def _snap(sents: list[Sentence], start: float, end: float, min_s: float, max_s: float) -> tuple[float, float] | None:
    if not sents:
        return None
    i = min(range(len(sents)), key=lambda k: abs(sents[k].start - start))
    j = min(range(i, len(sents)), key=lambda k: abs(sents[k].end - end))
    while j > i and sents[j].end - sents[i].start > max_s:
        j -= 1
    while j + 1 < len(sents) and sents[j].end - sents[i].start < min_s:
        j += 1
    s0, e0 = sents[i].start, sents[j].end
    if e0 - s0 > max_s:  # one very long sentence: cut it
        e0 = s0 + max_s
    return (s0, e0) if e0 - s0 >= min(min_s, 5.0) else None


def pick_clips(llm, sents: list[Sentence], settings: Settings, count: int, min_s: int = 20,
               max_s: int = 58, brief: str = "") -> list[ClipPlan]:
    if llm is None:  # offline: windows spread evenly over the whole video, each starting on a sentence
        plans, nxt = [], 0
        if not sents:
            return plans
        t0, step = sents[0].start, (sents[-1].end - sents[0].start) / max(count, 1)
        for k in range(count):
            i = next((n for n in range(nxt, len(sents)) if sents[n].start >= t0 + k * step), None)
            if i is None:
                break
            j = i
            while j + 1 < len(sents) and sents[j].end - sents[i].start < min_s:
                j += 1
            end = min(sents[j].end, sents[i].start + max_s)
            if end - sents[i].start < min(min_s, 5.0):
                continue
            plans.append(ClipPlan(sents[i].start, end, title=_title_from(sents[i].text) or f"Clip {k + 1}",
                                  hook_text=""))
            nxt = j + 1
        return plans
    system, user = clip_prompt(sents, count, min_s, max_s, settings, brief)
    data = llm.complete_json(system, user, CLIP_SCHEMA, max_tokens=6000, temperature=0.3)  # judge, don't invent
    plans: list[ClipPlan] = []
    for c in data.get("clips") or []:
        try:
            snapped = _snap(sents, float(c["start"]), float(c["end"]), min_s, max_s)
        except (KeyError, TypeError, ValueError):
            continue
        if not snapped:
            continue
        s0, e0 = snapped
        if any(s0 < p.end and e0 > p.start for p in plans):
            continue
        plans.append(ClipPlan(s0, e0, str(c.get("title") or "").strip(), str(c.get("hook_text") or "").strip(),
                              str(c.get("description") or "").strip(), list(c.get("hashtags") or []),
                              list(c.get("tags") or []), int(c.get("score") or 0), str(c.get("reason") or "")))
    plans.sort(key=lambda p: p.score or 0, reverse=True)
    return plans[:count]


# ------------------------------------------------------------------------------------------ face framing
def _face_detector(settings: Settings):
    """A function image -> [(centre x, centre y, area, score)], or None without OpenCV. Prefers the YuNet
    neural detector (its 230 KB model is downloaded once into data/models); falls back to OpenCV 4's
    Haar cascade."""
    try:
        import cv2
    except ImportError:
        return None
    if hasattr(cv2, "FaceDetectorYN"):
        model = settings.data_path / "models" / "face_detection_yunet_2023mar.onnx"
        try:
            if not model.exists() or model.stat().st_size < 100_000:
                download(YUNET_URL, model, timeout=60, max_bytes=5 * 1024 * 1024)
            det = cv2.FaceDetectorYN.create(str(model), "", (320, 320), 0.6, 0.3, 20)

            def yunet(img):
                h, w = img.shape[:2]
                det.setInputSize((w, h))
                _, faces = det.detect(img)
                return [(float(f[0] + f[2] / 2), float(f[1] + f[3] / 2), float(f[2] * f[3]), float(f[-1]))
                        for f in (faces if faces is not None else [])]
            return yunet
        except Exception as e:
            log.warning("Face detector model unavailable (%s)", e)
    if hasattr(cv2, "CascadeClassifier"):
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

        def haar(img):
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            return [(x + w / 2, y + h / 2, float(w * h), 1.0)
                    for x, y, w, h in cascade.detectMultiScale(gray, 1.1, 5, minSize=(24, 24))]
        return haar
    return None


def face_samples(settings: Settings, source: Path, start: float, dur: float, work: Path,
                 every: float = 0.5) -> list[tuple[float, float | None]] | None:
    """(time in the clip, horizontal centre of the main face as a fraction of the width) about twice a second.
    The main face is the biggest confident one. None when no detector is available."""
    detect = _face_detector(settings)
    if detect is None:
        return None
    import cv2
    frames = work / "faces"
    frames.mkdir(parents=True, exist_ok=True)
    ffmpeg.run(["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(source), "-vf",
                f"fps={1 / every:.4f},scale=640:-2", str(frames / "f%04d.jpg")], label="face samples")
    out: list[tuple[float, float | None]] = []
    for k, f in enumerate(sorted(frames.glob("f*.jpg"))):
        img = cv2.imread(str(f))
        if img is None:
            continue
        faces = detect(img)
        main = max(faces, key=lambda c: c[2] * c[3], default=None)
        out.append(((k + 0.5) * every, main[0] / img.shape[1] if main else None))
    return out


def plan_face_crop(samples: list[tuple[float, float | None]], dur: float, jump: float = 0.12,
                   min_seconds: float = 1.0) -> list[tuple[float, float]]:
    """[(from time, face centre x)]: one steady framing per camera shot. A new framing starts when the face
    moves more than ``jump`` of the width (a camera cut, or the other speaker); shorter than ``min_seconds``
    and it joins the framing before it, so detection noise never makes the picture jitter."""
    known = _smooth([(t, x) for t, x in samples if x is not None])
    if not known:
        return []
    segs: list[list] = []
    for t, x in known:
        if segs and abs(x - median(segs[-1][1])) <= jump:
            segs[-1][1].append(x)
        else:
            segs.append([t, [x]])
    merged: list[list] = []
    for i, (t0, xs) in enumerate(segs):
        end = segs[i + 1][0] if i + 1 < len(segs) else dur
        if merged and end - t0 < min_seconds:
            merged[-1][1].extend(xs)
        else:
            merged.append([t0, list(xs)])
    return [(0.0 if i == 0 else round(t0 - 0.25, 2), round(median(xs), 4)) for i, (t0, xs) in enumerate(merged)]


def _smooth(known: list[tuple[float, float]], radius: int = 2) -> list[tuple[float, float]]:
    """A running median over neighbouring samples: one stray detection (the other speaker for a moment, a
    poster on the wall) is outvoted instead of starting a framing of its own."""
    xs = [x for _, x in known]
    out = []
    for i, (t, x) in enumerate(known):
        win = sorted(xs[max(0, i - radius):i + radius + 1])
        n = len(win)
        if n % 2:
            m = win[n // 2]
        else:  # even window: of the two middle values, the one nearer this sample
            lo, hi = win[n // 2 - 1], win[n // 2]
            m = lo if abs(lo - x) <= abs(hi - x) else hi
        out.append((t, m))
    return out


def face_crop_filter(settings: Settings, src_w: int, src_h: int, plan: list[tuple[float, float]]) -> str | None:
    """A crop that keeps the face in frame, switching framing at the planned times. None when the source is
    not wider than the output (nothing to choose) or no face was found."""
    W, H = settings.width, settings.height
    if not plan or not src_w or not src_h or src_w / src_h <= W / H + 0.01:
        return None
    cw, ch = int(src_h * W / H) // 2 * 2, src_h // 2 * 2

    def left(c: float) -> int:
        return max(0, min(src_w - cw, int(c * src_w - cw / 2))) // 2 * 2
    expr = str(left(plan[-1][1]))
    for i in range(len(plan) - 2, -1, -1):
        expr = f"if(lt(t,{plan[i + 1][0]:.2f}),{left(plan[i][1])},{expr})"
    return f"crop={cw}:{ch}:x='{expr}':y=0,scale={W}:{H}:flags=lanczos,setsar=1"


# ------------------------------------------------------------------------------------------ editing
# hesitation sounds Whisper writes down (English, Spanish, German, French, Portuguese)
FILLERS = {"um", "umm", "uh", "uhh", "uhm", "erm", "er", "hmm", "mm", "mhm", "eh", "ehm", "äh", "ähm", "euh", "hum"}


def _filler(word: Word) -> bool:
    return re.sub(r"[^\w]", "", word.text.lower()) in FILLERS


def keep_ranges(words: list[Word], dur: float, fps: int, *, max_pause: float = 0.6, pad: float = 0.15,
                fillers: bool = True) -> list[tuple[float, float]]:
    """Jump cuts: the parts of a clip to keep, as (start, end) seconds on frame boundaries. Pauses longer
    than ``max_pause`` shrink to about 2 x ``pad`` and filler sounds ("um", "uh") are cut together with
    the pauses around them. Cutting on frame boundaries lets the picture and the sound be cut at exactly
    the same instants, so lips stay in sync however many cuts there are."""
    if not words:
        return [(0.0, dur)]
    cuts: list[tuple[float, float]] = []
    spoken = [w for w in words if not (fillers and _filler(w))]
    if not spoken:
        return [(0.0, dur)]
    if spoken[0].start > 2 * pad:
        cuts.append((0.0, spoken[0].start - pad))
    for a, b in zip(spoken, spoken[1:]):
        gap = b.start - a.end
        has_filler = fillers and any(_filler(w) and a.end <= w.start < b.start for w in words)
        if gap > max_pause or (has_filler and gap > 2 * pad):
            cuts.append((a.end + pad, b.start - pad))
    tail = min(dur, spoken[-1].end + 0.25)
    if dur - tail > 1.0 / fps:
        cuts.append((tail, dur))
    if not cuts:
        return [(0.0, dur)]

    def snap(t: float) -> float:
        return round(round(t * fps) / fps, 6)
    end = round(int(dur * fps + 1e-6) / fps, 6)  # never past the last frame of the clip
    keep, t = [], 0.0
    for c0, c1 in sorted(cuts):
        c0, c1 = snap(c0), min(snap(c1), end)
        if c1 - c0 < 1.0 / fps or c0 < t:
            continue
        if c0 - t >= 2.0 / fps:
            keep.append((t, c0))
        t = c1
    if end - t >= 2.0 / fps:
        keep.append((t, end))
    return keep or [(0.0, dur)]


def retime(words: list[Word], keep: list[tuple[float, float]]) -> list[Word]:
    """Word times after the jump cuts; words that fell in a cut (fillers) are dropped."""
    out, removed, k = [], 0.0, 0
    for w in words:
        while k < len(keep) and w.start >= keep[k][1]:
            k += 1
        if k >= len(keep):
            break
        a, b = keep[k]
        if w.start < a - 0.02:
            continue
        removed = a - sum(y - x for x, y in keep[:k])
        out.append(Word(w.text, round(max(0.0, w.start - removed), 3), round(min(b, w.end) - removed, 3),
                        w.speaker))
    return out


def select_expr(keep: list[tuple[float, float]], fps: int) -> str:
    """An ffmpeg select/aselect expression true for frames in the kept parts. Half a frame of tolerance
    so a frame that starts exactly on a boundary is decided the same way for picture and sound."""
    h = 0.5 / fps
    return "+".join(f"gte(t,{a - h:.4f})*lt(t,{b - h:.4f})" for a, b in keep)


def zoom_plan(words: list[Word], dur: float, *, zoom: float = 1.12, min_seconds: float = 2.0) -> list[tuple[float, float]]:
    """[(from time, zoom)]: the framing punches in and out at sentence starts, at most every
    ``min_seconds``, the hard-cut zoom editors use to keep a talking head lively."""
    plan, level, last = [(0.0, 1.0)], 1.0, 0.0
    for prev, w in zip(words, words[1:]):
        new_sentence = prev.text.rstrip()[-1:] in ".!?" or w.start - prev.end > 0.45
        if new_sentence and w.start - last >= min_seconds and dur - w.start >= min_seconds:
            level = zoom if level == 1.0 else 1.0
            t = max(0.0, w.start - 0.05)
            plan.append((round(t, 3), level))
            last = t
    return plan


def zoom_filter(settings: Settings, plan: list[tuple[float, float]]) -> str:
    """zoompan with a piecewise-constant zoom (no slow drift): each change is a clean cut. The zoom is
    centred a little above the middle, where faces usually are."""
    if len(plan) < 2:
        return ""
    expr = f"{plan[-1][1]:.3f}"
    for i in range(len(plan) - 2, -1, -1):
        expr = f"if(lt(it,{plan[i + 1][0]:.3f}),{plan[i][1]:.3f},{expr})"
    W, H, F = settings.width, settings.height, settings.fps
    return (f",zoompan=z='{expr}':x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*0.4':d=1:s={W}x{H}:fps={F},"
            f"setsar=1")


# ------------------------------------------------------------------------------------------ rendering
def crop_filter(settings: Settings, mode: str, face: str | None = None) -> str:
    W, H = settings.width, settings.height
    cover = f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},setsar=1"
    if mode == "face" and face:
        return face
    if mode == "blur":  # whole frame in the middle, a blurred copy fills the rest
        return (f"split[a][b];[a]{cover},boxblur=24:3,eq=brightness=-0.10[bg];"
                f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1")
    return cover


def render_clip(settings: Settings, source: Path, plan: ClipPlan, words: list[Word], folder: Path,
                crop: str = "center", src_size: tuple[int, int] | None = None) -> tuple[Path, list, float]:
    s = replace(settings, music_volume=0.0, transition="none", ken_burns=False)
    work = folder / "work"
    work.mkdir(parents=True, exist_ok=True)
    dur = round(plan.duration + 0.25, 3)
    F = s.fps
    face = None
    if crop == "face":
        if src_size is None:
            info = ffmpeg.probe(source)
            src_size = (info["width"], info["height"])
        samples = face_samples(s, source, plan.start, dur, work)
        if samples is None:
            log.warning("Face framing needs OpenCV (pip install opencv-python-headless); cropping the centre")
        else:
            framing = plan_face_crop(samples, dur)
            face = face_crop_filter(s, *src_size, framing)
            log.info("Face framing: %s", f"{len(framing)} shot(s)" if face else "no face found, cropping the centre")
    clip_words = [Word(w.text.strip(), round(w.start - plan.start, 3), round(w.end - plan.start, 3))
                  for w in words if plan.start - 0.05 <= w.start < plan.end]
    keep = keep_ranges(clip_words, dur, F, max_pause=s.clip_max_pause) if s.clip_jump_cuts else [(0.0, dur)]
    cut = len(keep) > 1 or keep[0] != (0.0, dur)
    picked, sound = "", ""
    if cut:
        expr = select_expr(keep, F)
        picked = f",select='{expr}',setpts=N/({F}*TB)"
        # audio frames exactly one video frame long, so both are kept or dropped together
        sound = f"asetnsamples=n={round(48000 / F)}:p=0,aselect='{expr}',asetpts=N/SR/TB,"
        clip_words = retime(clip_words, keep)
        new_dur = round(sum(b - a for a, b in keep), 3)
        log.info("Jump cuts: %d cut(s), %.1fs -> %.1fs", len(keep) - 1 + (keep[0][0] > 0), dur, new_dur)
        dur = new_dur
    zoom = zoom_filter(s, zoom_plan(clip_words, dur)) if s.clip_zoom and crop != "blur" else ""
    seg = work / "seg00.mp4"
    ffmpeg.run(["-ss", f"{plan.start:.3f}", "-i", str(source), "-t", f"{plan.duration + 0.25:.3f}", "-an",
                "-vf", f"{crop_filter(s, crop, face)},fps={F}{picked}{zoom}", *_encode_args(s, final=False),
                "-frames:v", str(max(2, round(dur * F))), str(seg)], label="clip video")
    voice = work / "voice.wav"
    ffmpeg.run(["-ss", f"{plan.start:.3f}", "-i", str(source), "-t", f"{plan.duration + 0.25:.3f}", "-vn",
                "-af", f"aresample=48000,{sound}aformat=channel_layouts=mono", "-ar", "48000", str(voice)],
               label="clip audio")
    chunks = caption_chunks(clip_words, s.caption_max_words, total=dur)
    overlay = build_overlays(s, chunks, dur, plan.hook_text, work)
    video = folder / ("short.mp4" if s.vertical else "video.mp4")
    compose(s, [seg], [dur], voice, dur, overlay, video, work, None)
    return video, chunks, dur


def make_clips(studio, src: str, *, count: int = 3, crop: str = "center", upload: bool | None = None,
               min_seconds: int = 20, max_seconds: int = 58, brief: str = "") -> list:
    """Returns one pipeline.Result per clip. ``brief``: what to look for ("the funniest moments", "every
    tip about sleep"); without an LLM it is ignored."""
    from .history import now_iso
    from .pipeline import Result, final_description, final_title

    s = studio.s
    upload = s.upload if upload is None else upload
    crop = crop if crop in CROPS else "center"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    src_name = Path(src).stem if not re.match(r"^https?://", src) else "video"
    scratch = s.out_path / f".clip-{stamp}-{slugify(src_name, 24)}"
    results = []
    try:
        studio._step("topic", "reading the video")
        source = fetch_source(src, scratch)
        info = ffmpeg.probe(source)
        if not info["has_video"] or not info["has_audio"]:
            raise PermanentError(f"{src}: needs both a picture and sound")
        studio._step("voice", "transcribing")
        words = transcribe(source, scratch, s)
        if not words:
            raise RuntimeError("the transcript is empty (is there speech in this video?)")
        sents = sentences(words)
        studio._step("script", "finding the best moments")
        try:
            llm = studio.llm
        except LLMConfigError as e:
            log.warning("No LLM is configured, so the clips are evenly spaced moments instead of the best ones "
                        "(%s)", str(e).split(".")[0])
            llm = None
        if brief and llm is None:
            log.warning("The clip brief needs an LLM to read the transcript; it is ignored")
        plans = pick_clips(llm, sents, s, count, min_seconds, min(max_seconds, 170), brief)
        if not plans:
            raise RuntimeError("no usable moments found")
        log.info("Clipping %d moment(s) from %s", len(plans), src)
        for n, plan in enumerate(plans, 1):
            studio._step("render", f"clip {n}/{len(plans)}")
            t0 = time.time()
            text = " ".join(w.text.strip() for w in words if plan.start <= w.start < plan.end)
            script = normalize({"title": plan.title, "hook_text": plan.hook_text, "description": plan.description,
                                "hashtags": plan.hashtags or [], "tags": plan.tags or [], "category": "entertainment",
                                "scenes": [{"narration": text or plan.title, "search_query": "clip"}]},
                               plan.title or src_name, "story", s.language)
            folder = (s.out_path / f"{stamp}_{slugify(script.title)}-{n}").resolve()
            folder.mkdir(parents=True, exist_ok=True)
            try:
                video, chunks, dur = render_clip(s, source, plan, words, folder, crop,
                                                 (info["width"], info["height"]))
                out = ffmpeg.probe(video)
                cover_at = pick_cover(video, folder / "cover.jpg", folder / "work", total=dur, until=min(3.0, dur * 0.4))
                (folder / "captions.srt").write_text(srt(chunks), encoding="utf-8")
                title, description = final_title(script, s), final_description(script, set(), s)
                meta = {"title": title, "description": description, "tags": script.tags, "category_id": "24",
                        "language": s.language, "source": "clip", "style": "clip", "clip_of": src,
                        "clip_start": round(plan.start, 2), "clip_end": round(plan.end, 2),
                        "score": plan.score, "review": [plan.reason] if plan.reason else [],
                        "duration": round(out["duration"], 2), "resolution": f"{s.width}x{s.height}",
                        "llm": llm.label if llm else "offline", "created_at": now_iso(), "cover_at": round(cover_at, 2)}
                (folder / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
                rid = studio.history.add_video(
                    subject=src, source="clip", topic=script.topic, style="clip", language=s.language, title=title,
                    description=description, tags=script.tags, folder=str(folder), video_path=str(video),
                    duration=out["duration"], llm=meta["llm"], voice="original audio", status="rendered",
                    score=plan.score)
                r = Result(True, title, folder, video, "rendered", seconds=time.time() - t0,
                           record_id=rid, score=plan.score, language=s.language, reason=plan.reason)
                log.info("Clip %d: %s (%.0fs from %s)", n, title, dur, _ts(plan.start))
                if upload:
                    studio.upload_record(rid, r)
                results.append(r)
            except PermanentError:
                raise
            except Exception as e:
                log.error("Clip %d failed: %s", n, e)
                results.append(Result(False, plan.title, folder, status="failed", error=str(e)))
            finally:
                if not os.getenv("KEEP_WORK"):
                    shutil.rmtree(folder / "work", ignore_errors=True)
        studio._step("done")
        return results
    finally:
        if not os.getenv("KEEP_WORK"):
            shutil.rmtree(scratch, ignore_errors=True)


def _ts(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"
