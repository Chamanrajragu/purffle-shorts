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

from . import ffmpeg, tts
from .config import Settings
from .llm import LLMConfigError
from .overlays import build_overlays
from .render import _encode_args, compose, extract_frame
from .script import normalize
from .timing import Word, caption_chunks, srt
from .utils import PermanentError, slugify

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
CROPS = ("center", "blur")
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
        words = tts._align_faster_whisper(audio, lang)
        log.info("Transcribed %d words with faster-whisper", len(words))
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
def clip_prompt(sents: list[Sentence], count: int, min_s: int, max_s: int, settings: Settings) -> tuple[str, str]:
    system = ("You are a short-form video editor who turns long videos into viral YouTube Shorts. You reply with a "
              "single JSON object and nothing else.")
    user = f"""Below is the transcript of a long video, one sentence per line with [start-end] times in seconds.

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
               max_s: int = 58) -> list[ClipPlan]:
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
            plans.append(ClipPlan(sents[i].start, end, title=sents[i].text[:60].rstrip(" ,.") or f"Clip {k + 1}",
                                  hook_text=""))
            nxt = j + 1
        return plans
    system, user = clip_prompt(sents, count, min_s, max_s, settings)
    data = llm.complete_json(system, user, CLIP_SCHEMA, max_tokens=6000)
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


# ------------------------------------------------------------------------------------------ rendering
def crop_filter(settings: Settings, mode: str) -> str:
    W, H = settings.width, settings.height
    cover = f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},setsar=1"
    if mode == "blur":  # whole frame in the middle, a blurred copy fills the rest
        return (f"split[a][b];[a]{cover},boxblur=24:3,eq=brightness=-0.10[bg];"
                f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1")
    return cover


def render_clip(settings: Settings, source: Path, plan: ClipPlan, words: list[Word], folder: Path,
                crop: str = "center") -> tuple[Path, list, float]:
    s = replace(settings, music_volume=0.0, transition="none", ken_burns=False)
    work = folder / "work"
    work.mkdir(parents=True, exist_ok=True)
    dur = round(plan.duration + 0.25, 3)
    F = s.fps
    seg = work / "seg00.mp4"
    ffmpeg.run(["-ss", f"{plan.start:.3f}", "-i", str(source), "-t", f"{dur:.3f}", "-an",
                "-vf", f"{crop_filter(s, crop)},fps={F}", *_encode_args(s, final=False),
                "-frames:v", str(max(2, round(dur * F))), str(seg)], label="clip video")
    voice = work / "voice.wav"
    ffmpeg.run(["-ss", f"{plan.start:.3f}", "-i", str(source), "-t", f"{dur:.3f}", "-vn", "-ac", "1",
                "-ar", "48000", str(voice)], label="clip audio")
    clip_words = [Word(w.text.strip(), round(w.start - plan.start, 3), round(w.end - plan.start, 3))
                  for w in words if plan.start - 0.05 <= w.start < plan.end]
    chunks = caption_chunks(clip_words, s.caption_max_words, total=dur)
    overlay = build_overlays(s, chunks, dur, plan.hook_text, work)
    video = folder / ("short.mp4" if s.vertical else "video.mp4")
    compose(s, [seg], [dur], voice, dur, overlay, video, work, None)
    return video, chunks, dur


def make_clips(studio, src: str, *, count: int = 3, crop: str = "center", upload: bool | None = None,
               min_seconds: int = 20, max_seconds: int = 58) -> list:
    """Returns one pipeline.Result per clip."""
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
        plans = pick_clips(llm, sents, s, count, min_seconds, min(max_seconds, 170))
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
                video, chunks, dur = render_clip(s, source, plan, words, folder, crop)
                out = ffmpeg.probe(video)
                extract_frame(video, min(1.2, dur / 3), folder / "cover.jpg")
                (folder / "captions.srt").write_text(srt(chunks), encoding="utf-8")
                title, description = final_title(script, s), final_description(script, set(), s)
                meta = {"title": title, "description": description, "tags": script.tags, "category_id": "24",
                        "language": s.language, "source": "clip", "style": "clip", "clip_of": src,
                        "clip_start": round(plan.start, 2), "clip_end": round(plan.end, 2),
                        "score": plan.score, "review": [plan.reason] if plan.reason else [],
                        "duration": round(out["duration"], 2), "resolution": f"{s.width}x{s.height}",
                        "llm": llm.label if llm else "offline", "created_at": now_iso()}
                (folder / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
                rid = studio.history.add_video(
                    subject=src, source="clip", topic=script.topic, style="clip", language=s.language, title=title,
                    description=description, tags=script.tags, folder=str(folder), video_path=str(video),
                    duration=out["duration"], llm=meta["llm"], voice="original audio", status="rendered",
                    score=plan.score)
                r = Result(True, title, folder, video, "rendered", seconds=time.time() - t0,
                           record_id=rid, score=plan.score, language=s.language)
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
