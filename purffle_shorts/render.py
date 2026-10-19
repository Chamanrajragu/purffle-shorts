"""ffmpeg rendering. Each scene is normalised to a 9:16 segment (cover-crop, colour grade, Ken Burns for
stills), then one final pass joins them with transitions and adds captions, overlays, a progress bar,
ducked background music and loudness normalisation. No MoviePy, no ImageMagick."""

from __future__ import annotations

import concurrent.futures
import logging
import os
import random
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from . import ffmpeg, sfx
from .config import Settings
from .media import MediaItem
from .overlays import OverlayPlan

log = logging.getLogger("purffle")

GRADES = {
    "none": "",
    "vivid": "eq=contrast=1.06:saturation=1.20",
    "cinematic": "eq=contrast=1.08:saturation=0.90:gamma=0.97,colorbalance=rs=-0.04:bs=0.05:rh=0.05:bh=-0.04,vignette=PI/5",
    "warm": "colorbalance=rs=0.06:gs=0.02:bs=-0.05,eq=saturation=1.10",
    "cool": "colorbalance=rs=-0.05:bs=0.07,eq=saturation=1.05",
    "bw": "hue=s=0,eq=contrast=1.15",
}
TRANSITIONS = ["fade", "smoothleft", "smoothup", "slideleft", "slideup", "circleopen", "wipeleft",
               "zoomin", "dissolve", "radial", "hblur", "fadeblack", "squeezeh"]
GRADIENT_PALETTES = [("0x0f2027", "0x2c5364"), ("0x41295a", "0x2f0743"), ("0x1f1c2c", "0x928dab"),
                     ("0x16222a", "0x3a6073"), ("0x3a1c71", "0xd76d77"), ("0x0b486b", "0xf56217")]
MUSIC_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


def _grade(settings: Settings) -> str:
    g = GRADES.get(settings.color_grade, "")
    return f",{g}" if g else ""


def _encode_args(settings: Settings, final: bool) -> list[str]:
    if not final:  # intermediates are decoded again at once: encode them as fast as possible, visually lossless
        return ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "15", "-pix_fmt", "yuv420p"]
    enc = settings.video_encoder
    if enc == "auto":
        enc = "h264_videotoolbox" if sys.platform == "darwin" and ffmpeg.has_encoder("h264_videotoolbox") else "libx264"
    if enc == "h264_videotoolbox":
        return ["-c:v", enc, "-b:v", "12M", "-maxrate", "16M", "-bufsize", "24M", "-profile:v", "high",
                "-pix_fmt", "yuv420p"]
    if enc == "h264_nvenc":
        return ["-c:v", enc, "-preset", "p5", "-rc", "vbr", "-cq", str(settings.crf), "-b:v", "0",
                "-profile:v", "high", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", settings.preset, "-crf", str(settings.crf), "-profile:v", "high",
            "-pix_fmt", "yuv420p", "-g", str(settings.fps * 2)]


def prepare_segment(item: MediaItem, seconds: float, idx: int, settings: Settings, work: Path) -> Path:
    W, H, F = settings.width, settings.height, settings.fps
    out = work / f"seg{idx:02d}.mp4"
    seconds = max(seconds, 2.0 / F)
    frames = max(2, round(seconds * F))
    cover = f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},setsar=1"
    grade = _grade(settings)
    enc = _encode_args(settings, final=False)

    if item.kind == "video" and item.path:
        src = item.duration or ffmpeg.duration(item.path)
        pre: list[str] = []
        if src <= seconds + 0.1:
            pre = ["-stream_loop", "-1"]
        elif item.extra.get("start") is not None:  # a chosen stretch (background video)
            pre = ["-ss", f"{float(item.extra['start']):.2f}"]
        else:
            # Skip the first moments (often a fade-in) and pick a random window for variety.
            max_start = src - seconds
            lo = min(0.5, max_start)
            hi = max(lo, min(max_start, src * 0.35))
            pre = ["-ss", f"{random.uniform(lo, hi):.2f}"]
        ffmpeg.run([*pre, "-i", str(item.path), "-t", f"{seconds:.3f}", "-an",
                    "-vf", f"{cover},fps={F}{grade}", *enc, "-frames:v", str(frames), str(out)],
                   label=f"segment {idx}")
        return out

    if item.kind == "image" and item.path:
        if settings.ken_burns:
            z = random.choice(["in", "out", "pan"])
            zoom = {"in": f"min(1+0.16*on/{frames},1.16)", "out": f"1.16-0.16*on/{frames}", "pan": "1.12"}[z]
            x = "(iw-iw/zoom)*on/" + str(frames) if z == "pan" else "iw/2-(iw/zoom/2)"
            y = "ih/2-(ih/zoom/2)"
            vf = (f"scale={2 * W}:{2 * H}:force_original_aspect_ratio=increase,crop={2 * W}:{2 * H},"
                  f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={F},setsar=1{grade}")
            ffmpeg.run(["-i", str(item.path), "-vf", vf, *enc, "-frames:v", str(frames), str(out)],
                       label=f"segment {idx} (ken burns)")
        else:
            ffmpeg.run(["-loop", "1", "-framerate", str(F), "-i", str(item.path), "-vf", f"{cover}{grade}",
                        *enc, "-frames:v", str(frames), str(out)], label=f"segment {idx} (still)")
        return out

    # Generated animated background (no footage found / offline demo). A gradient has no detail, so it is drawn
    # at a quarter of the size and scaled up: the same picture about ten times faster.
    c0, c1 = random.choice(GRADIENT_PALETTES)
    gw, gh = max(32, W // 8 * 2), max(32, H // 8 * 2)
    if ffmpeg.has_filter("gradients"):
        src = (f"gradients=s={gw}x{gh}:r={F}:c0={c0}:c1={c1}:x0=0:y0=0:x1={gw}:y1={gh}:"
               f"speed=0.02:d={seconds:.3f}:seed={random.randint(0, 9999)}")
    else:
        src = f"color=c={c0}:s={gw}x{gh}:r={F}:d={seconds:.3f}"
    ffmpeg.run(["-f", "lavfi", "-i", src, "-vf", f"scale={W}:{H}:flags=bicubic,setsar=1,format=yuv420p", *enc,
                "-frames:v", str(frames), str(out)], label=f"segment {idx} (generated)")
    return out


def segment_lengths(scene_durations: list[float], transition: float, joins: list[bool] | None = None) -> list[float]:
    """Pad segments so centred cross-fades keep every cut on its narration boundary. ``joins[i]`` is True when
    segments i and i+1 are shots of the same scene: those meet with a hard cut and need no padding."""
    n = len(scene_durations)
    if n <= 1 or transition <= 0:
        return list(scene_durations)
    half = transition / 2
    out = list(scene_durations)
    for i in range(n - 1):
        if joins and joins[i]:
            continue
        out[i] += half
        out[i + 1] += half
    return out


def pick_music(settings: Settings) -> Path | None:
    if settings.music_volume <= 0:
        return None
    d = Path(settings.music_dir)
    tracks = [p for p in d.rglob("*") if p.suffix.lower() in MUSIC_EXT] if d.is_dir() else []
    if tracks:
        return random.choice(tracks)
    f = Path(settings.music_file)
    return f if settings.music_file and f.exists() else None


VOICE_CHAIN = ("highpass=f=75", "deesser=i=0.35", "acompressor=threshold=0.08:ratio=2.5:attack=8:release=140:makeup=1.6")


def _voice_filters(settings: Settings) -> str:
    """Gentle broadcast clean-up for the voice: rumble cut, softer 's' sounds, evened-out level."""
    if not settings.voice_enhance:
        return ""
    chain = [c for c in VOICE_CHAIN if ffmpeg.has_filter(c.split("=", 1)[0])]
    return "," + ",".join(chain) if chain else ""


SFX_BELOW_VOICE = 11.0  # dB: effects are heard but never compete with the words


def _fx_gain(settings: Settings, voice: Path, effects: Path) -> float:
    """Linear gain that puts the effects SFX_BELOW_VOICE dB under this voice (measured after the voice
    clean-up), so they sit the same way whichever TTS engine spoke, times SFX_VOLUME."""
    v = _measure(voice, _voice_filters(settings).lstrip(","))
    fx = _measure(effects, "")
    if v is None or fx is None:
        return 0.25 * settings.sfx_volume
    db = max(-30.0, min(12.0, v - SFX_BELOW_VOICE - fx))
    return settings.sfx_volume * 10 ** (db / 20)


def _measure(path: Path, filters: str) -> float | None:
    chain = f"{filters}," if filters else ""
    try:
        err = ffmpeg.run(["-i", str(Path(path).resolve()), "-vn", "-af",
                          f"aformat=channel_layouts=stereo,{chain}loudnorm=print_format=json", "-f", "null", "-"],
                         label="measure loudness", loglevel="info")
    except ffmpeg.FFmpegError:
        return None
    try:
        value = float((ffmpeg.loudnorm_report(err) or {}).get("input_i", "nan"))
    except ValueError:
        return None
    return value if value > -70 else None


def mix_audio(settings: Settings, voice: Path, total: float, music: Path | None, work: Path,
              effects: Path | None = None) -> Path:
    """The finished soundtrack, exactly ``total`` seconds long: the cleaned-up voice with the music ducked under
    it and the sound effects (sfx.track) on top, normalised to LOUDNESS_LUFS in two passes. The first pass
    measures the mix; the second applies one constant gain (loudnorm's linear mode), which hits the target
    within a fraction of a LU and never pumps the way single-pass normalisation does."""
    mix = work / "mix.wav"
    graph = [f"[0:a]aresample=48000,aformat=channel_layouts=stereo{_voice_filters(settings)},"
             f"apad=whole_dur={total:.3f},atrim=0:{total:.3f}[v0]"]
    inputs = ["-i", str(Path(voice).resolve())]
    beds: list[str] = []  # everything mixed under the voice
    k = 1                 # next input index
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(Path(music).resolve())]
        fade_out = max(0.0, total - 1.5)
        graph.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,volume={settings.music_volume:.3f},"
                     f"afade=t=in:d=0.8,afade=t=out:st={fade_out:.3f}:d=1.5,atrim=0:{total:.3f}[mus]")
        k += 1
        if settings.music_ducking:  # music dips automatically whenever the voice speaks
            graph.append("[v0]asplit=2[voice][sc]")
            graph.append("[mus][sc]sidechaincompress=threshold=0.015:ratio=8:attack=15:release=350:makeup=1[duck]")
            beds.append("duck")
        else:
            graph.append("[v0]anull[voice]")
            beds.append("mus")
    else:
        graph.append("[v0]anull[voice]")
    if effects:
        inputs += ["-i", str(Path(effects).resolve())]
        gain = _fx_gain(settings, voice, effects)
        graph.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,volume={gain:.4f},"
                     f"apad=whole_dur={total:.3f},atrim=0:{total:.3f}[fx]")
        beds.append("fx")
    if beds:
        graph.append("[voice]" + "".join(f"[{b}]" for b in beds)
                     + f"amix=inputs={1 + len(beds)}:duration=first:dropout_transition=0:normalize=0[mix]")
    else:
        graph.append("[voice]anull[mix]")
    target = f"I={settings.loudness_lufs}:TP=-1.5:LRA=11"
    graph.append(f"[mix]asplit=2[keep][probe];[probe]loudnorm={target}:print_format=json[m]")
    err = ffmpeg.run([*inputs, "-filter_complex", ";".join(graph), "-map", "[keep]", "-c:a", "pcm_s16le",
                      str(mix.resolve()), "-map", "[m]", "-f", "null", "-"], label="audio mix", loglevel="info")
    m = ffmpeg.loudnorm_report(err) or {}
    try:
        measured = {k: float(m[k]) for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}
    except (KeyError, TypeError, ValueError):
        measured = {}
    if not measured or measured["input_i"] <= -70:  # silence (e.g. a layout preview): nothing to normalise
        return mix
    out = work / "soundtrack.wav"
    ffmpeg.run(["-i", str(mix.resolve()), "-af",
                f"loudnorm={target}:measured_I={measured['input_i']}:"
                f"measured_TP={measured['input_tp']}:measured_LRA={measured['input_lra']}:"
                f"measured_thresh={measured['input_thresh']}:offset={measured['target_offset']}:linear=true,"
                f"aresample=48000", "-c:a", "pcm_s16le", str(out.resolve())], label="audio loudness")
    return out


def compose(settings: Settings, segments: list[Path], lengths: list[float], voice: Path, total: float,
            plan: OverlayPlan, out: Path, work: Path, music: Path | None, joins: list[bool] | None = None,
            progress: Callable[[float], None] | None = None, effects: Path | None = None,
            background: Path | None = None) -> Path:
    """``background``: a segment as long as the video, stacked under the footage (split layout); the
    segments are then the top part of the frame."""
    W, H, F = settings.width, settings.height, settings.fps
    T = settings.transition_seconds if settings.transition != "none" and len(segments) > 1 else 0.0
    # ffmpeg runs inside `work` (so the libass paths stay simple): every input must be absolute.
    inputs: list[str] = []
    for seg in segments:
        inputs += ["-i", str(Path(seg).resolve())]
    n = len(segments)
    idx = n
    audio_i = idx
    inputs += ["-i", str(mix_audio(settings, voice, total, music, work, effects).resolve())]
    idx += 1
    bg_i = None
    if background:
        inputs += ["-i", str(Path(background).resolve())]
        bg_i, idx = idx, idx + 1

    f: list[str] = []
    for i in range(n):
        f.append(f"[{i}:v]settb=AVTB,setpts=PTS-STARTPTS,fps={F},format=yuv420p[s{i}]")
    # Shots of one scene are joined with hard cuts; scenes are joined with transitions.
    groups: list[list[int]] = [[0]]
    for i in range(1, n):
        if T > 0 and joins and joins[i - 1]:
            groups[-1].append(i)
        else:
            groups.append([i])
    labels, glens = [], []
    for gi, g in enumerate(groups):
        if len(g) == 1:
            labels.append(f"s{g[0]}")
        else:
            # concat outputs microsecond timestamps; xfade needs both inputs on the 1/fps timebase
            f.append("".join(f"[s{i}]" for i in g) + f"concat=n={len(g)}:v=1:a=0,settb=1/{F}[g{gi}]")
            labels.append(f"g{gi}")
        glens.append(sum(lengths[i] for i in g))
    if len(labels) == 1:
        last = labels[0]
    elif T > 0:
        acc, last = glens[0], labels[0]
        for gi in range(1, len(labels)):
            tr = random.choice(TRANSITIONS) if settings.transition == "random" else settings.transition
            f.append(f"[{last}][{labels[gi]}]xfade=transition={tr}:duration={T:.3f}:offset={acc - T:.3f}[x{gi}]")
            acc += glens[gi] - T
            last = f"x{gi}"
    else:
        f.append("".join(f"[{lab}]" for lab in labels) + f"concat=n={len(labels)}:v=1:a=0[cat]")
        last = "cat"
    if bg_i is not None:
        f.append(f"[{bg_i}:v]settb=AVTB,setpts=PTS-STARTPTS,fps={F},format=yuv420p[bg]")
        f.append(f"[{last}][bg]vstack=inputs=2,setsar=1[split]")
        last = "split"

    def overlay(src_label: str, expr: str, name: str):
        # Blend in the output's own pixel format: with format=auto ffmpeg converts every full frame to another
        # format and back for each overlay, which used to be most of the render time.
        nonlocal last
        f.append(f"[{last}][{src_label}]overlay={expr}:format=yuv420[{name}]")
        last = name

    def still(png: Path, seconds: float) -> None:
        nonlocal inputs
        inputs += ["-framerate", str(F), "-loop", "1", "-t", f"{max(seconds, 1.0 / F):.3f}", "-i", str(png.resolve())]

    if plan.chat:
        playlist, cx, cy = plan.chat
        inputs += ["-f", "concat", "-safe", "0", "-i", str(playlist.resolve())]
        f.append(f"[{idx}:v]format=yuva420p[chat]")
        overlay("chat", f"x={cx}:y={cy}", "vchat")
        idx += 1
    if plan.card:
        png, cx, cy = plan.card
        u = plan.card_until
        still(png, u)
        f.append(f"[{idx}:v]format=yuva420p,fade=t=in:st=0:d=0.12:alpha=1,"
                 f"fade=t=out:st={max(0.0, u - 0.25):.3f}:d=0.25:alpha=1[card]")
        overlay("card", f"x={cx}:y={cy}:eof_action=pass", "vcard")
        idx += 1
    if plan.mode == "pillow":
        if plan.captions:
            inputs += ["-f", "concat", "-safe", "0", "-i", str(plan.captions.resolve())]
            f.append(f"[{idx}:v]format=yuva420p[cap]")
            overlay("cap", f"x=0:y={plan.captions_y}", "vcap")
            idx += 1
        if plan.hook:
            png, y = plan.hook
            u = plan.hook_until
            still(png, u)
            f.append(f"[{idx}:v]format=yuva420p,fade=t=in:st=0:d=0.15:alpha=1,"
                     f"fade=t=out:st={max(0.0, u - 0.3):.3f}:d=0.3:alpha=1[hook]")
            overlay("hook", f"x=(W-w)/2:y={y}:eof_action=pass", "vhook")
            idx += 1
        if plan.watermark:
            png, y = plan.watermark
            inputs += ["-i", str(png.resolve())]
            f.append(f"[{idx}:v]format=yuva420p[wm]")
            overlay("wm", f"x=(W-w)/2:y={y}", "vwm")
            idx += 1
        if plan.cta:
            png, y = plan.cta
            # Only the frames where the call-to-action is visible, shifted to where it starts.
            still(png, total - plan.cta_from)
            f.append(f"[{idx}:v]format=yuva420p,fade=t=in:st=0:d=0.3:alpha=1,"
                     f"setpts=PTS+{plan.cta_from:.3f}/TB[cta]")
            overlay("cta", f"x=(W-w)/2:y={y}:eof_action=repeat", "vcta")
            idx += 1
    if plan.emoji:
        playlist, ex, ey = plan.emoji
        inputs += ["-f", "concat", "-safe", "0", "-i", str(playlist.resolve())]
        f.append(f"[{idx}:v]format=yuva420p[emo]")
        overlay("emo", f"x={ex}:y={ey}", "vemo")
        idx += 1
    if settings.progress_bar:
        bar_h = max(6, H // 200 // 2 * 2)
        f.append(f"color=c=0xFFE11A@0.9:s={W}x{bar_h}:r={F}:d={total:.3f},format=yuva420p[bar]")
        overlay("bar", f"x='-w+w*t/{total:.3f}':y=0:shortest=1", "vbar")
    if plan.mode == "ass" and plan.ass:
        f.append(f"[{last}]ass={plan.ass.name}:fontsdir={plan.fonts_dir.name if plan.fonts_dir else '.'}[vass]")
        last = "vass"
    f.append(f"[{last}]format=yuv420p[vout]")

    def args(encode: list[str]) -> list[str]:
        return [*inputs, "-filter_complex", ";".join(f), "-map", "[vout]", "-map", f"{audio_i}:a",
                *encode, "-r", str(F), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                "-t", f"{total:.3f}", "-movflags", "+faststart", str(out.resolve())]
    encode = _encode_args(settings, final=True)
    try:
        ffmpeg.run(args(encode), label="final render", cwd=work, progress=progress, duration=total)
    except ffmpeg.FFmpegError:
        if encode[1] == "libx264":
            raise
        # Hardware encoders fail on some machines/drivers (busy GPU, unsupported size): use the CPU.
        log.warning("Encoder %s failed; rendering again with libx264", encode[1])
        ffmpeg.run(args(_encode_args(replace(settings, video_encoder="libx264"), final=True)),
                   label="final render (libx264)", cwd=work, progress=progress, duration=total)
    return out


# Share of the render stage spent preparing shots vs. the final pass (measured on 1080x1920 renders).
SEGMENT_SHARE = 0.3


def render_video(settings: Settings, media: list[MediaItem], scene_durations: list[float], voice: Path,
                 total: float, plan: OverlayPlan, out: Path, work: Path, joins: list[bool] | None = None,
                 progress: Callable[[float], None] | None = None,
                 effects: list[tuple[float, str]] | None = None, background: MediaItem | None = None) -> Path:
    """``progress`` gets the fraction of the render that is done (0..1), several times a second.
    ``effects`` are (time, sound) pairs for the sound-effects track (see sfx.events_for). ``background``
    (split layout): the footage fills the top half and this video plays under it for the whole Short."""
    T = settings.transition_seconds if settings.transition != "none" else 0.0
    lengths = segment_lengths(scene_durations, T, joins)
    report = progress or (lambda frac: None)
    top = settings
    if background is not None:
        top = replace(settings, resolution=split_sizes(settings)[0])
    workers = max(1, min(8, max(2, (os.cpu_count() or 4) // 3), len(media)))  # each ffmpeg is multithreaded
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(prepare_segment, m, L, i, top, work) for i, (m, L) in enumerate(zip(media, lengths))]
        bg_fut = None
        if background is not None:
            bottom = replace(settings, resolution=split_sizes(settings)[1])
            bg_fut = ex.submit(prepare_segment, background, total, 99, bottom, work)
        for done, _ in enumerate(concurrent.futures.as_completed(futs), 1):
            report(SEGMENT_SHARE * done / len(futs))
        segments = [fu.result() for fu in futs]
        bg_seg = bg_fut.result() if bg_fut else None
    music = pick_music(settings)
    if music:
        log.info("Music: %s", music.name)
    fx = None
    if effects and settings.sound_effects and settings.sfx_volume > 0:
        fx = sfx.track(effects, total, work / "effects.wav")
        if fx:
            log.info("Sound effects: %d", len(effects))
    return compose(settings, segments, lengths, voice, total, plan, out, work, music, joins,
                   progress=lambda frac: report(SEGMENT_SHARE + (1 - SEGMENT_SHARE) * frac), effects=fx,
                   background=bg_seg)


def split_sizes(settings: Settings) -> tuple[tuple[int, int], tuple[int, int]]:
    """(top, bottom) frame sizes of the split layout: footage above, background video below."""
    W, H = settings.resolution
    top = H // 2 // 2 * 2
    return (W, top), (W, H - top)


def frame_quality(img) -> float:
    """0..1 for a thumbnail candidate: sharp (text and detail fully drawn, not mid-fade or motion-blurred),
    well exposed, colourful and with some contrast."""
    from PIL import ImageFilter, ImageStat
    rgb = img.convert("RGB")
    gray = rgb.convert("L")
    sharp = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).mean[0]
    st = ImageStat.Stat(gray)
    exposure = 1 - min(1.0, abs(st.mean[0] - 125) / 125)
    sat = ImageStat.Stat(rgb.convert("HSV")).mean[1]
    return (0.45 * min(1.0, sharp / 30) + 0.25 * min(1.0, sat / 140) + 0.2 * exposure
            + 0.1 * min(1.0, st.stddev[0] / 70))


def pick_cover(video: Path, dest: Path, work: Path, *, total: float, until: float,
               avoid: list[float] | tuple = ()) -> float:
    """Save the best frame of the opening seconds (where the hook is on screen) as the cover, skipping the
    moments around a cut where two shots are blended. Returns the time it was taken from."""
    from PIL import Image
    start = min(0.35, total / 4)
    end = max(start + 0.4, min(until, total - 0.1))
    n = 12
    rate = n / (end - start)
    cand = work / "cover"
    cand.mkdir(parents=True, exist_ok=True)
    ffmpeg.run(["-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(video), "-vf",
                f"fps={rate:.4f},scale=270:-2", str(cand / "c%02d.png")], label="cover candidates")
    best_t, best_q = min(1.2, total / 3), -1.0
    for k, f in enumerate(sorted(cand.glob("c*.png"))):
        t = start + (k + 0.5) / rate
        if any(abs(t - c) < 0.3 for c in avoid):
            continue
        with Image.open(f) as img:
            q = frame_quality(img)
        if q > best_q:
            best_t, best_q = t, q
    extract_frame(video, best_t, dest)
    return best_t


def extract_frame(video: Path, at: float, dest: Path) -> Path:
    ffmpeg.run(["-ss", f"{at:.2f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(dest)], label="cover")
    return dest
