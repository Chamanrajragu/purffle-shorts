"""Clip editing: jump cuts (pauses and fillers), frame-exact sync, punch-in zoom, the brief and the score."""

import subprocess

from PIL import Image

from purffle_shorts import clipper as C
from purffle_shorts import ffmpeg
from purffle_shorts.timing import Word

from .conftest import needs_ffmpeg

F = 30


def test_long_pauses_shrink_and_fillers_go():
    words = [Word("Hello", 1.0, 1.4), Word("there.", 1.5, 2.0),            # 1.0 s of silence before
             Word("Um,", 3.0, 3.3),                                        # a filler in a long pause
             Word("So", 4.0, 4.2), Word("anyway.", 4.25, 4.8)]
    keep = C.keep_ranges(words, 6.0, F, max_pause=0.6, pad=0.15)
    for a, b in keep:
        assert abs(a * F - round(a * F)) < 1e-4 and abs(b * F - round(b * F)) < 1e-4   # frame boundaries
    kept = sum(b - a for a, b in keep)
    assert 3.5 - 0.1 < 6.0 - kept                                          # ~3.6 s of silence removed
    assert keep[0][0] > 0.7                                                # leading silence is cut
    assert not any(a <= 3.15 < b for a, b in keep)                         # the "um" is gone
    assert any(a <= 1.2 < b for a, b in keep) and any(a <= 4.5 < b for a, b in keep)


def test_short_pauses_and_no_words_are_left_alone():
    words = [Word("one", 0.0, 0.4), Word("two", 0.6, 1.0), Word("three", 1.2, 1.6)]
    assert C.keep_ranges(words, 1.85, F) == [(0.0, 1.85)]          # nothing to cut: the clip as it is
    assert C.keep_ranges([], 5.0, F) == [(0.0, 5.0)]
    trailing = C.keep_ranges(words, 4.0, F)                           # 2.4 s of silence at the end
    assert trailing[-1][1] <= 4.0 and trailing[-1][1] < 2.0


def test_retime_moves_words_with_the_cuts_and_drops_fillers():
    words = [Word("a", 0.0, 0.5), Word("Um", 2.0, 2.3), Word("b", 3.0, 3.5)]
    keep = [(0.0, 0.7), (2.8, 3.7)]
    out = C.retime(words, keep)
    assert [w.text for w in out] == ["a", "b"]
    assert out[1].start == round(3.0 - 2.1, 3) and out[1].end == round(3.5 - 2.1, 3)


def test_select_expression_has_half_a_frame_of_tolerance():
    expr = C.select_expr([(0.0, 1.0), (2.0, 3.0)], 25)
    assert expr == "gte(t,-0.0200)*lt(t,0.9800)+gte(t,1.9800)*lt(t,2.9800)"


def test_zoom_alternates_at_sentence_starts_and_not_too_often():
    words = [Word("One.", 0.0, 0.5), Word("Two.", 0.8, 1.2), Word("Three.", 2.5, 3.0), Word("Four", 5.0, 5.4),
             Word("five.", 5.5, 6.0), Word("Six.", 7.6, 8.0)]
    plan = C.zoom_plan(words, 10.0, zoom=1.1, min_seconds=2.0)
    assert plan[0] == (0.0, 1.0)
    assert [z for _, z in plan] == [1.0, 1.1, 1.0, 1.1]
    times = [t for t, _ in plan]
    assert all(b - a >= 2.0 for a, b in zip(times, times[1:]))
    f = C.zoom_filter(C.Settings(resolution=(1080, 1920), fps=30), plan)
    assert f.startswith(",zoompan=z='if(lt(it,") and "s=1080x1920" in f
    assert C.zoom_filter(C.Settings(), [(0.0, 1.0)]) == ""


def test_clip_prompt_carries_the_brief(settings):
    sents = [C.Sentence(0.0, 3.0, "Hello there.")]
    _, user = C.clip_prompt(sents, 2, 20, 58, settings, brief="only the jokes")
    assert "only the jokes" in user and "Only pick moments that fit" in user
    _, plain = C.clip_prompt(sents, 2, 20, 58, settings)
    assert "brief" not in plain


@needs_ffmpeg
def test_jump_cuts_keep_picture_and_sound_in_sync(settings, tmp_path):
    """Each 'word' is a white flash with a beep at the same instant, between long silences. After the cuts
    every flash must still coincide with its beep."""
    src = tmp_path / "talk.mp4"
    flashes = [0.5, 2.5, 4.9, 7.3]       # pauses of ~2 s get cut
    lum = "+".join(f"between(T,{t:.2f},{t + 0.3:.2f})" for t in flashes)   # geq calls time T
    beep = "+".join(f"between(t,{t:.2f},{t + 0.3:.2f})" for t in flashes)
    subprocess.run([ffmpeg.ffmpeg_bin(), "-v", "error", "-y",
                    "-f", "lavfi", "-i", "color=c=black:s=320x568:r=30:d=9",
                    "-f", "lavfi", "-i", f"aevalsrc='0.6*sin(2*PI*1000*t)*({beep})':s=48000:d=9",
                    "-vf", f"geq=lum='if({lum},235,16)':cb=128:cr=128", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src)], check=True)
    words = [Word(f"w{i}.", t, t + 0.3) for i, t in enumerate(flashes)]
    s = settings.with_overrides(resolution=(320, 568), fps=30, hook_overlay=False, end_cta="", watermark="none",
                                progress_bar=False, caption_style="minimal", clip_zoom=False, voice_enhance=False)
    plan = C.ClipPlan(0.0, 8.8, "sync")
    video, chunks, dur = C.render_clip(s, src, plan, words, tmp_path / "clip", crop="center", src_size=(320, 568))
    assert dur < 5.0                                         # ~6 s of silence was removed
    # luma of each frame and audio level of each 1/30 s, from the finished file
    raw = subprocess.run([ffmpeg.ffmpeg_bin(), "-v", "error", "-i", str(video), "-vf", "scale=8:8,format=gray",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    frames = [sum(raw[i:i + 64]) / 64 for i in range(0, len(raw), 64)]
    pcm = subprocess.run([ffmpeg.ffmpeg_bin(), "-v", "error", "-i", str(video), "-ac", "1", "-ar", "48000",
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    import array
    a = array.array("h", pcm)
    per = 48000 // 30
    levels = [max((abs(x) for x in a[k * per:(k + 1) * per]), default=0) for k in range(len(a) // per)]

    def onsets(xs, thr):
        return [i for i in range(1, len(xs)) if xs[i] > thr >= xs[i - 1]]
    v_on, a_on = onsets(frames, 120), onsets(levels, 4000)
    assert len(v_on) == len(flashes) == len(a_on)
    assert all(abs(v - a) <= 1 for v, a in zip(v_on, a_on)), (v_on, a_on)   # within one frame
    assert abs(ffmpeg.duration(video) - dur) < 0.1


@needs_ffmpeg
def test_zoom_changes_the_framing(settings, tmp_path):
    src = tmp_path / "grid.mp4"
    subprocess.run([ffmpeg.ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x568:r=30:d=6",
                    "-f", "lavfi", "-i", "sine=f=200:d=6", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    str(src)], check=True)
    s = settings.with_overrides(resolution=(320, 568), fps=30, hook_overlay=False, end_cta="", watermark="none",
                                progress_bar=False, caption_style="minimal", clip_jump_cuts=False)
    words = [Word("First.", 0.2, 0.8), Word("Second", 3.0, 3.4), Word("part.", 3.5, 4.0)]
    video, _, _ = C.render_clip(s, src, C.ClipPlan(0.0, 5.5, "zoom"), words, tmp_path / "clip", "center",
                                (320, 568))
    out = []
    for t in (2.85, 3.05):          # the zoom starts at 2.95 s, between two near-identical source frames
        f = tmp_path / f"z{t}.png"
        subprocess.run([ffmpeg.ffmpeg_bin(), "-v", "error", "-y", "-ss", str(t), "-i", str(video),
                        "-frames:v", "1", str(f)], check=True)
        out.append(Image.open(f).convert("L").resize((32, 56)))
    diff = sum(abs(a - b) for a, b in zip(out[0].tobytes(), out[1].tobytes()))
    assert diff / (32 * 56) > 8      # the picture jumped (punch-in), not just one frame of motion


def test_offline_clip_titles_drop_leading_fillers():
    assert C._title_from("Uh, and most of their brain is in their arms.") == "And most of their brain is in their arms"
    assert C._title_from("um um so here it is") == "So here it is"
    assert C._title_from("Um.") == ""
