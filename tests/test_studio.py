"""The Studio web app's server: security checks, the JSON API and a real (offline) job."""

import http.client
import json
import logging
import threading
import time
from http.server import ThreadingHTTPServer

import pytest

from purffle_shorts import studio as ST


@pytest.fixture
def server(settings):
    app = ST.StudioServer(settings.with_overrides(upload=False))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ST._handler(app, "127.0.0.1"))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield app, httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()
    root = logging.getLogger()
    for h in [h for h in root.handlers if isinstance(h, ST._JobLog)]:
        root.removeHandler(h)


def req(port, method, path, body=None, token=None, host=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Studio-Token"] = token
    if host:
        headers["Host"] = host
    c.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, dict(r.getheaders()), data


def test_page_has_token_and_strict_csp(server):
    app, port = server
    status, headers, body = req(port, "GET", "/")
    assert status == 200 and app.token.encode() in body and b"__TOKEN__" not in body
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert "unsafe-inline" not in headers["Content-Security-Policy"]
    assert req(port, "GET", "/static/app.js")[0] == 200
    assert req(port, "GET", "/static/../studio.py")[0] == 404


def test_other_host_names_are_refused(server):
    app, port = server
    assert req(port, "GET", "/api/info", host="evil.example:8765")[0] == 421
    assert req(port, "GET", "/api/info", host=f"localhost:{port}")[0] == 200


def test_writes_need_the_token(server):
    app, port = server
    assert req(port, "POST", "/api/ideas", {"subject": "x"})[0] == 403
    status, _, body = req(port, "POST", "/api/ideas", {"subject": "Why cats purr", "style": "facts"}, app.token)
    assert status == 200
    iid = json.loads(body)["id"]
    ideas = json.loads(req(port, "GET", "/api/ideas")[2])["pending"]
    assert [(i["id"], i["style"]) for i in ideas] == [(iid, "facts")]
    req(port, "POST", f"/api/ideas/{iid}/delete", {}, app.token)
    assert json.loads(req(port, "GET", "/api/ideas")[2])["pending"] == []


def test_options_and_doctor(server):
    app, port = server
    opts = json.loads(req(port, "GET", "/api/options")[2])
    assert {"chat", "dialogue"} <= set(opts["styles"]) and "16:9" in opts["aspects"]
    checks = json.loads(req(port, "GET", "/api/doctor")[2])
    assert any(c["label"] == "Python" for c in checks)


def test_form_values_are_validated(server):
    app, _ = server
    s = app.overrides({"caption_style": "<script>", "aspect": "16:9", "duration": "999", "review": "rewrite",
                       "grade": "cinematic", "visuals": ["pollinations"], "music": False, "tts": "rm -rf"})
    assert s.caption_style == app.settings.caption_style and s.resolution == (1920, 1080)
    assert s.target_seconds == 170 and s.color_grade == "cinematic" and s.visual_sources == ["pollinations"]
    assert s.music_volume == 0.0 and s.tts_engine == app.settings.tts_engine


def test_offline_draft_job_runs_to_completion(server):
    app, port = server
    status, _, body = req(port, "POST", "/api/draft", {"offline": True, "style": "chat"}, app.token)
    jid = json.loads(body)["job"]
    for _ in range(100):
        job = json.loads(req(port, "GET", f"/api/jobs/{jid}")[2])
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "done", job
    assert job["result"]["script"]["style"] == "chat" and job["pct"] == 100
    assert job["label"] == "Demo video"


def _job(port, jid, until=("done", "failed", "cancelled"), tries=600):
    for _ in range(tries):
        job = json.loads(req(port, "GET", f"/api/jobs/{jid}")[2])
        if job["status"] in until:
            return job
        time.sleep(0.05)
    return job


def test_event_stream_pushes_job_changes(server):
    app, port = server
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", "/api/events")
    r = c.getresponse()
    assert r.status == 200 and r.getheader("Content-Type").startswith("text/event-stream")
    jid = json.loads(req(port, "POST", "/api/draft", {"offline": True}, app.token)[2])["job"]
    seen = set()
    deadline = time.time() + 15
    while time.time() < deadline and "done" not in seen:
        line = r.fp.readline().decode()
        if line.startswith("data: "):
            jobs = json.loads(line[6:])
            seen |= {j["status"] for j in jobs if j["id"] == jid}
    c.close()
    assert "done" in seen  # the finished job arrived on the stream, without polling


def test_a_running_job_can_be_cancelled(server, monkeypatch):
    from purffle_shorts import pipeline as P
    from purffle_shorts.utils import CANCEL
    app, port = server
    started = threading.Event()
    real_step = P.Studio._step

    def slow_step(self, stage, message=""):
        if stage == "voice":
            started.set()
            for _ in range(200):  # stand-in for a long stage that checks for cancellation
                if CANCEL.is_set():
                    break
                time.sleep(0.02)
        return real_step(self, stage, message)
    monkeypatch.setattr(P.Studio, "_step", slow_step)
    jid = json.loads(req(port, "POST", "/api/make", {"offline": True}, app.token)[2])["job"]
    assert started.wait(10)
    assert json.loads(req(port, "POST", f"/api/jobs/{jid}/cancel", {}, app.token)[2])["ok"]
    job = _job(port, jid)
    assert job["status"] == "cancelled", job
    assert app.studio.history.recent(5) == []  # nothing half-made was left in the library
    assert not CANCEL.is_set()                 # the next job starts clean


def test_password_protects_everything(settings):
    app = ST.StudioServer(settings.with_overrides(upload=False))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ST._handler(app, "127.0.0.1", password="s3cret"))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    try:
        status, headers, _ = req(port, "GET", "/api/info")
        assert status == 401 and "Basic" in headers["WWW-Authenticate"]
        import base64
        good = "Basic " + base64.b64encode(b"me:s3cret").decode()
        bad = "Basic " + base64.b64encode(b"me:nope").decode()
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("GET", "/api/info", headers={"Authorization": bad})
        assert c.getresponse().status == 401
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("GET", "/api/info", headers={"Authorization": good})
        assert c.getresponse().status == 200
    finally:
        httpd.shutdown()
        httpd.server_close()
        root = logging.getLogger()
        for h in [h for h in root.handlers if isinstance(h, ST._JobLog)]:
            root.removeHandler(h)


def test_running_jobs_report_an_eta(server):
    app, port = server
    app.studio.clock.avg.update({"voice": 2.0, "render": 4.0})  # as if the machine had made videos before
    st = app.studio
    st._begin(["voice", "footage", "captions", "render", "check", "done"])
    st._step("voice")
    eta = st.eta()
    assert eta is not None and eta > 4.0
    st._t_start -= 10  # ten seconds into the job
    st._step("render")
    st._sub(0.5)
    assert st.eta() == 3.0  # the second half of render (2 s) + the default 1 s for the check
    assert 0 < st._pct < 100


def test_bundled_fonts_and_brand_assets_are_served(server):
    app, port = server
    status, headers, body = req(port, "GET", "/static/fonts/SchibstedGrotesk.woff2")
    assert status == 200 and headers["Content-Type"] == "font/woff2" and body[:4] == b"wOF2"
    assert "max-age" in headers["Cache-Control"]
    assert req(port, "GET", "/static/fonts/JetBrainsMono.woff2")[0] == 200
    assert req(port, "GET", "/static/fonts/missing.woff2")[0] == 404
    assert req(port, "GET", "/static/fonts/../app.js")[0] == 404
    status, headers, body = req(port, "GET", "/static/icon.svg")
    assert status == 200 and b"<svg" in body


def test_page_has_no_inline_styles_or_scripts(server):
    """The Content-Security-Policy forbids inline styles and scripts, so the markup must not use them."""
    import re
    app, port = server
    html = req(port, "GET", "/")[2].decode()
    js = req(port, "GET", "/static/app.js")[2].decode()
    assert not re.search(r"\sstyle=", html) and not re.search(r"<script>(?!\s*</script>)", html)
    assert not re.search(r"""\sstyle=["']""", js)
