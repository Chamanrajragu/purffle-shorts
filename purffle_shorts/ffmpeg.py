"""Locate and drive ffmpeg. Uses the system ffmpeg if present, otherwise the static build
shipped with the ``imageio-ffmpeg`` package — so no manual install is needed."""

from __future__ import annotations

import functools
import json
import logging
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
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


_procs: set[subprocess.Popen] = set()
_procs_lock = threading.Lock()


def kill_all() -> int:
    """Stop every running ffmpeg (used when a Studio job is cancelled). Returns how many were stopped."""
    with _procs_lock:
        procs = list(_procs)
    for p in procs:
        try:
            p.kill()
        except OSError:
            pass
    return len(procs)


def run(args: list[str], *, label: str = "ffmpeg", cwd: str | Path | None = None, timeout: int = 1800,
        loglevel: str = "error", progress: Callable[[float], None] | None = None, duration: float = 0.0) -> str:
    """Run ffmpeg and return what it wrote to stderr (with ``loglevel="info"`` that includes filter reports).

    With ``progress`` and the output ``duration``, ffmpeg reports how far it has got and ``progress`` is
    called with a 0..1 fraction about twice a second. A cancelled job stops the process at once."""
    from .utils import CANCEL, Cancelled
    watch = progress is not None and duration > 0
    extra = ["-nostats", "-progress", "pipe:1"] if watch else []
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", loglevel, *extra, "-y", *args]
    log.debug("%s: %s", label, " ".join(cmd))
    if CANCEL.is_set():
        raise Cancelled(label)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE if watch else subprocess.DEVNULL, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", cwd=cwd)
    with _procs_lock:
        _procs.add(proc)
    deadline = time.monotonic() + timeout
    stderr = ""
    try:
        if watch:
            err: list[str] = []
            reader = threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True)
            reader.start()
            for line in proc.stdout:
                key, _, value = line.strip().partition("=")
                if key in ("out_time_us", "out_time_ms") and value.lstrip("-").isdigit():
                    try:
                        progress(max(0.0, min(1.0, int(value) / 1e6 / duration)))
                    except Exception:  # a progress display must never break a render
                        log.debug("progress callback failed", exc_info=True)
                if CANCEL.is_set() or time.monotonic() > deadline:
                    proc.kill()
            proc.wait()
            reader.join(timeout=5)
            stderr = "".join(err)
        else:
            while True:
                try:
                    stderr = proc.communicate(timeout=0.5)[1] or ""
                    break
                except subprocess.TimeoutExpired:
                    if CANCEL.is_set() or time.monotonic() > deadline:
                        proc.kill()
    finally:
        if proc.poll() is None:  # interrupted (Ctrl+C, an error above): don't leave ffmpeg running
            proc.kill()
            proc.wait()
        with _procs_lock:
            _procs.discard(proc)
    if CANCEL.is_set():
        raise Cancelled(label)
    if time.monotonic() > deadline and proc.returncode != 0:
        raise FFmpegError(f"{label} timed out after {timeout}s")
    if proc.returncode != 0:
        tail = "\n".join(stderr.strip().splitlines()[-12:])
        raise FFmpegError(f"{label} failed (exit {proc.returncode}):\n{tail}")
    return stderr


def loudnorm_report(stderr: str) -> dict | None:
    """The JSON block that ``loudnorm=print_format=json`` writes at the end of a run."""
    end = stderr.rfind("}")
    start = stderr.rfind("{", 0, end)
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(stderr[start:end + 1])
    except ValueError:
        return None


def loudness(path: str | Path) -> float | None:
    """Integrated loudness (LUFS) of a file's audio, or None when it is silent or unreadable."""
    try:
        err = run(["-i", str(path), "-vn", "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                  label="measure loudness", loglevel="info")
    except FFmpegError:
        return None
    rep = loudnorm_report(err) or {}
    try:
        value = float(rep.get("input_i", "nan"))
    except ValueError:
        return None
    return value if value > -70 else None


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


def silences(path: str | Path, noise_db: float = -38.0, min_seconds: float = 0.12) -> list[tuple[float, float]]:
    """(start, end) of every pause in a file's audio."""
    try:
        err = run(["-i", str(path), "-vn", "-af", f"silencedetect=noise={noise_db}dB:d={min_seconds}",
                   "-f", "null", "-"], label="find pauses", loglevel="info")
    except FFmpegError:
        return []
    out, start = [], None
    for m in re.finditer(r"silence_(start|end): (-?[\d.]+)", err):
        t = max(0.0, float(m.group(2)))
        if m.group(1) == "start":
            start = t
        elif start is not None:
            out.append((start, t))
            start = None
    if start is not None:  # silent until the end
        out.append((start, duration(path)))
    return out


def duration(path: str | Path) -> float:
    return probe(path)["duration"]

