"""Full offline render: silent voice, generated backgrounds, real ffmpeg. No network needed."""

import json

import pytest

from purffle_shorts import ffmpeg
from purffle_shorts.pipeline import Studio

from .conftest import needs_ffmpeg


@needs_ffmpeg
@pytest.mark.parametrize("renderer", ["pillow", "ass"])
def test_offline_render(settings, monkeypatch, renderer):
    if renderer == "ass" and not ffmpeg.has_filter("ass"):
        pytest.skip("ffmpeg built without libass")
    monkeypatch.setenv("CAPTION_RENDERER", renderer)
    s = settings.with_overrides(offline=True, tts_engine="silent", resolution=(360, 640), fps=24,
                                transition="random", music_volume=0.0)
    r = Studio(s).make()
    assert r.ok, r.error
    info = ffmpeg.probe(r.video)
    assert (info["width"], info["height"]) == (360, 640)
    assert info["has_audio"] and info["duration"] > 5
    for name in ("cover.jpg", "captions.srt", "metadata.json", "script.json"):
        assert (r.folder / name).exists()
    meta = json.loads((r.folder / "metadata.json").read_text())
    assert meta["title"].endswith("#shorts") and meta["resolution"] == "360x640"
    assert not (r.folder / "work").exists()
    hist = Studio(s).history.recent(1)[0]
    assert hist["status"] == "rendered"


@needs_ffmpeg
def test_render_from_script_file_needs_no_llm(settings, tmp_path):
    f = tmp_path / "script.json"
    f.write_text(json.dumps({"title": "Honey Never Spoils", "hook_text": "3000 YEARS OLD",
                             "scenes": [{"narration": "Archaeologists found honey in Egyptian tombs.",
                                         "search_query": "honey jar"},
                                        {"narration": "It was still safe to eat.", "search_query": "honey"}]}))
    # Not offline, yet no LLM key is set: a script file must not need one.
    s = settings.with_overrides(tts_engine="silent", resolution=(360, 640), fps=24, music_volume=0.0)
    r = Studio(s).make(script_file=f)
    assert r.ok, r.error
    meta = json.loads((r.folder / "metadata.json").read_text())
    assert meta["title"] == "Honey Never Spoils #shorts"
    assert meta["llm"] == "script file" and meta["source"] == "script"
