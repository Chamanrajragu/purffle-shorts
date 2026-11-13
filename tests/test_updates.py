"""The once-a-day update check and the optional "Made with PurffleShorts" credit line."""

import json
from dataclasses import replace

from purffle_shorts import updates as U
from purffle_shorts.config import Settings
from purffle_shorts.pipeline import CREDIT_LINE, final_description
from purffle_shorts.script import Scene, Script
from tests.test_studio import req, server  # noqa: F401  (pytest fixture)


class Meta:
    def __init__(self):
        self.d = {}

    def get_meta(self, k):
        return self.d.get(k)

    def set_meta(self, k, v):
        self.d[k] = v


def test_versions_compare_numerically():
    assert U.parse("v3.10.0") == (3, 10, 0) and U.parse("junk") == (0,) and U.parse("3.1.0rc1") == (3, 1, 0)
    assert U.newer("3.10.0", "3.9.9") and U.newer("v4", "3.9") and U.newer("3.0.1", "3.0")
    assert not U.newer("3.0.0", "3.0") and not U.newer("2.9", "3.0.0") and not U.newer("", "3.0.0")


def test_check_runs_once_a_day_and_survives_failures():
    h, calls = Meta(), []

    def ok():
        calls.append(1)
        return {"version": "99.0.0", "url": "https://github.com/x/y/releases/tag/v99.0.0"}

    def boom():
        raise OSError("offline")

    U.check(h, now=1000, fetcher=boom)                     # offline: remembered as tried, nothing shown
    assert U.available(h) is None
    U.check(h, now=2000, fetcher=ok)                       # tried less than a day ago: no request
    assert calls == []
    U.check(h, now=1000 + U.EVERY, fetcher=ok)
    assert calls == [1] and U.available(h) == {"version": "99.0.0",
                                                "url": "https://github.com/x/y/releases/tag/v99.0.0"}
    h.d[U.META_KEY] = json.dumps({"at": 0, "latest": "0.1.0"})
    assert U.available(h) is None                          # older than this version: nothing to show
    h.d[U.META_KEY] = "not json"
    assert U.load(h) == {}


def test_fetch_ignores_drafts_and_foreign_links(monkeypatch):
    import requests

    class R:
        status_code = 200

        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

    monkeypatch.setattr(requests, "get", lambda *a, **k: R({"tag_name": "v9.9.9", "html_url": "https://evil.example"}))
    assert U.fetch() == {"version": "9.9.9", "url": U.RELEASES}
    monkeypatch.setattr(requests, "get", lambda *a, **k: R({"tag_name": "v9.9.9", "prerelease": True}))
    assert U.fetch() is None


def test_info_shows_a_newer_release(server):  # noqa: F811
    app, port = server
    assert json.loads(req(port, "GET", "/api/info")[2])["update"] is None
    app.settings = replace(app.settings, check_updates=True)
    app.studio.history.set_meta(U.META_KEY, json.dumps({"at": 1, "latest": "99.0.0", "url": U.RELEASES}))
    assert json.loads(req(port, "GET", "/api/info")[2])["update"] == {"version": "99.0.0", "url": U.RELEASES}
    app.settings = replace(app.settings, check_updates=False)     # CHECK_UPDATES=false hides it
    assert json.loads(req(port, "GET", "/api/info")[2])["update"] is None


def test_credit_line_is_opt_in():
    script = Script(topic="t", title="T", hook_text="h", scenes=[Scene("x", "y")], description="Body.", hashtags=["#a"])
    s = Settings()
    assert CREDIT_LINE not in final_description(script, set(), s)
    assert final_description(script, set(), replace(s, credit_line=True)).endswith("\n\n" + CREDIT_LINE)


def test_icon_and_numbers_are_served(server):  # noqa: F811
    app, port = server
    status, headers, body = req(port, "GET", "/static/icon.png")[:3]
    assert status == 200 and body[:4] == b"\x89PNG"
    info = json.loads(req(port, "GET", "/api/info")[2])
    assert info["seconds"] == 0 and info["formats"] == 0 and info["credit_line"] is False
