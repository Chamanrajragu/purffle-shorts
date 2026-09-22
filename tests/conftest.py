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
                "OLLAMA_HOST", "UPLOAD"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def settings(tmp_path) -> Settings:
    font = next((f for f in FONT_CANDIDATES if Path(f).exists()), "")
    return Settings(output_dir=str(tmp_path / "out"), data_dir=str(tmp_path / "data"), caption_font=font,
                    upload=False)


needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") or __import__("importlib").util.find_spec("imageio_ffmpeg")),
    reason="ffmpeg not available")
