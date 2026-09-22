from purffle_shorts.config import Settings, parse_resolution
from purffle_shorts.history import History
from purffle_shorts.utils import redact


def test_legacy_env_names_still_work(monkeypatch):
    monkeypatch.setenv("SHORTS_RESOLUTION", "721x1281")
    monkeypatch.setenv("SHORTS_FPS", "60")
    monkeypatch.setenv("SHORTS_BATCH_SIZE", "5")
    monkeypatch.setenv("NICHES", "space, cats ,")
    monkeypatch.setenv("END_CTA", "")
    s = Settings.from_env()
    assert s.resolution == (720, 1280) and s.fps == 60 and s.batch_size == 5
    assert s.niches == ["space", "cats"]
    assert s.end_cta == ""


def test_parse_resolution_fallback():
    assert parse_resolution("garbage") == (1080, 1920)


def test_watermark_defaults_to_channel():
    assert Settings(channel_name="Chan").watermark_text == "Chan"
    assert Settings(watermark="none").watermark_text == ""


def test_history_roundtrip(tmp_path):
    h = History(tmp_path / "h.db")
    vid = h.add_video(title="T", status="rendered", video_path="/x.mp4", tags=["a"])
    h.update_video(vid, status="queued")
    assert [r["id"] for r in h.pending_uploads()] == [vid]
    assert h.pending_uploads(("rendered",)) == []
    h.update_video(vid, status="uploaded", uploaded_at="2099-01-01T00:00:00+00:00")
    assert h.uploads_since("2098-12-31T00:00:00+00:00") == 1
    h.mark_media(["pexels:1", "pexels:1"])
    assert h.used_media() == {"pexels:1"}
    h.mark_topic("Trend:X")
    assert h.topic_used("trend:x")
    assert h.recent_titles() == ["T"]


def test_redact_hides_keys_in_urls():
    msg = "Max retries exceeded with url: /api/videos/?key=abc123SECRET&q=octopus (api_key=zzz)"
    out = redact(msg)
    assert "abc123SECRET" not in out and "zzz" not in out and "q=octopus" in out


def test_redact_hides_ip_addresses_but_not_times_or_versions():
    msg = ('HTTP 429 — {"message":"Queue full for IP: 2409:4091:a01f:c202:f83f:1657:e36b:9830"} '
           "from 203.0.113.7 at 17:49:06 with ffmpeg 9.0.2")
    out = redact(msg)
    assert "2409:4091" not in out and "203.0.113.7" not in out and out.count("<ip>") == 2
    assert "17:49:06" in out and "9.0.2" in out
