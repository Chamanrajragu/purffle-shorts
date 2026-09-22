"""Locate and drive ffmpeg. Uses the system ffmpeg if present, otherwise the static build
shipped with the ``imageio-ffmpeg`` package — so no manual install is needed."""

from __future__ import annotations

import functools
import json
import logging
import re
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("purffle")


class FFmpegError(RuntimeError):
    pass


@functools.lru_cache(maxsize=1)
def ffmpeg_bin() -> str:
    import os
    env = os.getenv("FFMPEG_BINARY")
    if env and Path(env).exists():
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:  # pragma: no cover - depends on the machine
        raise FFmpegError("ffmpeg not found. Install it (brew/apt/winget install ffmpeg) "
                          "or `pip install imageio-ffmpeg`.") from e


@functools.lru_cache(maxsize=1)
def ffprobe_bin() -> str | None:
    found = shutil.which("ffprobe")
    if found:
        return found
    sibling = Path(ffmpeg_bin()).with_name("ffprobe" + Path(ffmpeg_bin()).suffix)
    return str(sibling) if sibling.exists() else None


@functools.lru_cache(maxsize=1)
def version() -> str:
    out = subprocess.run([ffmpeg_bin(), "-hide_banner", "-version"], capture_output=True, text=True).stdout
    m = re.search(r"ffmpeg version (\S+)", out)
    return m.group(1) if m else "unknown"


@functools.lru_cache(maxsize=4)
def _listing(kind: str) -> str:
    return subprocess.run([ffmpeg_bin(), "-hide_banner", f"-{kind}"], capture_output=True, text=True).stdout


def has_filter(name: str) -> bool:
    return re.search(rf"^\s*\S+\s+{re.escape(name)}\s", _listing("filters"), re.M) is not None


def has_encoder(name: str) -> bool:
    return re.search(rf"^\s*\S+\s+{re.escape(name)}\s", _listing("encoders"), re.M) is not None


def run(args: list[str], *, label: str = "ffmpeg", cwd: str | Path | None = None, timeout: int = 1800) -> None:
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", *args]
    log.debug("%s: %s", label, " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise FFmpegError(f"{label} timed out after {timeout}s") from e
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-12:])
        raise FFmpegError(f"{label} failed (exit {proc.returncode}):\n{tail}")


def probe(path: str | Path) -> dict:
    """Return {duration, width, height, has_audio, has_video} for a media file."""
    path = str(path)
    fp = ffprobe_bin()
    if fp:
        out = subprocess.run(
            [fp, "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,duration",
             "-of", "json", path], capture_output=True, text=True)
        if out.returncode == 0:
            data = json.loads(out.stdout or "{}")
            streams = data.get("streams", [])
            v = next((s for s in streams if s.get("codec_type") == "video"), {})
            dur = data.get("format", {}).get("duration") or v.get("duration") or 0
            return {
                "duration": float(dur or 0),
                "width": int(v.get("width") or 0),
                "height": int(v.get("height") or 0),
                "has_audio": any(s.get("codec_type") == "audio" for s in streams),
                "has_video": bool(v),
            }
    # Fallback: parse `ffmpeg -i` banner (imageio-ffmpeg ships without ffprobe).
    proc = subprocess.run([ffmpeg_bin(), "-hide_banner", "-i", path], capture_output=True, text=True)
    err = proc.stderr
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0
    vm = re.search(r"Stream #.*Video:.*?(\d{2,5})x(\d{2,5})", err)
    return {
        "duration": dur,
        "width": int(vm.group(1)) if vm else 0,
        "height": int(vm.group(2)) if vm else 0,
        "has_audio": "Audio:" in err,
        "has_video": vm is not None,
    }


def duration(path: str | Path) -> float:
    return probe(path)["duration"]

