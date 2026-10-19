"""Sound effects (where they go, how loud) and key-word emphasis in captions."""

import wave
from array import array
from pathlib import Path

from PIL import Image

from purffle_shorts import ffmpeg, overlays, render, sfx
from purffle_shorts.script import SCRIPT_SCHEMA, normalize, offline_script
from purffle_shorts.timing import Chunk, Word

from .conftest import needs_ffmpeg


def _samples(path: Path) -> array:
    with wave.open(str(path)) as w:
        assert w.getframerate() == sfx.RATE and w.getnchannels() == 1
        return array("h", w.readframes(w.getnframes()))


def test_effect_placement():
    ev = sfx.events_for(scene_starts=[2.0, 2.5, 6.0], hook=True)
    assert ev == [(0.05, "hit"), (2.0, "whoosh"), (6.0, "whoosh")]  # 2.5 s is too soon after 2.0 s
    chat = sfx.events_for(scene_starts=[2.0, 4.0], message_starts=[0.0, 1.1, 2.3])
    assert chat == [(0.0, "pop"), (1.1, "pop"), (2.3, "pop")]     # a chat pops, it doesn't whoosh
    assert sfx.events_for(scene_starts=[]) == []


def test_track_puts_each_effect_peak_on_its_moment(tmp_path):
    total = 4.0
    path = sfx.track([(1.0, "whoosh"), (3.0, "pop")], total, tmp_path / "fx.wav", seed=3)
    pcm = _samples(path)
    assert len(pcm) == int(total * sfx.RATE)

    def loudest(a: float, b: float) -> float:
        lo, hi = int(a * sfx.RATE), int(b * sfx.RATE)
        k = max(range(lo, hi), key=lambda i: abs(pcm[i]))
        return k / sfx.RATE
    assert abs(loudest(0.5, 1.5) - 1.0) < 0.08
    assert abs(loudest(2.9, 3.1) - 3.0) < 0.02
    assert max(abs(v) for v in pcm[: int(0.6 * sfx.RATE)]) == 0       # silence before the whoosh starts
    assert sfx.track([], total, tmp_path / "none.wav") is None
    assert sfx.track([(9.0, "pop")], total, tmp_path / "late.wav") is None


@needs_ffmpeg
def test_effects_sit_11_db_under_the_voice(settings, tmp_path):
    voice = tmp_path / "voice.wav"
    ffmpeg.run(["-f", "lavfi", "-i", "sine=f=220:d=4", "-af", "volume=0.3", "-ar", "48000", str(voice)])
    fx = sfx.track([(1.0, "whoosh"), (2.5, "hit")], 4.0, tmp_path / "fx.wav", seed=1)
    gain = render._fx_gain(settings.with_overrides(voice_enhance=False), voice, fx)
    loud = tmp_path / "loud.wav"
    ffmpeg.run(["-i", str(fx), "-af", f"volume={gain:.5f}", str(loud)])
    v, e = render._measure(voice, ""), render._measure(loud, "")
    assert abs((v - e) - render.SFX_BELOW_VOICE) < 1.0
    half = render._fx_gain(settings.with_overrides(voice_enhance=False, sfx_volume=0.5), voice, fx)
    assert abs(half / gain - 0.5) < 1e-6


@needs_ffmpeg
def test_mix_with_effects_still_hits_the_loudness_target(settings, tmp_path):
    voice = tmp_path / "voice.wav"
    ffmpeg.run(["-f", "lavfi", "-i", "sine=f=300:d=3", "-ar", "48000", str(voice)])
    fx = sfx.track([(1.0, "whoosh")], 3.0, tmp_path / "fx.wav", seed=2)
    out = render.mix_audio(settings, voice, 3.0, None, tmp_path, effects=fx)
    assert abs(ffmpeg.loudness(out) - settings.loudness_lufs) < 1.0
    assert abs(ffmpeg.duration(out) - 3.0) < 0.05


# ------------------------------------------------------------------------------------------ emphasis
def test_script_schema_asks_for_emphasis_and_normalize_keeps_only_spoken_words():
    assert "emphasis" in SCRIPT_SCHEMA["properties"]["scenes"]["items"]["required"]
    data = {"title": "t", "scenes": [{"narration": "An octopus has three hearts, and blue blood.",
                                      "emphasis": ["three hearts", "the", "kidneys", "Blue"]}]}
    sc = normalize(data, "octopus", "facts", "en").scenes[0]
    assert sc.emphasis == ["three", "hearts", "blue"]        # split, lower-cased, only words that are spoken
    assert normalize({"scenes": [{"narration": "Hi there."}]}, "x", "facts", "en").scenes[0].emphasis == []


def test_numbers_are_always_emphasised():
    assert overlays.is_emphasised("1,000", frozenset())
    assert overlays.is_emphasised("90%", frozenset())
    assert overlays.is_emphasised("HEARTS,", frozenset({"hearts"}))
    assert not overlays.is_emphasised("THE", frozenset({"hearts"}))


def _has_colour(img: Image.Image, rgb: tuple[int, int, int], tol: int = 30) -> bool:
    colours = img.convert("RGBA").getcolors(maxcolors=1 << 22) or []
    return any(p[3] > 200 and all(abs(c - t) <= tol for c, t in zip(p[:3], rgb)) for _, p in colours)


def test_pillow_captions_draw_key_words_in_the_emphasis_colour(settings):
    s = settings.with_overrides(resolution=(540, 960))
    style = overlays.CAPTION_STYLES["bold"]
    font, _ = overlays.resolve_font(s, style.font)
    green = overlays._rgba(style.emphasis)[:3]
    caps = overlays.PillowCaptions(s, style, font, emphasis={"hearts"})
    words = ["THREE", "HEARTS"]
    size = caps.fit_size(words)
    assert _has_colour(caps.render(words, 0, size), green)           # HEARTS not spoken yet: green
    plain = overlays.PillowCaptions(s, style, font, emphasis=None)
    assert not _has_colour(plain.render(words, 0, size), green)       # CAPTION_EMPHASIS off


def test_ass_captions_carry_the_emphasis_colour(settings, tmp_path):
    style = overlays.CAPTION_STYLES["bold"]
    chunks = [Chunk([Word("three", 0.0, 0.4), Word("hearts", 0.4, 0.9)], 0.0, 0.9)]
    on = overlays.write_ass(settings, style, "Anton", chunks, 2.0, tmp_path / "a.ass", emphasis={"hearts"})
    colour = overlays._ass_color(style.emphasis)
    assert colour in on.read_text()
    off = overlays.write_ass(settings, style, "Anton", chunks, 2.0, tmp_path / "b.ass", emphasis=None)
    assert colour not in off.read_text()


def test_demo_script_marks_key_words(settings):
    script = offline_script("demo", settings)
    assert script.scenes[0].emphasis == ["three", "hearts"]


# ------------------------------------------------------------------------------------------ emoji
REAL_EMOJI_PNG = overlays.emoji_png  # conftest switches the download off for every test


def test_one_emoji_keeps_whole_sequences():
    from purffle_shorts.script import one_emoji
    assert one_emoji("🐙 octopus") == "🐙"
    assert one_emoji("❤️🔥") == "❤️"                         # first emoji with its variation selector
    assert one_emoji("👩‍🚀 astronaut") == "👩‍🚀"              # zero-width-joined sequence
    assert one_emoji("👍🏽") == "👍🏽"                          # skin tone
    assert one_emoji("none") == one_emoji("") == one_emoji(None) == ""
    assert overlays.twemoji_code("❤️") == "2764" and overlays.twemoji_code("👩‍🚀") == "1f469-200d-1f680"


def test_emoji_images_are_downloaded_once(settings, monkeypatch):
    import io
    buf = io.BytesIO()
    Image.new("RGBA", (72, 72), (255, 0, 0, 255)).save(buf, "PNG")
    calls = []

    class Resp:
        status_code, content = 200, buf.getvalue()

    class Session:
        def get(self, url, timeout=None):
            calls.append(url)
            return Resp()
    monkeypatch.setattr(overlays, "http", lambda: Session())
    first = REAL_EMOJI_PNG("🐙", settings.data_path)
    again = REAL_EMOJI_PNG("🐙", settings.data_path)
    assert first == again and first.exists() and len(calls) == 1 and calls[0].endswith("/1f419.png")

    class Missing:
        def get(self, url, timeout=None):
            r = Resp()
            r.status_code = 404
            return r
    monkeypatch.setattr(overlays, "http", lambda: Missing())
    assert REAL_EMOJI_PNG("🫨", settings.data_path) is None


def test_emoji_pop_in_above_the_captions(settings, tmp_path, monkeypatch):
    red = tmp_path / "red.png"
    Image.new("RGBA", (72, 72), (255, 0, 0, 255)).save(red)
    monkeypatch.setattr(overlays, "emoji_png", lambda char, d: red if char == "🐙" else None)
    s = settings.with_overrides(resolution=(540, 960), fps=25)
    playlist, x, y = overlays.emoji_pops(s, [(1.0, 2.5, "🐙"), (3.0, 4.0, "🫨")], 5.0, tmp_path / "e")
    text = playlist.read_text()
    assert text.count("e000_") == 3 and "e001_" not in text      # the missing emoji is simply left out
    durations = [float(line.split()[1]) for line in text.splitlines() if line.startswith("duration")]
    assert abs(sum(durations) - 5.0) < 1e-3 and abs(durations[0] - 1.0) < 1e-3   # blank until it pops in
    assert y + Image.open(playlist.parent / "e000_2.png").height < s.height * overlays.CENTER_Y["center"]
    assert overlays.emoji_pops(s, [(1.0, 2.0, "🫨")], 5.0, tmp_path / "none") is None


@needs_ffmpeg
def test_demo_video_shows_emoji_and_credits_them(settings, monkeypatch, tmp_path):
    import json

    from purffle_shorts.pipeline import Studio
    red = tmp_path / "red.png"
    Image.new("RGBA", (72, 72), (255, 0, 0, 255)).save(red)
    monkeypatch.setattr(overlays, "emoji_png", lambda char, d: red)
    s = settings.with_overrides(offline=True, resolution=(270, 480), fps=15, tts_engine="silent", transition="none",
                                hook_overlay=False, end_cta="", watermark="none", progress_bar=False,
                                caption_style="minimal", color_grade="none")
    r = Studio(s).make("demo", upload=False)
    assert r.ok, r.error
    meta = json.loads((r.folder / "metadata.json").read_text())
    assert meta["description"].endswith(overlays.EMOJI_CREDIT)
    frame = tmp_path / "f.png"
    ffmpeg.run(["-ss", "0.5", "-i", str(r.video), "-frames:v", "1", str(frame)])
    with Image.open(frame) as im:
        px = im.convert("RGB").getpixel((135, int(480 * 0.56 - 270 * 0.21)))
    assert px[0] > 180 and px[1] < 90 and px[2] < 90
