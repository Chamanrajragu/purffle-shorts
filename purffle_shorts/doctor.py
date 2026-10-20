"""Setup checks shared by `purffle-shorts doctor` and the Studio's System page.

Each check is {"ok": True | False | None, "label": ..., "detail": ...}: True = working, False = must be
fixed before videos can be made, None = information or an optional extra."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from .config import Settings


def checks(s: Settings) -> list[dict]:
    from . import ffmpeg
    from .llm import LLMError, build_provider, ollama_has, ollama_models, resolve_provider_name
    out: list[dict] = []

    def add(ok: bool | None, label: str, detail: str = "") -> None:
        out.append({"ok": ok, "label": label, "detail": detail})

    add(sys.version_info >= (3, 10), "Python", sys.version.split()[0])
    try:
        add(True, "ffmpeg", f"{ffmpeg.version()} ({ffmpeg.ffmpeg_bin()})")
        for flt in ("xfade", "sidechaincompress", "loudnorm", "zoompan"):
            if not ffmpeg.has_filter(flt):
                add(False, f"ffmpeg filter {flt}", "missing — update ffmpeg (6.0+ recommended)")
        add(True if ffmpeg.has_filter("ass") else None, "libass (complex-script captions)",
            "available" if ffmpeg.has_filter("ass") else "not in this ffmpeg build")
    except Exception as e:
        add(False, "ffmpeg", str(e))
    try:
        name = resolve_provider_name(s)
        prov = build_provider(name, s, s.llm_model)
        model = getattr(prov, "model", s.llm_model or "default")
        installed = ollama_models(prov.base_url) if name == "ollama" else []
        if installed is None:
            add(False, "LLM", f"ollama is not running at {prov.base_url} (start it with: ollama serve)")
        elif name == "ollama" and not ollama_has(installed, model):
            add(False, "LLM", f"ollama model '{model}' is not pulled. Run: ollama pull {model}"
                + (f"  (installed: {', '.join(installed)})" if installed else ""))
        else:
            add(True, "LLM", f"{name} (model: {model})"
                + (f", fallbacks: {', '.join(s.llm_fallbacks)}" if s.llm_fallbacks else ""))
    except LLMError as e:
        add(False, "LLM", str(e))
    add(True, "Voice", s.tts_engine + (f" / {s.tts_voice}" if s.tts_voice else ""))
    if s.tts_engine == "elevenlabs" and not s.elevenlabs_api_key:
        add(False, "ElevenLabs key", "ELEVENLABS_API_KEY missing")
    usable = 0
    for src in s.visual_sources:
        if src == "pollinations" and not s.pollinations_api_key:
            add(None, "Visual source pollinations", "no key: anonymous use is limited to about one image every "
                "few minutes, so most scenes fall back to gradients. Set POLLINATIONS_API_KEY")
            continue
        need = {"pexels": s.pexels_api_key, "pixabay": s.pixabay_api_key, "openai-images": s.openai_api_key,
                "pollinations": s.pollinations_api_key}.get(src, "n/a")
        usable += bool(need)
        add(True if need else None, f"Visual source {src}",
            "key found" if need and need != "n/a" else ("no key needed" if need == "n/a" else "API key missing"))
    full_background = bool(s.background_video) and s.background_layout == "full"
    if s.background_video:
        from .media import VIDEO_EXT
        bg = Path(s.background_video).expanduser()
        n = (sum(1 for f in bg.rglob("*") if f.suffix.lower() in VIDEO_EXT) if bg.is_dir()
             else int(bg.is_file()))
        add(bool(n), "Background video", f"{s.background_layout} layout, {n} video(s) in {bg}" if n
            else f"{bg}: no video files found")
    if not usable and not full_background:
        add(False, "Footage", "no usable visual source — every scene would be an animated gradient. Add a free "
            "Pexels or Pixabay key (PEXELS_API_KEY / PIXABAY_API_KEY), or put your own clips in MEDIA_DIR")
    add(True if importlib.util.find_spec("edge_tts") else s.tts_engine != "edge", "edge-tts",
        "installed" if importlib.util.find_spec("edge_tts") else "not installed (pip install edge-tts)")
    from .render import pick_music
    m = pick_music(s)
    add(None, "Music", str(m) if m else f"none (add tracks to {s.music_dir}/)")
    doctor = {"off": "off", "score": "grades scripts (6-part rubric)",
              "rewrite": "grades, rewrites and re-grades scripts; keeps the better one"}.get(s.script_review,
                                                                                          s.script_review)
    if s.script_review == "rewrite" and s.script_review_rounds > 1:
        doctor += f", up to {s.script_review_rounds} rounds until {s.script_target_score}/100"
    add(None, "Script Doctor", doctor)
    look = [name for on, name in ((s.caption_emphasis, "key words in colour"), (s.caption_emoji, "emoji"),
                                  (s.sound_effects and s.sfx_volume > 0, "sound effects")) if on]
    add(None, "Retention editing", ", ".join(look) if look else "off")
    seo = (["real YouTube searches for titles and tags"] if s.seo_keywords else []) \
        + ([f"titles localised in {', '.join(s.localize_metadata)}"] if s.localize_metadata else []) \
        + (["caption tracks uploaded"] if s.upload_captions else [])
    add(None, "SEO", "; ".join(seo) if seo else "off")
    add(None, "Voice cache", "on (re-renders only voice the lines that changed)" if s.voice_cache else "off")
    add(None, "Pacing", f"long scenes cut into shots of up to {s.max_shot_seconds:g}s" if s.max_shot_seconds
        else "one shot per scene")
    add(None, "Output", f"{s.width}x{s.height} ({s.orientation})"
        + (f", also in {', '.join(s.also_languages)}" if s.also_languages else ""))
    has_fw = importlib.util.find_spec("faster_whisper") is not None
    if has_fw:
        from .tts import whisper_model
        fw = f"faster-whisper, model {whisper_model(s)}"
    add(True if has_fw or s.openai_api_key else None, "Clipping long videos",
        fw if has_fw else ("OpenAI transcription" if s.openai_api_key else "needs: pip install faster-whisper"))
    clip_edit = ([f"jump cuts (pauses over {s.clip_max_pause:g}s, um/uh)"] if s.clip_jump_cuts else []) \
        + (["punch-in zoom"] if s.clip_zoom else [])
    add(None, "Clip editing", ", ".join(clip_edit) if clip_edit else "off")
    add(None, "Clip from URLs", "yt-dlp installed" if importlib.util.find_spec("yt_dlp") else "pip install yt-dlp")
    add(None, "Face framing for clips", "OpenCV installed (--crop face)" if importlib.util.find_spec("cv2")
        else "optional: pip install opencv-python-headless")
    if s.notify_webhook:
        add(True, "Notifications", "webhook set")
    if s.learn_from_stats:
        add(True, "Learn from stats", "YOUTUBE_API_KEY" if s.youtube_api_key else "via OAuth (run `auth` once)")
    from .history import History
    queued = len(History(s.data_path / "history.db").ideas("pending"))
    add(None, "Idea queue", f"{queued} planned idea(s)" if queued else "empty (fill it with `plan`)")
    if s.upload:
        if "youtube" in s.publish_to:
            cs = Path(s.client_secrets).exists()
            tok = Path(s.token_file).exists() or Path("token.pickle").exists()
            add(cs or tok, "YouTube OAuth client", s.client_secrets if cs else "credentials.json missing")
            add(tok if cs else None, "YouTube token", "found" if tok else "run: purffle-shorts auth")
        from .crosspost import NAMES, routes
        others = [p for p in s.publish_to if p != "youtube"]
        direct, relay = routes(s, others)
        if direct:
            add(True, "Instagram", f"official Instagram API (account {s.instagram_user_id}, "
                f"Graph {s.instagram_api_version}); posts right away, it can't schedule")
        if relay:
            ready = bool(s.upload_post_api_key and s.upload_post_user)
            add(ready, ", ".join(NAMES.get(p, p) for p in relay),
                f"via Upload-Post, profile {s.upload_post_user}" + (" (TikTok needs a paid Upload-Post plan)"
                                                                   if "tiktok" in relay else "") if ready else
                "set UPLOAD_POST_API_KEY and UPLOAD_POST_USER (upload-post.com), or remove them from PUBLISH_TO"
                + ("; Instagram can also use INSTAGRAM_USER_ID + INSTAGRAM_ACCESS_TOKEN" if "instagram" in relay
                   else ""))
        add(None, "Publishing", f"to {', '.join(s.publish_to)}; {s.privacy}"
            + (f", scheduled at {', '.join(s.publish_times)}" if s.publish_times else "")
            + f", max {s.daily_upload_limit}/day")
    else:
        add(None, "Upload", "disabled (UPLOAD=false)")
    return out
