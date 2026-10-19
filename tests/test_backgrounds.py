"""Background video under stories: picking a stretch, the full-screen and split layouts end to end."""

import subprocess

import pytest
from PIL import Image

from purffle_shorts import ffmpeg
from purffle_shorts import media as M
from purffle_shorts.config import ConfigError, Settings
from purffle_shorts.pipeline import Studio
from purffle_shorts.render import split_sizes

from .conftest import needs_ffmpeg


def _video(path, colour="red", seconds=12, size="320x180"):
    subprocess.run([ffmpeg.ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"color=c={colour}:s={size}:r=25:d={seconds}", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def _pixel(video, t, x_frac, y_frac):
    img = video.parent / f"px_{t}.png"
    subprocess.run([ffmpeg.ffmpeg_bin(), "-v", "error", "-y", "-ss", str(t), "-i", str(video), "-frames:v", "1",
                    str(img)], check=True)
    with Image.open(img) as im:
        rgb = im.convert("RGB")
        return rgb.getpixel((int(rgb.width * x_frac), int(rgb.height * y_frac)))


@needs_ffmpeg
def test_background_item_picks_a_stretch_that_fits(settings, tmp_path):
    folder = tmp_path / "bg"
    folder.mkdir()
    _video(folder / "a.mp4", seconds=30)
    (folder / "notes.txt").write_text("not a video")
    item = M.background_item(settings.with_overrides(background_video=str(folder)), 10.0)
    assert item.source == "background" and item.path.name == "a.mp4"
    assert 0 <= item.extra["start"] <= 30 - 10
    short = M.background_item(settings.with_overrides(background_video=str(_video(tmp_path / "s.mp4", seconds=4))),
                              10.0)
    assert short.extra["start"] == 0.0                 # too short to choose: it loops from the start
    assert M.background_item(settings.with_overrides(background_video=str(tmp_path / "missing")), 5) is None
    assert M.background_item(settings, 5) is None


def test_layout_setting_is_checked(monkeypatch):
    monkeypatch.setenv("BACKGROUND_LAYOUT", "sideways")
    with pytest.raises(ConfigError):
        Settings.from_env()


def test_split_sizes_are_even_and_fill_the_frame(settings):
    for res in [(1080, 1920), (720, 1280), (1080, 1350)]:
        (w1, h1), (w2, h2) = split_sizes(settings.with_overrides(resolution=res))
        assert w1 == w2 == res[0] and h1 + h2 == res[1] and h1 % 2 == 0 and h2 % 2 == 0


def _demo(settings, tmp_path, **kw):
    s = settings.with_overrides(offline=True, resolution=(270, 480), fps=15, tts_engine="silent", transition="none",
                                hook_overlay=False, end_cta="", watermark="none", progress_bar=False,
                                caption_style="minimal", **kw)
    r = Studio(s).make("demo", upload=False)
    assert r.ok, r.error
    return r


@needs_ffmpeg
def test_full_layout_plays_the_background_for_the_whole_short(settings, tmp_path):
    bg = _video(tmp_path / "game.mp4", "red", 120)
    r = _demo(settings, tmp_path, background_video=str(bg), background_layout="full")
    info = ffmpeg.probe(r.video)
    for t in (0.5, info["duration"] / 2, info["duration"] - 0.5):
        red, g, b = _pixel(r.video, t, 0.5, 0.95)
        assert red > 180 and g < 80 and b < 80
    import json
    meta = json.loads((r.folder / "metadata.json").read_text())
    assert [v["source"] for v in meta["visuals"]] == ["background"]


@needs_ffmpeg
def test_split_layout_puts_footage_on_top_and_the_background_below(settings, tmp_path):
    bg = _video(tmp_path / "game.mp4", "red", 120)
    r = _demo(settings, tmp_path, background_video=str(bg), background_layout="split")
    info = ffmpeg.probe(r.video)
    assert (info["width"], info["height"]) == (270, 480)
    red, g, b = _pixel(r.video, 2.0, 0.5, 0.92)          # bottom half: the background
    assert red > 180 and g < 80 and b < 80
    top = _pixel(r.video, 2.0, 0.5, 0.1)                 # top half: the scene's own (generated) footage
    assert not (top[0] > 180 and top[1] < 80 and top[2] < 80)


def test_background_videos_are_never_used_as_scene_footage(settings, tmp_path):
    media = tmp_path / "media"
    (media / "backgrounds").mkdir(parents=True)
    (media / "backgrounds" / "parkour.mp4").write_bytes(b"x")
    (media / "octopus.mp4").write_bytes(b"x")
    elsewhere = tmp_path / "game.mp4"
    elsewhere.write_bytes(b"x")
    s = settings.with_overrides(media_dir=str(media), visual_sources=["local"])
    found = [i.path.name for i in M.Visuals(s)._local("octopus")]
    assert found == ["octopus.mp4"]
    (media / "game.mp4").write_bytes(b"x")
    s2 = s.with_overrides(background_video=str(media / "game.mp4"))
    assert [i.path.name for i in M.Visuals(s2)._local("octopus")] == ["octopus.mp4"]


def test_doctor_reports_the_background_and_the_new_editing(settings, tmp_path):
    from purffle_shorts.doctor import checks
    bg = tmp_path / "bg"
    bg.mkdir()
    _video(bg / "a.mp4", seconds=2)
    out = {c["label"]: c for c in checks(settings.with_overrides(background_video=str(bg), upload=False,
                                                                 localize_metadata=["es"]))}
    assert out["Background video"]["ok"] is True and "1 video" in out["Background video"]["detail"]
    assert "Footage" not in out                       # a full-screen background needs no stock footage
    assert "emoji" in out["Retention editing"]["detail"] and "es" in out["SEO"]["detail"]
    assert "jump cuts" in out["Clip editing"]["detail"]
