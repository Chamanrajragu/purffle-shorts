"""Face-aware framing for clips: the plan, the crop expression and a real render (detector faked)."""

import subprocess

from PIL import Image

from purffle_shorts import clipper as C
from purffle_shorts import ffmpeg

from .conftest import needs_ffmpeg


def test_one_steady_framing_per_camera_shot():
    # speaker on the left, a camera cut to the other speaker on the right at ~4 s, and one noisy sample
    samples = [(t / 2 + 0.25, 0.30) for t in range(8)] + [(4.25, None), (4.75, 0.72), (5.25, 0.31)]
    samples += [(t / 2 + 0.25, 0.70) for t in range(11, 16)]
    plan = C.plan_face_crop(samples, 8.0)
    assert len(plan) == 2
    assert plan[0] == (0.0, 0.3) and abs(plan[1][1] - 0.70) < 0.02 and 4.0 <= plan[1][0] <= 5.0


def test_no_faces_means_no_plan():
    assert C.plan_face_crop([(0.25, None), (0.75, None)], 2.0) == []


def test_face_crop_filter_switches_framing_at_the_cut(settings):
    s = settings.with_overrides(resolution=(1080, 1920))
    f = C.face_crop_filter(s, 1920, 1080, [(0.0, 0.25), (4.0, 0.8)])
    assert f.startswith("crop=606:1080:x='if(lt(t,4.00),") and "scale=1080:1920" in f
    assert C.face_crop_filter(s, 1080, 1920, [(0.0, 0.5)]) is None  # already vertical: nothing to choose
    assert C.face_crop_filter(s, 1920, 1080, []) is None


@needs_ffmpeg
def test_face_framing_renders_the_side_with_the_face(settings, tmp_path, monkeypatch):
    src = tmp_path / "wide.mp4"
    # left half blue, right half red; the "face" is on the right
    subprocess.run([ffmpeg.ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=640x360:r=25:d=3",
                    "-f", "lavfi", "-i", "color=c=red:s=320x360:r=25:d=3", "-f", "lavfi", "-i", "sine=f=200:d=3",
                    "-filter_complex", "[0:v][1:v]overlay=x=320[v]", "-map", "[v]", "-map", "2:a",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)],
                   check=True)
    monkeypatch.setattr(C, "face_samples", lambda *a, **k: [(0.25, 0.85), (0.75, 0.86), (1.25, 0.85)])
    s = settings.with_overrides(resolution=(180, 320), fps=25, hook_overlay=False, end_cta="", watermark="none",
                                progress_bar=False)
    video, _, _ = C.render_clip(s, src, C.ClipPlan(0.0, 2.0, "t"), [], tmp_path / "clip", crop="face")
    frame = tmp_path / "f.png"
    subprocess.run([ffmpeg.ffmpeg_bin(), "-v", "error", "-y", "-ss", "1", "-i", str(video), "-frames:v", "1",
                    str(frame)], check=True)
    r, g, b = Image.open(frame).convert("RGB").resize((1, 1)).getpixel((0, 0))
    assert r > 150 and b < 80  # the red (face) side, not the blue centre-left
