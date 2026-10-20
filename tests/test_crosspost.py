"""Publishing beyond YouTube: Upload-Post (TikTok, Instagram, ...) and the official Instagram API, with the
HTTP APIs faked, and how the pipeline records, retries and cleans up per network."""

import json
from datetime import datetime, timezone

import pytest

from purffle_shorts import cli
from purffle_shorts import crosspost as X
from purffle_shorts import pipeline as P
from purffle_shorts.config import ConfigError, Settings

from .conftest import needs_ffmpeg
from .test_pipeline_online import clip, online  # noqa: F401  (fixtures)

META = {"title": "Why Octopuses Have Three Hearts #shorts", "created_at": "2026-10-20T10:00:00Z",
        "description": "Three hearts, one octopus. Which fact surprised you?\n\n#shorts #octopus #ocean\n\n"
                       "Footage: Pexels", "cover_at": 1.25}


class Resp:
    def __init__(self, data=None, status=200, text=""):
        self._data, self.status_code, self.text = data, status, text or json.dumps(data)

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data


class Fake:
    """Records every request; answers from a queue of (method, url-part) -> response."""

    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def _answer(self, method, url, **kw):
        self.calls.append((method, url, kw))
        for i, (m, part, resp) in enumerate(self.answers):
            if m == method and part in url:
                del self.answers[i]
                return resp
        raise AssertionError(f"unexpected {method} {url}")

    def post(self, url, **kw):
        if "data" in kw and hasattr(kw["data"], "read"):
            kw["body"] = kw["data"].read()
        for f in (kw.get("files") or {}).values():
            kw["file_bytes"] = f[1].read()
        return self._answer("POST", url, **kw)

    def get(self, url, **kw):
        return self._answer("GET", url, **kw)


@pytest.fixture
def video(tmp_path):
    folder = tmp_path / "20261020-100000_octopus"
    folder.mkdir()
    v = folder / "short.mp4"
    v.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 1000)
    return v


def relay_settings(**kw):
    return Settings(upload_post_api_key="up-key", upload_post_user="mychannel", **kw)


def test_caption_drops_shorts_and_fits_each_network():
    text = X.caption(META)
    assert text.startswith("Why Octopuses Have Three Hearts\n\nThree hearts") and "#shorts" not in text
    assert "#octopus #ocean" in text and "Footage: Pexels" in text
    short = X.caption(META, "x")
    assert len(short) <= 280
    long_meta = dict(META, description="word " * 200)
    cut = X.caption(long_meta, "x")
    assert len(cut) <= 280 and cut.endswith("…")


def test_routes_send_instagram_direct_only_with_its_own_token():
    s = relay_settings()
    assert X.routes(s, ["tiktok", "instagram"]) == (False, ["tiktok", "instagram"])
    d = relay_settings(instagram_user_id="1784", instagram_access_token="tok")
    assert X.routes(d, ["tiktok", "instagram"]) == (True, ["tiktok"])


def test_upload_post_sends_one_request_with_captions_per_network(video, monkeypatch):
    fake = Fake([("POST", "/api/upload", Resp({"success": True, "results": {
        "tiktok": {"success": True, "url": "https://www.tiktok.com/@me/video/1", "publish_id": "p1"},
        "instagram": {"success": False, "error": "Expired access token"}}}))])
    monkeypatch.setattr(X, "http", lambda: fake)
    when = datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc)
    out = X.upload_post(relay_settings(tiktok_privacy="SELF_ONLY"), video, META, ["tiktok", "instagram"], when)
    assert out["tiktok"].status == "posted" and out["tiktok"].url.endswith("/video/1") and out["tiktok"].id == "p1"
    assert out["instagram"].status == "failed" and "Expired" in out["instagram"].error
    _, url, kw = fake.calls[0]
    assert url == "https://api.upload-post.com/api/upload"
    data = dict(kw["data"])
    assert [v for k, v in kw["data"] if k == "platform[]"] == ["tiktok", "instagram"]
    assert data["user"] == "mychannel" and data["title"] == "Why Octopuses Have Three Hearts"
    assert "#shorts" not in data["tiktok_title"] and data["instagram_title"].startswith("Why Octopuses")
    assert data["privacy_level"] == "SELF_ONLY" and data["thumb_offset"] == "1250"
    assert data["scheduled_date"] == "2026-10-21T09:00:00Z" and data["async_upload"] == "true"
    assert kw["headers"]["Authorization"] == "Apikey up-key" and kw["headers"]["Idempotency-Key"].startswith("purffle-")
    assert kw["file_bytes"].startswith(b"\x00\x00\x00\x18ftyp")


def test_upload_post_async_is_followed_until_done(video, monkeypatch):
    fake = Fake([("POST", "/api/upload", Resp({"success": True, "request_id": "r-9", "total_platforms": 2})),
                 ("GET", "/uploadposts/status", Resp({"status": "in_progress", "results": []})),
                 ("GET", "/uploadposts/status", Resp({"status": "completed", "results": [
                     {"platform": "tiktok", "success": True, "fallback_to_inbox": True}]}))])
    monkeypatch.setattr(X, "http", lambda: fake)
    monkeypatch.setattr(X.time, "sleep", lambda s: None)
    out = X.upload_post(relay_settings(), video, META, ["tiktok", "instagram"], poll_every=0)
    assert out["tiktok"].status == "draft" and "inbox" in out["tiktok"].error   # unaudited TikTok: drafts
    assert out["instagram"].status == "submitted" and out["instagram"].id == "r-9"
    assert fake.calls[1][2]["params"] == {"request_id": "r-9"}


def test_upload_post_errors_explain_themselves(video, monkeypatch):
    for code, hint in ((401, "UPLOAD_POST_API_KEY"), (403, "paid plan"), (429, "monthly limit")):
        fake = Fake([("POST", "/api/upload", Resp({"message": "nope"}, status=code))])
        monkeypatch.setattr(X, "http", lambda f=fake: f)
        out = X.publish(relay_settings(), video, META, ["tiktok", "instagram"])
        assert {p.status for p in out.values()} == {"failed"} and hint in out["tiktok"].error


def test_networks_without_credentials_are_skipped(video):
    out = X.publish(Settings(), video, META, ["tiktok", "youtube", "bogus"])
    assert list(out) == ["tiktok"] and out["tiktok"].status == "skipped"
    assert "UPLOAD_POST_API_KEY" in out["tiktok"].error


def test_instagram_api_resumable_upload_then_publish(video, monkeypatch):
    fake = Fake([
        ("POST", "/1784/media_publish", Resp({"id": "m-1"})),
        ("POST", "/1784/media", Resp({"id": "c-1", "uri": "https://rupload.facebook.com/ig-api-upload/v25.0/c-1"})),
        ("POST", "rupload.facebook.com", Resp({"success": True, "message": "Upload successful."})),
        ("GET", "/c-1", Resp({"status_code": "IN_PROGRESS"})),
        ("GET", "/c-1", Resp({"status_code": "FINISHED"})),
        ("GET", "/m-1", Resp({"permalink": "https://www.instagram.com/reel/abc/"})),
    ])
    monkeypatch.setattr(X, "http", lambda: fake)
    monkeypatch.setattr(X.time, "sleep", lambda s: None)
    s = Settings(instagram_user_id="1784", instagram_access_token="tok")
    post = X.instagram_direct(s, video, "caption text", 1.25, poll_every=0)
    assert post.status == "posted" and post.url == "https://www.instagram.com/reel/abc/" and post.id == "m-1"
    create, upload = fake.calls[0], fake.calls[1]
    assert create[1] == "https://graph.facebook.com/v25.0/1784/media"
    assert create[2]["params"] == {"media_type": "REELS", "upload_type": "resumable", "caption": "caption text",
                                   "thumb_offset": "1250"}
    assert upload[2]["headers"]["offset"] == "0" and upload[2]["headers"]["file_size"] == str(video.stat().st_size)
    assert upload[2]["headers"]["Authorization"] == "OAuth tok" and upload[2]["body"] == video.read_bytes()
    assert fake.calls[4][1].endswith("/1784/media_publish") and fake.calls[4][2]["params"] == {"creation_id": "c-1"}


def test_instagram_processing_errors_fail_only_instagram(video, monkeypatch):
    fake = Fake([("POST", "/1784/media", Resp({"id": "c-2", "uri": "https://rupload.facebook.com/x/c-2"})),
                 ("POST", "rupload.facebook.com", Resp({"success": True})),
                 ("GET", "/c-2", Resp({"status_code": "ERROR", "status": "Video too long"}))])
    monkeypatch.setattr(X, "http", lambda: fake)
    s = Settings(instagram_user_id="1784", instagram_access_token="tok")
    out = X.publish(s, video, META, ["instagram"])
    assert out["instagram"].status == "failed" and "Video too long" in out["instagram"].error
    bad = Fake([("POST", "/1784/media", Resp({"error": {"message": "Invalid OAuth access token"}}, status=400))])
    monkeypatch.setattr(X, "http", lambda: bad)
    out = X.publish(s, video, META, ["instagram"])
    assert "INSTAGRAM_ACCESS_TOKEN" in out["instagram"].error


def test_publish_settings_are_checked(monkeypatch):
    monkeypatch.setenv("PUBLISH_TO", "youtube,tiktk")
    with pytest.raises(ConfigError, match="tiktk"):
        Settings.from_env()
    monkeypatch.setenv("PUBLISH_TO", "TikTok, Instagram")
    monkeypatch.setenv("TIKTOK_PRIVACY", "everyone")
    with pytest.raises(ConfigError, match="TIKTOK_PRIVACY"):
        Settings.from_env()
    monkeypatch.setenv("TIKTOK_PRIVACY", "public_to_everyone")
    s = Settings.from_env()
    assert s.publish_to == ["tiktok", "instagram"] and s.tiktok_privacy == "PUBLIC_TO_EVERYONE"
    a = cli.build_parser().parse_args(["make", "--publish-to", "youtube,instagram"])
    assert cli.build_settings(a).publish_to == ["youtube", "instagram"]
    with pytest.raises(ConfigError):
        cli.build_settings(cli.build_parser().parse_args(["make", "--publish-to", "myspace"]))


# ------------------------------------------------------------------------------------------ in the pipeline
@needs_ffmpeg
def test_youtube_and_tiktok_both_recorded_and_retried_separately(online, monkeypatch):  # noqa: F811
    s, _ = online
    yt_calls, relay_calls = [], []
    monkeypatch.setattr(P.youtube, "upload", lambda settings, video, body: yt_calls.append(body) or {"id": "yt1"})

    def relay(settings, video, meta, platforms, when=None):
        relay_calls.append((list(platforms), video.exists()))
        if len(relay_calls) == 1:
            return {p: X.Post(p, "failed", error="Upload-Post HTTP 500") for p in platforms}
        return {p: X.Post(p, "posted", url=f"https://{p}.example/v1") for p in platforms}
    monkeypatch.setattr(X, "upload_post", relay)
    s = s.with_overrides(publish_to=["youtube", "tiktok"], upload_post_api_key="k", upload_post_user="me")
    studio = P.Studio(s)
    r = studio.make()
    assert r.ok and r.status == "uploaded" and r.youtube_id == "yt1"
    assert r.posts["tiktok"]["status"] == "failed"
    meta = json.loads((r.folder / "metadata.json").read_text())
    assert meta["published"]["tiktok"]["status"] == "failed" and isinstance(meta["cover_at"], float)
    assert r.video.exists()                        # kept: TikTok still needs it
    # a retry only re-sends TikTok, never YouTube again
    r2 = P.Result(True)
    assert studio.upload_record(r.record_id, r2) == "uploaded"
    assert len(yt_calls) == 1 and [c[0] for c in relay_calls] == [["tiktok"], ["tiktok"]]
    assert r2.posts["tiktok"] == {"status": "posted", "url": "https://tiktok.example/v1"}
    assert not r.video.exists()                    # everywhere now: KEEP_VIDEOS=false removes it
    assert studio.upload_record(r.record_id) == "missing"


@needs_ffmpeg
def test_tiktok_only_channel_never_touches_youtube(online, monkeypatch):  # noqa: F811
    s, _ = online

    def no_youtube(*a, **k):
        raise AssertionError("YouTube must not be called")
    monkeypatch.setattr(P.youtube, "upload", no_youtube)
    seen = []
    monkeypatch.setattr(X, "upload_post", lambda settings, video, meta, platforms, when=None:
                        seen.append(when) or {p: X.Post(p, "scheduled", id="job1") for p in platforms})
    s = s.with_overrides(publish_to=["tiktok"], upload_post_api_key="k", upload_post_user="me",
                         publish_times=["09:00", "21:00"])
    studio = P.Studio(s)
    r = studio.make()
    assert r.ok and r.status == "scheduled" and r.youtube_id is None
    assert seen[0] is not None and seen[0] > datetime.now(timezone.utc)   # TikTok gets the same publish slot
    rec = studio.history.get(r.record_id)
    assert rec["status"] == "scheduled" and rec["publish_at"]


def test_doctor_and_studio_report_destinations(settings):
    from purffle_shorts import studio as ST
    from purffle_shorts.doctor import checks
    s = settings.with_overrides(upload=True, publish_to=["tiktok", "instagram"], instagram_user_id="1784",
                                instagram_access_token="tok")
    out = {c["label"]: c for c in checks(s)}
    assert "YouTube OAuth client" not in out
    assert out["Instagram"]["ok"] is True and out["TikTok"]["ok"] is False
    app = ST.StudioServer(s)
    try:
        assert app.info()["publish_to"] == ["tiktok", "instagram"]
        r = P.Result(True, "t", posts={"tiktok": {"status": "posted"}})
        assert ST._result(r)["posts"] == {"tiktok": {"status": "posted"}}
    finally:
        import logging
        root = logging.getLogger()
        for h in [h for h in root.handlers if isinstance(h, ST._JobLog)]:
            root.removeHandler(h)
