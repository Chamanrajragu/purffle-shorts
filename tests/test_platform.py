"""Settings, database migration, channel stats, notifications and the MCP server."""

import io
import json
import sqlite3

import pytest

from purffle_shorts import analytics, notify
from purffle_shorts.cli import main
from purffle_shorts.config import ConfigError, Settings
from purffle_shorts.history import History
from purffle_shorts.mcp_server import TOOLS, Server
from purffle_shorts.utils import redact


# ------------------------------------------------------------------ settings
def test_aspect_presets(monkeypatch):
    monkeypatch.setenv("ASPECT", "16:9")
    s = Settings.from_env()
    assert s.resolution == (1920, 1080) and s.orientation == "landscape" and not s.vertical
    assert s.unit == 810  # captions sized to the height of a wide frame
    monkeypatch.setenv("RESOLUTION", "720x1280")  # an explicit resolution wins
    assert Settings.from_env().resolution == (720, 1280)
    monkeypatch.setenv("ASPECT", "5:7")
    with pytest.raises(ConfigError, match="ASPECT"):
        Settings.from_env()


def test_bad_numbers_give_a_clear_message(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TARGET_SECONDS", "forty")
    with pytest.raises(ConfigError, match="TARGET_SECONDS='forty'"):
        Settings.from_env()
    assert main(["history"]) == 2
    assert "TARGET_SECONDS" in capsys.readouterr().err


def test_new_settings_from_env(monkeypatch):
    for k, v in {"SCRIPT_REVIEW": "false", "ALSO_LANGUAGES": "ES, hi", "RSS_FEEDS": "https://a/rss;https://b/rss",
                 "TTS_VOICE_B": "en-GB-SoniaNeural", "LEARN_FROM_STATS": "yes"}.items():
        monkeypatch.setenv(k, v)
    s = Settings.from_env()
    assert s.script_review == "off" and s.also_languages == ["es", "hi"]
    assert s.rss_feeds == ["https://a/rss", "https://b/rss"] and s.tts_voice_b == "en-GB-SoniaNeural"
    assert s.learn_from_stats


# ------------------------------------------------------------------ history
def test_a_2x_database_is_migrated(tmp_path):
    db = tmp_path / "history.db"
    con = sqlite3.connect(db)
    con.executescript("CREATE TABLE videos (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, "
                      "title TEXT, status TEXT NOT NULL, youtube_id TEXT, publish_at TEXT, uploaded_at TEXT);"
                      "INSERT INTO videos (created_at, title, status) VALUES ('2026-09-01', 'Old one', 'uploaded');")
    con.close()
    h = History(db)
    assert h.recent(1)[0]["title"] == "Old one" and h.recent(1)[0]["score"] is None
    vid = h.add_video(title="New", status="rendered", score=80, parent_id=1)
    assert h.get(vid)["score"] == 80 and h.ideas() == []


def test_performers_need_age_and_views(tmp_path):
    h = History(tmp_path / "h.db")
    for i, views in enumerate([500, 90, 12000, 3]):
        vid = h.add_video(title=f"V{i}", status="uploaded", youtube_id=f"y{i}", style="facts",
                          uploaded_at="2026-01-01T00:00:00+00:00")
        h.set_stats(f"y{i}", views, views // 10, 1)
    h.add_video(title="Too new", status="uploaded", youtube_id="new", uploaded_at="2999-01-01T00:00:00+00:00")
    h.set_stats("new", 10**9, 0, 0)
    assert [v["title"] for v in h.performers(2)] == ["V2", "V0"]
    assert [v["title"] for v in h.performers(1, best=False)] == ["V3"]
    assert vid


# ------------------------------------------------------------------ analytics
class R:
    def __init__(self, data, status=200):
        self._d, self.status_code, self.text = data, status, json.dumps(data)

    def json(self):
        return self._d


def test_sync_stats_with_api_key(monkeypatch, tmp_path):
    h = History(tmp_path / "h.db")
    for i in range(3):
        h.add_video(title=f"V{i}", status="uploaded", youtube_id=f"y{i}", uploaded_at="2026-01-01T00:00:00+00:00")
    calls = []

    class S:
        def get(self, url, params=None, timeout=None):
            calls.append(params)
            return R({"items": [{"id": i, "statistics": {"viewCount": str(100 * n), "likeCount": "5"}}
                                for n, i in enumerate(params["id"].split(","), 1)]})
    monkeypatch.setattr(analytics, "http", lambda: S())
    assert analytics.sync_stats(Settings(youtube_api_key="k"), h) == 3
    assert calls[0]["part"] == "statistics" and calls[0]["key"] == "k"
    text = analytics.insights(h)
    assert "performed best" in text and "300 views" in text


def test_insights_stay_empty_without_enough_data(tmp_path):
    assert analytics.insights(History(tmp_path / "h.db")) == ""


# ------------------------------------------------------------------ notifications
@pytest.mark.parametrize("url,key", [
    ("https://discord.com/api/webhooks/123/abc", "content"),
    ("https://hooks.slack.com/services/T/B/x", "text"),
    ("https://example.com/hook", "event"),
])
def test_notification_payloads(url, key):
    p = notify.payload(url, "uploaded", {"title": "Cats", "url": "https://youtube.com/shorts/x"})
    assert key in p and "Cats" in json.dumps(p)


def test_notify_posts_in_background(monkeypatch):
    sent = []

    class S:
        def post(self, url, json=None, timeout=None):
            sent.append((url, json))
            return R({})
    monkeypatch.setattr(notify, "http", lambda: S())
    assert notify.send(Settings(), "failed", title="x") is None  # no webhook: nothing happens
    notify.send(Settings(notify_webhook="https://discord.com/api/webhooks/1/t"), "failed", title="Oops").join(5)
    assert sent and "Oops" in sent[0][1]["content"]


def test_webhook_tokens_are_redacted():
    out = redact("POST https://discord.com/api/webhooks/1234/SeCrEt-Token_x failed; hooks.slack.com/services/T0/B0/zz")
    assert "SeCrEt" not in out and "T0/B0" not in out and "/api/webhooks/1234/***" in out


# ------------------------------------------------------------------ MCP
def _call(server, method, params=None, mid=1):
    return server.handle({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})


def test_mcp_handshake_and_tools(settings):
    srv = Server(settings)
    init = _call(srv, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}})
    assert init["result"]["protocolVersion"] == "2025-03-26"
    assert init["result"]["serverInfo"]["name"] == "purffle-shorts"
    assert _call(srv, "initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"] == "2025-06-18"
    assert srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    names = {t["name"] for t in _call(srv, "tools/list")["result"]["tools"]}
    assert {"make_short", "draft_script", "clip_video", "plan_ideas", "list_videos", "upload_video"} <= names
    assert all(t["inputSchema"]["type"] == "object" for t in TOOLS)


def test_mcp_tool_results_and_errors(settings):
    srv = Server(settings)
    r = _call(srv, "tools/call", {"name": "list_videos", "arguments": {}})["result"]
    assert r["isError"] is False and r["content"][0]["text"] == "No videos yet."
    bad = _call(srv, "tools/call", {"name": "upload_video", "arguments": {"id": 99}})["result"]
    assert bad["content"][0]["text"] == "Video #99: missing"
    assert _call(srv, "tools/call", {"name": "rm_rf"})["error"]["code"] == -32602
    assert _call(srv, "nope")["error"]["code"] == -32601


def test_mcp_stdio_loop(settings):
    stdin = io.StringIO('{"jsonrpc":"2.0","id":7,"method":"ping"}\nnot json\n\n'
                        '{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
    out = io.StringIO()
    Server(settings).serve(stdin, out)
    lines = [json.loads(x) for x in out.getvalue().splitlines()]
    assert lines[0] == {"jsonrpc": "2.0", "id": 7, "result": {}}
    assert lines[1]["error"]["code"] == -32700 and len(lines) == 2


def test_upload_limit_refusal_is_queued_not_failed(settings, tmp_path, monkeypatch):
    # YouTube answers videos.insert with 400 uploadLimitExceeded when a channel hits its own upload cap.
    import httplib2
    from googleapiclient.errors import HttpError

    from purffle_shorts import youtube
    content = b'{"error": {"code": 400, "message": "The user has exceeded the number of videos they may upload.", '\
              b'"errors": [{"reason": "uploadLimitExceeded", "domain": "youtube.video"}]}}'

    class Request:
        def next_chunk(self):
            raise HttpError(httplib2.Response({"status": 400}), content)

    class Videos:
        def insert(self, **kw):
            return Request()

    class Service:
        def videos(self):
            return Videos()
    monkeypatch.setattr(youtube, "service", lambda *a, **k: Service())
    video = tmp_path / "short.mp4"
    video.write_bytes(b"\0" * 1024)
    with pytest.raises(youtube.QuotaExceeded):
        youtube.upload(settings, video, {})
