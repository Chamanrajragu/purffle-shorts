"""Text-to-speech engines. Every engine returns audio plus per-word timings (native when the engine
provides them, otherwise from an aligner or an estimate) so captions land exactly on the voice.

  edge        Microsoft neural voices — free, no key, 400+ voices, native word timings (default)
  openai      OpenAI gpt-4o-mini-tts / tts-1-hd (OPENAI_API_KEY)
  elevenlabs  ElevenLabs premium voices, native timings (ELEVENLABS_API_KEY)
  kokoro      Kokoro-82M open-weight model, runs locally (pip install kokoro soundfile)
  coqui       Coqui TTS models, runs locally (pip install coqui-tts)
  system      The OS voice (macOS `say`, Linux espeak-ng, Windows SAPI) — offline
  silent      No voice; for layout previews and tests
"""

from __future__ import annotations

import base64
import logging
import random
import subprocess
import sys
import threading
import wave
from dataclasses import dataclass
from pathlib import Path

from . import ffmpeg
from .config import Settings
from .timing import Word, estimate_timings, tokenize, transfer_timings
from .utils import PermanentError, http, raise_for_status, with_retries

log = logging.getLogger("purffle")

# Hand-picked, natural-sounding default voices per language (edge-tts). Override with TTS_VOICE.
EDGE_VOICES = {
    "en": "en-US-AndrewMultilingualNeural", "es": "es-MX-JorgeNeural", "fr": "fr-FR-HenriNeural",
    "de": "de-DE-ConradNeural", "it": "it-IT-DiegoNeural", "pt": "pt-BR-AntonioNeural",
    "hi": "hi-IN-MadhurNeural", "ta": "ta-IN-ValluvarNeural", "te": "te-IN-MohanNeural",
    "bn": "bn-IN-BashkarNeural", "mr": "mr-IN-ManoharNeural", "ur": "ur-PK-AsadNeural",
    "ar": "ar-SA-HamedNeural", "ru": "ru-RU-DmitryNeural", "ja": "ja-JP-KeitaNeural",
    "ko": "ko-KR-InJoonNeural", "zh": "zh-CN-YunxiNeural", "id": "id-ID-ArdiNeural",
    "tr": "tr-TR-AhmetNeural", "nl": "nl-NL-MaartenNeural", "pl": "pl-PL-MarekNeural",
    "vi": "vi-VN-NamMinhNeural", "th": "th-TH-NiwatNeural", "fil": "fil-PH-AngeloNeural",
    "uk": "uk-UA-OstapNeural", "sv": "sv-SE-MattiasNeural",
}
KOKORO_LANG = {"en": ("a", "am_michael"), "es": ("e", "em_alex"), "fr": ("f", "ff_siwis"),
               "hi": ("h", "hm_omega"), "it": ("i", "im_nicola"), "ja": ("j", "jm_kumo"),
               "pt": ("p", "pm_alex"), "zh": ("z", "zm_yunxi")}


@dataclass
class Speech:
    audio: Path
    words: list[Word]
    duration: float
    engine: str
    voice: str
    timing: str  # native | aligned | estimated


def _pick_voice(settings: Settings, default: str) -> str:
    voices = [v.strip() for v in settings.tts_voice.split(",") if v.strip()]
    return random.choice(voices) if voices else default


def _rate_multiplier(rate: str) -> float:
    try:
        return 1.0 + float(rate.strip().rstrip("%")) / 100.0
    except ValueError:
        return 1.0


# ------------------------------------------------------------------------------------------ engines
def _edge(text: str, out: Path, settings: Settings) -> tuple[Path, list[Word], str]:
    try:
        import edge_tts
    except ImportError as e:
        raise PermanentError("edge-tts is not installed:  pip install edge-tts") from e
    voice = _pick_voice(settings, EDGE_VOICES.get(settings.language, EDGE_VOICES["en"]))
    path = out / "voice.mp3"

    def _do():
        words: list[Word] = []
        comm = edge_tts.Communicate(text, voice, rate=settings.tts_rate, boundary="WordBoundary",
                                    receive_timeout=60)
        with open(path, "wb") as f:
            for chunk in comm.stream_sync():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    start = chunk["offset"] / 1e7
                    words.append(Word(chunk["text"], start, start + chunk["duration"] / 1e7))
        if path.stat().st_size == 0:
            raise RuntimeError("edge-tts returned no audio")
        return words

    words = with_retries(_do, attempts=3, label=f"edge-tts {voice}")
    return path, words, voice


def _openai(text: str, out: Path, settings: Settings) -> tuple[Path, list[Word], str]:
    if not settings.openai_api_key:
        raise PermanentError("TTS_ENGINE=openai needs OPENAI_API_KEY")
    model = settings.tts_model or "gpt-4o-mini-tts"
    voice = _pick_voice(settings, "onyx")
    body = {"model": model, "voice": voice, "input": text, "response_format": "mp3"}
    if model.startswith("gpt-4o"):
        body["instructions"] = settings.tts_instructions
    else:
        body["speed"] = max(0.25, min(4.0, _rate_multiplier(settings.tts_rate)))
    path = out / "voice.mp3"

    def _do():
        r = http().post("https://api.openai.com/v1/audio/speech", json=body, timeout=180,
                        headers={"Authorization": f"Bearer {settings.openai_api_key}"})
        raise_for_status(r, "OpenAI TTS")
        path.write_bytes(r.content)

    with_retries(_do, attempts=3, label="OpenAI TTS")
    return path, [], voice


def _elevenlabs(text: str, out: Path, settings: Settings) -> tuple[Path, list[Word], str]:
    if not settings.elevenlabs_api_key:
        raise PermanentError("TTS_ENGINE=elevenlabs needs ELEVENLABS_API_KEY")
    voice = _pick_voice(settings, "pNInz6obpgDQGcFmaJgB")  # "Adam" premade voice; use any voice id
    model = settings.tts_model or "eleven_multilingual_v2"
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps?output_format=mp3_44100_128"
    path = out / "voice.mp3"

    def _do():
        r = http().post(url, timeout=180, headers={"xi-api-key": settings.elevenlabs_api_key},
                        json={"text": text, "model_id": model,
                              "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.3}})
        raise_for_status(r, "ElevenLabs TTS")
        return r.json()

    data = with_retries(_do, attempts=3, label="ElevenLabs TTS")
    path.write_bytes(base64.b64decode(data["audio_base64"]))
    al = data.get("alignment") or data.get("normalized_alignment") or {}
    words: list[Word] = []
    cur, cs, prev_e = "", 0.0, 0.0
    for ch, s, e in zip(al.get("characters", []), al.get("character_start_times_seconds", []),
                        al.get("character_end_times_seconds", [])):
        if ch.isspace():
            if cur:
                words.append(Word(cur, cs, prev_e))
            cur = ""
            continue
        if not cur:
            cs = s
        cur += ch
        prev_e = e
    if cur:
        words.append(Word(cur, cs, prev_e))
    return path, words, voice


_model_lock = threading.Lock()
_model_cache: dict[str, object] = {}


def _kokoro(text: str, out: Path, settings: Settings) -> tuple[Path, list[Word], str]:
    try:
        import numpy as np
        from kokoro import KPipeline
    except ImportError as e:
        raise PermanentError("TTS_ENGINE=kokoro needs:  pip install kokoro soundfile") from e
    lang_code, default_voice = KOKORO_LANG.get(settings.language, KOKORO_LANG["en"])
    voice = _pick_voice(settings, default_voice)
    with _model_lock:
        pipe = _model_cache.get(f"kokoro-{lang_code}")
        if pipe is None:
            pipe = _model_cache[f"kokoro-{lang_code}"] = KPipeline(lang_code=lang_code)
        parts = [np.asarray(audio, dtype=np.float32)
                 for _, _, audio in pipe(text, voice=voice, speed=_rate_multiplier(settings.tts_rate))]
    if not parts:
        raise RuntimeError("kokoro produced no audio")
    pcm = (np.clip(np.concatenate(parts), -1, 1) * 32767).astype("<i2")
    path = out / "voice.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm.tobytes())
    return path, [], voice


def _coqui(text: str, out: Path, settings: Settings) -> tuple[Path, list[Word], str]:
    try:
        from TTS.api import TTS
    except ImportError as e:
        raise PermanentError("TTS_ENGINE=coqui needs:  pip install coqui-tts") from e
    model = settings.tts_model or "tts_models/en/ljspeech/vits"
    path = out / "voice.wav"
    with _model_lock:
        tts = _model_cache.get(model)
        if tts is None:
            tts = _model_cache[model] = TTS(model_name=model)
        tts.tts_to_file(text=text, file_path=str(path))
    return path, [], model


def _system(text: str, out: Path, settings: Settings) -> tuple[Path, list[Word], str]:
    txt = out / "voice.txt"
    txt.write_text(text, encoding="utf-8")
    voice = settings.tts_voice or ""
    if sys.platform == "darwin":
        raw = out / "voice.aiff"
        cmd = ["say", "-r", str(int(185 * _rate_multiplier(settings.tts_rate))), "-o", str(raw), "-f", str(txt)]
        if voice:
            cmd[1:1] = ["-v", voice]
    elif sys.platform.startswith("win"):
        raw = out / "voice.wav"
        ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              f"$s.SetOutputToWaveFile('{raw}'); $s.Speak([IO.File]::ReadAllText('{txt}')); $s.Dispose()")
        cmd = ["powershell", "-NoProfile", "-Command", ps]
    else:
        raw = out / "voice.wav"
        exe = "espeak-ng"
        cmd = [exe, "-v", voice or settings.language, "-s", str(int(165 * _rate_multiplier(settings.tts_rate))),
               "-w", str(raw), "-f", str(txt)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=300)
    except FileNotFoundError as e:
        raise PermanentError(f"System voice not available ({cmd[0]} missing). On Linux: apt install espeak-ng") from e
    return raw, [], voice or "system-default"


def _silent(text: str, out: Path, settings: Settings) -> tuple[Path, list[Word], str]:
    seconds = max(2.0, len(tokenize(text)) / 2.6)
    path = out / "voice.wav"
    ffmpeg.run(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", f"{seconds:.2f}", str(path)],
               label="silent-voice")
    return path, [], "silent"


_ENGINE_FUNCS = {"edge": _edge, "openai": _openai, "elevenlabs": _elevenlabs, "kokoro": _kokoro,
                 "coqui": _coqui, "system": _system, "silent": _silent}


# ------------------------------------------------------------------------------------------ aligners
def _align_faster_whisper(audio: Path, language: str) -> list[Word]:
    from faster_whisper import WhisperModel  # optional dependency
    with _model_lock:
        model = _model_cache.get("whisper")
        if model is None:
            model = _model_cache["whisper"] = WhisperModel("base", device="auto", compute_type="int8")
        segments, _ = model.transcribe(str(audio), language=language, word_timestamps=True)
        return [Word(w.word.strip(), w.start, w.end) for seg in segments for w in (seg.words or [])]


def _align_openai(audio: Path, language: str, api_key: str) -> list[Word]:
    with open(audio, "rb") as f:
        r = http().post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            data={"model": "whisper-1", "response_format": "verbose_json", "language": language,
                  "timestamp_granularities[]": "word"},
            files={"file": (audio.name, f)}, timeout=180)
    raise_for_status(r, "OpenAI alignment")
    return [Word(w["word"], float(w["start"]), float(w["end"])) for w in r.json().get("words", [])]


def _align(audio: Path, settings: Settings) -> tuple[list[Word], str]:
    mode = settings.align
    if mode == "none":
        return [], "estimated"
    lang = settings.language.split("-")[0]
    if mode in ("auto", "faster-whisper"):
        try:
            return _align_faster_whisper(audio, lang), "aligned"
        except ImportError:
            if mode == "faster-whisper":
                log.warning("ALIGN=faster-whisper but it isn't installed (pip install faster-whisper)")
        except Exception as e:
            log.warning("faster-whisper alignment failed: %s", e)
    if mode == "openai" and settings.openai_api_key:
        try:
            return _align_openai(audio, lang, settings.openai_api_key), "aligned"
        except Exception as e:
            log.warning("OpenAI alignment failed: %s", e)
    return [], "estimated"


def synthesize(text: str, out_dir: Path, settings: Settings) -> Speech:
    """Speak ``text`` and return audio + one timed Word per script token."""
    engine = settings.tts_engine if settings.tts_engine in _ENGINE_FUNCS else "edge"
    out_dir.mkdir(parents=True, exist_ok=True)
    audio, native, voice = _ENGINE_FUNCS[engine](text, out_dir, settings)
    dur = ffmpeg.duration(audio)
    if dur <= 0:
        raise RuntimeError(f"{engine} produced unreadable audio: {audio}")
    tokens = tokenize(text, settings.language)
    if native:
        words, timing = transfer_timings(tokens, native, dur), "native"
    elif engine == "silent":
        words, timing = estimate_timings(tokens, dur), "estimated"
    else:
        aligned, timing = _align(audio, settings)
        words = transfer_timings(tokens, aligned, dur) if aligned else estimate_timings(tokens, dur)
    log.info("Voice: %s/%s, %.1fs, %d words (%s timing)", engine, voice, dur, len(words), timing)
    return Speech(audio=audio, words=words, duration=dur, engine=engine, voice=voice, timing=timing)


def list_edge_voices(language: str = "") -> list[dict]:
    import asyncio

    import edge_tts
    voices = asyncio.run(edge_tts.list_voices())
    if language:
        voices = [v for v in voices if v["Locale"].lower().startswith(language.lower())]
    return sorted(voices, key=lambda v: v["ShortName"])
