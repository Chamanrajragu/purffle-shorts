from datetime import datetime, timezone

from purffle_shorts import youtube as Y
from purffle_shorts.config import Settings


def test_next_publish_slot_skips_past_and_taken():
    s = Settings(publish_times=["09:00", "18:00"], timezone="Asia/Kolkata")
    now = datetime(2026, 9, 22, 5, 0, tzinfo=timezone.utc)   # 10:30 IST
    slot = Y.next_publish_slot(s, [], now)
    assert slot.strftime("%H:%M") == "18:00" and slot.day == 22
    taken = [Y.to_rfc3339(slot)]
    nxt = Y.next_publish_slot(s, taken, now)
    assert nxt.strftime("%H:%M") == "09:00" and nxt.day == 23


def test_no_publish_times_means_immediate():
    assert Y.next_publish_slot(Settings(), [], None) is None


def test_build_body_scheduled_and_disclosure():
    s = Settings(privacy="public", synthetic_media=True)
    when = datetime(2026, 9, 23, 3, 30, tzinfo=timezone.utc)
    body = Y.build_body(s, "T" * 150, "d", ["a"], "27", "en", when)
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["publishAt"] == "2026-09-23T03:30:00Z"
    assert body["status"]["containsSyntheticMedia"] is True
    assert len(body["snippet"]["title"]) == 100


def test_build_body_public_now():
    body = Y.build_body(Settings(privacy="unlisted", synthetic_media=False), "t", "d", [], "24", "es")
    assert body["status"]["privacyStatus"] == "unlisted" and "publishAt" not in body["status"]
    assert "containsSyntheticMedia" not in body["status"]
    assert body["snippet"]["defaultAudioLanguage"] == "es"
