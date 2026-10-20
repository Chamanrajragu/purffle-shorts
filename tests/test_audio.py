"""The soundtrack pass: two-pass loudness normalisation, exact length, music ducking, silence."""

import subprocess

from purffle_shorts import ffmpeg
from purffle_shorts.render import mix_audio

from .conftest import needs_ffmpeg

SPEECHLIKE = "{a}*sin(2*PI*210*t)*(0.5+0.5*sin(2*PI*3*t))*gt(sin(2*PI*0.4*t),-0.3)"


def _tone(path, amplitude: float, seconds: float = 12.0):
    expr = SPEECHLIKE.format(a=amplitude)
    subprocess.run([ffmpeg.ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"aevalsrc='{expr}':s=48000:d={seconds}", str(path)], check=True)
    return path


@needs_ffmpeg
def test_soundtrack_hits_the_loudness_target(settings, tmp_path):
    for amp in (0.03, 0.6):  # a very quiet and a loud voice both end at the target
        voice = _tone(tmp_path / f"v{amp}.wav", amp)
        out = mix_audio(settings.with_overrides(music_volume=0.0), voice, 12.0, None, tmp_path)
        assert abs(ffmpeg.loudness(out) - settings.loudness_lufs) < 0.5
        assert abs(ffmpeg.duration(out) - 12.0) < 0.02


@needs_ffmpeg
def test_soundtrack_with_music_is_padded_and_normalised(settings, tmp_path):
    voice = _tone(tmp_path / "v.wav", 0.2, seconds=8.0)
    music = tmp_path / "m.wav"
    subprocess.run([ffmpeg.ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i", "anoisesrc=d=4:c=pink:a=0.2",
                    str(music)], check=True)
    out = mix_audio(settings.with_overrides(music_volume=0.2, loudness_lufs=-16.0), voice, 10.0, music, tmp_path)
    assert abs(ffmpeg.duration(out) - 10.0) < 0.02  # voice padded, short music looped and trimmed
    assert abs(ffmpeg.loudness(out) + 16.0) < 0.5


@needs_ffmpeg
def test_silent_voice_is_left_alone(settings, tmp_path):
    voice = tmp_path / "silent.wav"
    subprocess.run([ffmpeg.ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
                    "-t", "3", str(voice)], check=True)
    out = mix_audio(settings.with_overrides(music_volume=0.0), voice, 4.0, None, tmp_path)
    assert out.name == "mix.wav" and ffmpeg.loudness(out) is None
    assert abs(ffmpeg.duration(out) - 4.0) < 0.02


@needs_ffmpeg
def test_pauses_are_found_where_they_are(tmp_path):
    spans = [(0.3, 2.1), (2.55, 4.9), (5.3, 6.0)]
    expr = "+".join(f"between(t,{a},{b})" for a, b in spans)
    audio = tmp_path / "v.wav"
    subprocess.run([ffmpeg.ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"aevalsrc='0.3*sin(2*PI*200*t)*({expr})':s=24000:d=7", str(audio)], check=True)
    found = ffmpeg.silences(audio)
    expected = [(0.0, 0.3), (2.1, 2.55), (4.9, 5.3), (6.0, 7.0)]
    assert len(found) == len(expected)
    assert all(abs(a - x) < 0.02 and abs(b - y) < 0.02 for (a, b), (x, y) in zip(found, expected))


@needs_ffmpeg
def test_ffmpeg_reports_progress_while_it_works(tmp_path):
    seen = []
    ffmpeg.run(["-f", "lavfi", "-i", "testsrc2=s=320x240:r=25:d=6", "-c:v", "libx264", "-preset", "ultrafast",
                str(tmp_path / "p.mp4")], progress=seen.append, duration=6.0)
    assert seen and seen == sorted(seen) and seen[-1] > 0.9


@needs_ffmpeg
def test_cancel_stops_a_running_ffmpeg_at_once(tmp_path):
    import threading
    import time

    import pytest

    from purffle_shorts.utils import CANCEL, Cancelled
    err = []

    def long_job():
        try:
            ffmpeg.run(["-re", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=25:d=60", "-f", "null", "-"])
        except Exception as e:
            err.append(e)
    t = threading.Thread(target=long_job)
    t.start()
    time.sleep(0.5)
    t0 = time.time()
    CANCEL.set()
    try:
        t.join(5)
        assert not t.is_alive() and time.time() - t0 < 2
        assert err and isinstance(err[0], Cancelled)
        with pytest.raises(Cancelled):
            ffmpeg.run(["-version"])  # nothing new starts while cancelled
    finally:
        CANCEL.clear()


@needs_ffmpeg
def test_cover_is_the_sharpest_frame_not_a_dark_or_blended_one(tmp_path):
    from purffle_shorts.render import pick_cover
    video = tmp_path / "v.mp4"
    # 0-1.3 s: black; 1.3-3 s: a sharp, colourful test pattern
    subprocess.run([ffmpeg.ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x568:r=25:d=3",
                    "-vf", "drawbox=enable='lt(t,1.3)':c=black:t=fill", "-pix_fmt", "yuv420p", str(video)], check=True)
    t = pick_cover(video, tmp_path / "cover.jpg", tmp_path, total=3.0, until=2.8, avoid=[2.0])
    assert 1.3 < t < 2.8 and abs(t - 2.0) >= 0.3
    assert (tmp_path / "cover.jpg").stat().st_size > 1000


@needs_ffmpeg
def test_voice_cache_only_voices_what_changed(settings, tmp_path, monkeypatch):
    from purffle_shorts import tts
    calls = []

    def fake_edge(text, out, s):
        calls.append(text)
        path = out / "voice.wav"
        _tone(path, 0.2, seconds=1.5)
        return path, [tts.Word(w, 0.1 + 0.3 * i, 0.35 + 0.3 * i) for i, w in enumerate(text.split())], "fake-voice"
    monkeypatch.setitem(tts._ENGINE_FUNCS, "edge", fake_edge)
    s = settings.with_overrides(tts_engine="edge")
    lines = [("A", "First line here."), ("B", "Second line here.")]
    a = tts.synthesize_lines(lines, tmp_path / "one", s)
    assert len(calls) == 2
    edited = [("A", "First line here."), ("B", "A brand new second line.")]
    b = tts.synthesize_lines(edited, tmp_path / "two", s)
    assert calls[2:] == ["A brand new second line."]  # the unchanged line came from the cache
    assert [w.text for w in b.words][:3] == [w.text for w in a.words][:3]
    tts.synthesize_lines(lines, tmp_path / "three", s.with_overrides(voice_cache=False))
    assert len(calls) == 5
