import os
import shutil
from pathlib import Path

import pytest

from purffle_shorts.config import Settings

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Tests never see the developer's real keys or .env settings."""
    for key in list(os.environ):
        if key.endswith("_API_KEY") or key.startswith(("LLM_", "ANTHROPIC_", "TTS_", "CAPTION_")) or key in (
                "OLLAMA_HOST", "UPLOAD", "ASPECT", "RESOLUTION", "TARGET_SECONDS", "SCRIPT_REVIEW", "ALSO_LANGUAGES",
                "RSS_FEEDS", "NOTIFY_WEBHOOK", "LEARN_FROM_STATS", "PURFFLE_HOME", "KEEP_WORK", "SOUND_EFFECTS",
                "SFX_VOLUME", "BACKGROUND_VIDEO", "BACKGROUND_LAYOUT", "SEO_KEYWORDS", "LOCALIZE_METADATA",
                "UPLOAD_CAPTIONS", "CLIP_JUMP_CUTS", "CLIP_MAX_PAUSE", "CLIP_ZOOM", "STUDIO_TOKEN", "STUDIO_PASSWORD",
                "PUBLISH_TO", "UPLOAD_POST_USER", "TIKTOK_PRIVACY", "INSTAGRAM_USER_ID", "INSTAGRAM_ACCESS_TOKEN",
                "INSTAGRAM_API_VERSION"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _no_search_suggestions(monkeypatch):
    """YouTube search suggestions and emoji images are network calls: off in tests unless a test fakes them."""
    from purffle_shorts import overlays, seo
    monkeypatch.setattr(seo, "suggestions", lambda *a, **k: [])
    monkeypatch.setattr(overlays, "emoji_png", lambda *a, **k: None)  # Twemoji images come from a CDN


@pytest.fixture
def settings(tmp_path) -> Settings:
    font = next((f for f in FONT_CANDIDATES if Path(f).exists()), "")
    return Settings(output_dir=str(tmp_path / "out"), data_dir=str(tmp_path / "data"), caption_font=font,
                    upload=False)


needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") or __import__("importlib").util.find_spec("imageio_ffmpeg")),
    reason="ffmpeg not available")
