"""ffmpeg rendering. Each scene is normalised to a 9:16 segment (cover-crop, colour grade, Ken Burns for
stills), then one final pass joins them with transitions and adds captions, overlays, a progress bar,
ducked background music and loudness normalisation. No MoviePy, no ImageMagick."""

from __future__ import annotations

import concurrent.futures
import logging
import random
import sys
from pathlib import Path

from . import ffmpeg
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
    if not final:  # intermediates: fast, visually lossless
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p"]
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
        src = ffmpeg.duration(item.path)
        pre: list[str] = []
        if src <= seconds + 0.1:
            pre = ["-stream_loop", "-1"]
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

    # Generated animated background (no footage found / offline demo).
    c0, c1 = random.choice(GRADIENT_PALETTES)
    if ffmpeg.has_filter("gradients"):
        src = (f"gradients=s={W}x{H}:r={F}:c0={c0}:c1={c1}:x0=0:y0=0:x1={W}:y1={H}:"
               f"speed=0.02:d={seconds:.3f}:seed={random.randint(0, 9999)}")
    else:
        src = f"color=c={c0}:s={W}x{H}:r={F}:d={seconds:.3f}"
    ffmpeg.run(["-f", "lavfi", "-i", src, "-vf", "setsar=1,format=yuv420p", *enc, "-frames:v", str(frames),
                str(out)], label=f"segment {idx} (generated)")
    return out


def segment_lengths(scene_durations: list[float], transition: float) -> list[float]:
    """Pad segments so centred cross-fades keep every cut on its narration boundary."""
    n = len(scene_durations)
    if n <= 1 or transition <= 0:
        return list(scene_durations)
    half = transition / 2
    out = []
    for i, d in enumerate(scene_durations):
        extra = (half if i in (0, n - 1) else transition)
        out.append(d + extra)
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


def compose(settings: Settings, segments: list[Path], lengths: list[float], voice: Path, total: float,
            plan: OverlayPlan, out: Path, work: Path, music: Path | None) -> Path:
    W, H, F = settings.width, settings.height, settings.fps
    T = settings.transition_seconds if settings.transition != "none" and len(segments) > 1 else 0.0
    # ffmpeg runs inside `work` (so the libass paths stay simple): every input must be absolute.
    inputs: list[str] = []
    for seg in segments:
        inputs += ["-i", str(Path(seg).resolve())]
    n = len(segments)
    idx = n
    voice_i = idx
    inputs += ["-i", str(Path(voice).resolve())]
    idx += 1
    music_i = None
    if music:
        music_i = idx
        inputs += ["-stream_loop", "-1", "-i", str(Path(music).resolve())]
        idx += 1

    f: list[str] = []
    for i in range(n):
        f.append(f"[{i}:v]settb=AVTB,setpts=PTS-STARTPTS,fps={F},format=yuv420p[s{i}]")
    if n == 1:
        last = "s0"
    elif T > 0:
        acc, last = lengths[0], "s0"
        for i in range(1, n):
            tr = random.choice(TRANSITIONS) if settings.transition == "random" else settings.transition
            f.append(f"[{last}][s{i}]xfade=transition={tr}:duration={T:.3f}:offset={acc - T:.3f}[x{i}]")
            acc += lengths[i] - T
            last = f"x{i}"
    else:
        f.append("".join(f"[s{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[cat]")
        last = "cat"

    def overlay(src_label: str, expr: str, name: str):
        nonlocal last
        f.append(f"[{last}][{src_label}]overlay={expr}[{name}]")
        last = name

    if plan.mode == "pillow":
        if plan.captions:
            inputs += ["-f", "concat", "-safe", "0", "-i", str(plan.captions.resolve())]
            f.append(f"[{idx}:v]format=rgba[cap]")
            overlay("cap", f"x=0:y={plan.captions_y}:format=auto", "vcap")
            idx += 1
        if plan.hook:
            png, y = plan.hook
            u = plan.hook_until
            inputs += ["-framerate", str(F), "-loop", "1", "-t", f"{u:.3f}", "-i", str(png.resolve())]
            f.append(f"[{idx}:v]format=rgba,fade=t=in:st=0:d=0.15:alpha=1,"
                     f"fade=t=out:st={max(0.0, u - 0.3):.3f}:d=0.3:alpha=1[hook]")
            overlay("hook", f"x=(W-w)/2:y={y}:eof_action=pass:format=auto", "vhook")
            idx += 1
        if plan.watermark:
            png, y = plan.watermark
            inputs += ["-i", str(png.resolve())]
            f.append(f"[{idx}:v]format=rgba[wm]")
            overlay("wm", f"x=(W-w)/2:y={y}:format=auto", "vwm")
            idx += 1
        if plan.cta:
            png, y = plan.cta
            inputs += ["-framerate", str(F), "-loop", "1", "-t", f"{total:.3f}", "-i", str(png.resolve())]
            f.append(f"[{idx}:v]format=rgba,fade=t=in:st={plan.cta_from:.3f}:d=0.3:alpha=1[cta]")
            overlay("cta", f"x=(W-w)/2:y={y}:enable='gte(t,{plan.cta_from:.3f})':format=auto", "vcta")
            idx += 1
    if settings.progress_bar:
        bar_h = max(6, H // 200)
        f.append(f"color=c=0xFFE11A@0.9:s={W}x{bar_h}:r={F}:d={total:.3f}[bar]")
        overlay("bar", f"x='-w+w*t/{total:.3f}':y=0:shortest=1", "vbar")
    if plan.mode == "ass" and plan.ass:
        f.append(f"[{last}]ass={plan.ass.name}:fontsdir={plan.fonts_dir.name if plan.fonts_dir else '.'}[vass]")
        last = "vass"
    f.append(f"[{last}]format=yuv420p[vout]")

    # Audio: voice (+ music ducked under it) -> loudness normalised.
    f.append(f"[{voice_i}:a]aresample=48000,aformat=channel_layouts=stereo,apad=whole_dur={total:.3f}[v0]")
    if music_i is not None:
        fade_out = max(0.0, total - 1.5)
        f.append(f"[{music_i}:a]aresample=48000,aformat=channel_layouts=stereo,volume={settings.music_volume:.3f},"
                 f"afade=t=in:d=0.8,afade=t=out:st={fade_out:.3f}:d=1.5[mus]")
        if settings.music_ducking:  # music dips automatically whenever the voice speaks
            f.append("[v0]asplit=2[voice][sc]")
            f.append("[mus][sc]sidechaincompress=threshold=0.015:ratio=8:attack=15:release=350:makeup=1[duck]")
            f.append("[voice][duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix]")
        else:
            f.append("[v0][mus]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix]")
    else:
        f.append("[v0]anull[mix]")
    f.append(f"[mix]loudnorm=I={settings.loudness_lufs}:TP=-1.5:LRA=11,aresample=48000[aout]")

    args = [*inputs, "-filter_complex", ";".join(f), "-map", "[vout]", "-map", "[aout]",
            *_encode_args(settings, final=True), "-r", str(F),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-t", f"{total:.3f}", "-movflags", "+faststart", str(out.resolve())]
    ffmpeg.run(args, label="final render", cwd=work)
    return out


def render_video(settings: Settings, media: list[MediaItem], scene_durations: list[float], voice: Path,
                 total: float, plan: OverlayPlan, out: Path, work: Path) -> Path:
    T = settings.transition_seconds if settings.transition != "none" else 0.0
    lengths = segment_lengths(scene_durations, T)
    workers = max(1, min(4, len(media)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(prepare_segment, m, L, i, settings, work) for i, (m, L) in enumerate(zip(media, lengths))]
        segments = [fu.result() for fu in futs]
    music = pick_music(settings)
    if music:
        log.info("Music: %s", music.name)
    return compose(settings, segments, lengths, voice, total, plan, out, work, music)


def extract_frame(video: Path, at: float, dest: Path) -> Path:
    ffmpeg.run(["-ss", f"{at:.2f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(dest)], label="cover")
    return dest
