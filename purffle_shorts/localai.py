"""Local AI for the Studio's "Local AI" page: run the whole app without any API key or internet account.

* Ollama: detect it, start it, list installed models, download (pull) recommended ones with live progress,
  delete them and test how fast one writes on this machine.
* Offline voice (Kokoro) and transcription (faster-whisper): show whether they are installed and download their
  model files ahead of time, so the first video doesn't stall on a download.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .llm import ollama_url
from .utils import Cancelled, http

log = logging.getLogger("purffle")

# Chosen for writing short scripts in JSON on an ordinary laptop. "ram" is the memory the model wants (GB).
RECOMMENDED: list[dict] = [
    {"name": "qwen3.5:4b", "label": "Qwen 3.5 4B", "size_gb": 3.4, "ram": 6, "tier": "fast",
     "note": "Best all-rounder for laptops: good JSON, many languages."},
    {"name": "gemma4:e4b", "label": "Gemma 4 E4B", "size_gb": 6.6, "ram": 8, "tier": "balanced",
     "note": "Google's efficient model, strong at hooks and stories."},
    {"name": "qwen3.5:9b", "label": "Qwen 3.5 9B", "size_gb": 6.6, "ram": 12, "tier": "quality",
     "note": "Noticeably better scripts if you have 16 GB of memory."},
    {"name": "gemma4:12b", "label": "Gemma 4 12B", "size_gb": 8.0, "ram": 16, "tier": "quality",
     "note": "The best writer here; wants a GPU or Apple Silicon."},
    {"name": "ministral-3:8b", "label": "Ministral 3 8B", "size_gb": 6.0, "ram": 10, "tier": "balanced",
     "note": "Mistral's small model: fluent European languages."},
    {"name": "granite4.1:3b", "label": "Granite 4.1 3B", "size_gb": 2.1, "ram": 4, "tier": "fast",
     "note": "Smallest download; for older or 8 GB machines."},
    {"name": "llama3.2:3b", "label": "Llama 3.2 3B", "size_gb": 2.0, "ram": 4, "tier": "fast",
     "note": "Meta's small classic, widely tested."},
]

WHISPER_REPOS = {"tiny": "Systran/faster-whisper-tiny", "base": "Systran/faster-whisper-base",
                 "small": "Systran/faster-whisper-small", "medium": "Systran/faster-whisper-medium",
                 "large-v3": "Systran/faster-whisper-large-v3",
                 "large-v3-turbo": "mobiuslabs/faster-whisper-large-v3-turbo"}
KOKORO_REPO = "hexgrad/Kokoro-82M"


def _root() -> str:
    return ollama_url().rsplit("/v1", 1)[0]


def memory_gb() -> float:
    """Total RAM of this machine in GB (0 when it can't be read)."""
    try:
        if sys.platform == "win32":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))  # type: ignore[attr-defined]
            return round(m.ullTotalPhys / 1e9, 1)
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9, 1)
    except (ValueError, OSError, AttributeError):
        return 0.0


def ollama_binary() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    for p in ("/Applications/Ollama.app/Contents/Resources/ollama", "/usr/local/bin/ollama",
              os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe")):
        if p and Path(p).is_file():
            return p
    return None


def ollama_status() -> dict:
    """Is Ollama installed and running, which version, and the installed models with their sizes."""
    out: dict = {"url": _root(), "installed": bool(ollama_binary()), "running": False, "version": "",
                 "models": [], "loaded": [], "memory_gb": memory_gb()}
    try:
        r = http().get(_root() + "/api/tags", timeout=2)
        if not r.ok:
            return out
        out["running"] = out["installed"] = True
        out["models"] = sorted(({
            "name": m.get("name", ""), "size_gb": round((m.get("size") or 0) / 1e9, 1),
            "params": (m.get("details") or {}).get("parameter_size", ""),
            "family": (m.get("details") or {}).get("family", ""),
            "quant": (m.get("details") or {}).get("quantization_level", ""),
            "modified": m.get("modified_at", ""),
        } for m in r.json().get("models", [])), key=lambda m: m["name"])
        v = http().get(_root() + "/api/version", timeout=2)
        out["version"] = v.json().get("version", "") if v.ok else ""
        ps = http().get(_root() + "/api/ps", timeout=2)
        if ps.ok:
            out["loaded"] = [{"name": m.get("name"), "vram_gb": round((m.get("size_vram") or 0) / 1e9, 1)}
                             for m in ps.json().get("models", [])]
    except Exception:
        pass
    return out


def recommended(installed: list[str] | None = None) -> list[dict]:
    have = set(installed or [])
    ram = memory_gb()
    return [{**m, "installed": m["name"] in have or f"{m['name']}:latest" in have,
             "fits": not ram or m["ram"] <= ram * 0.75} for m in RECOMMENDED]


def start_ollama() -> bool:
    """Start the Ollama server in the background (returns True once it answers)."""
    if ollama_status()["running"]:
        return True
    exe = ollama_binary()
    if not exe:
        return False
    if sys.platform == "darwin" and Path("/Applications/Ollama.app").exists():
        subprocess.Popen(["open", "-g", "-a", "Ollama"])
    else:
        flags = {"creationflags": 0x08000000} if sys.platform == "win32" else {"start_new_session": True}
        subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **flags)
    for _ in range(30):
        time.sleep(0.5)
        if ollama_status()["running"]:
            return True
    return False


def valid_model_name(name: str) -> bool:
    import re
    return bool(re.fullmatch(r"[\w][\w./-]{0,120}(:[\w.-]{1,60})?", name or ""))


def pull(model: str, progress: Callable[[str, int, str], None], stop: threading.Event | None = None) -> None:
    """Download a model into Ollama, reporting progress (stage "download", percent, message)."""
    if not valid_model_name(model):
        raise ValueError(f"not a model name: {model!r}")
    r = http().post(_root() + "/api/pull", json={"model": model, "stream": True}, stream=True,
                    timeout=(10, 600))
    if not r.ok:
        raise RuntimeError(f"Ollama could not pull {model}: HTTP {r.status_code} {r.text[:200]}")
    last, layers = 0.0, {}
    try:
        for line in r.iter_lines(decode_unicode=True):
            if stop is not None and stop.is_set():
                raise Cancelled("cancelled")
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("error"):
                raise RuntimeError(f"{model}: {ev['error']}")
            status = ev.get("status", "")
            if ev.get("digest") and ev.get("total"):
                layers[ev["digest"]] = (ev.get("completed") or 0, ev["total"])
            done = sum(c for c, _ in layers.values())
            total = sum(t for _, t in layers.values())
            pct = int(done * 100 / total) if total else 0
            if time.monotonic() - last > 0.5 or status == "success":
                last = time.monotonic()
                msg = (f"{done / 1e9:.2f} of {total / 1e9:.2f} GB" if total and status.startswith("pulling")
                       else status)
                progress("download", min(99, pct) if status != "success" else 100, msg)
            if status == "success":
                log.info("Downloaded %s (%.1f GB)", model, total / 1e9)
                return
    finally:
        r.close()
    raise RuntimeError(f"{model}: the download stopped before it finished")


def delete(model: str) -> bool:
    if not valid_model_name(model):
        return False
    r = http().delete(_root() + "/api/delete", json={"model": model}, timeout=30)
    return r.ok


def benchmark(model: str) -> dict:
    """Write a tiny JSON reply with the model and measure load time and words per second."""
    t0 = time.monotonic()
    r = http().post(_root() + "/api/chat", timeout=(10, 600), json={
        "model": model, "stream": False, "think": False, "format": "json",
        "messages": [{"role": "user", "content": "Give a 25-word surprising fact about octopuses as JSON "
                      '{"fact": "..."}'}],
        "options": {"num_predict": 120}})
    if not r.ok:
        raise RuntimeError(f"{model}: HTTP {r.status_code} {r.text[:200]}")
    d = r.json()
    gen_s = (d.get("eval_duration") or 0) / 1e9
    tokens = d.get("eval_count") or 0
    tps = tokens / gen_s if gen_s else 0.0
    return {"model": model, "seconds": round(time.monotonic() - t0, 1),
            "load_seconds": round((d.get("load_duration") or 0) / 1e9, 1),
            "tokens_per_second": round(tps, 1),
            # a script plus its review is roughly 1500 output tokens
            "script_minutes": round(1500 / tps / 60, 1) if tps else None,
            "reply": ((d.get("message") or {}).get("content") or "")[:300]}


# ---------------------------------------------------------------- offline voice and transcription
def _hf_cached(repo: str) -> bool:
    home = Path(os.getenv("HF_HOME") or Path.home() / ".cache" / "huggingface")
    snap = home / "hub" / f"models--{repo.replace('/', '--')}" / "snapshots"
    return snap.is_dir() and any(snap.iterdir())


def offline_status(whisper_name: str = "small") -> dict:
    from .tts import whisper_model
    has_kokoro = importlib.util.find_spec("kokoro") is not None
    has_fw = importlib.util.find_spec("faster_whisper") is not None
    try:
        wname = whisper_model() if whisper_name in ("", "auto") else whisper_name
    except Exception:
        wname = "small"
    system = {"darwin": "macOS voices (say)", "win32": "Windows voices (SAPI)"}.get(sys.platform, "espeak-ng")
    system_ok = sys.platform in ("darwin", "win32") or bool(shutil.which("espeak-ng") or shutil.which("espeak"))
    return {
        "kokoro": {"installed": has_kokoro, "downloaded": has_kokoro and _hf_cached(KOKORO_REPO),
                   "size_mb": 330, "install": "pip install 'purffle-shorts[kokoro]'"},
        "whisper": {"installed": has_fw, "model": wname,
                    "downloaded": has_fw and _hf_cached(WHISPER_REPOS.get(wname, f"Systran/faster-whisper-{wname}")),
                    "models": {n: _hf_cached(r) for n, r in WHISPER_REPOS.items()},
                    "install": "pip install 'purffle-shorts[whisper]'"},
        "system": {"available": system_ok, "name": system},
    }


def prefetch(what: str, progress: Callable[[str, int, str], None], whisper_name: str = "small") -> str:
    """Download the Kokoro voice or a faster-whisper model now, instead of in the middle of a video."""
    if what == "kokoro":
        progress("download", 10, "Loading the Kokoro voice model (about 330 MB the first time)…")
        from kokoro import KPipeline
        pipe = KPipeline(lang_code="a")
        progress("download", 80, "Testing the voice…")
        for _ in pipe("Ready.", voice="af_heart"):
            break
        return "Kokoro voice ready"
    if what == "whisper":
        progress("download", 10, f"Downloading faster-whisper {whisper_name}…")
        from faster_whisper import WhisperModel
        WhisperModel(whisper_name, device="cpu", compute_type="int8")
        return f"faster-whisper {whisper_name} ready"
    raise ValueError(f"unknown download {what!r}")
