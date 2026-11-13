"""The Studio's Settings page (.env editing) and Local AI page (Ollama downloads on their own worker)."""

import json
import threading

import pytest

from purffle_shorts import envfile, localai
from tests.test_studio import _job, req, server  # noqa: F401  (pytest fixture)


# ---------------------------------------------------------------- .env editing
def test_write_keeps_comments_and_unknown_lines(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# my keys\nPEXELS_API_KEY=abc\nSOMETHING_ELSE=1\nTTS_RATE=+8%\n")
    envfile.write({"PEXELS_API_KEY": "new key", "TTS_RATE": None, "CHANNEL_NAME": "Cats & Co"}, p)
    text = p.read_text()
    assert text.startswith("# my keys\n")
    assert "SOMETHING_ELSE=1" in text and "TTS_RATE" not in text
    assert envfile.read(p) == {"PEXELS_API_KEY": "new key", "SOMETHING_ELSE": "1", "CHANNEL_NAME": "Cats & Co"}


def test_clean_validates_and_ignores_unknown_keys():
    assert envfile.clean({"NOT_A_SETTING": "x", "OPENAI_API_KEY": None}) == {}
    assert envfile.clean({"TTS_RATE": "+5%\nEVIL=1", "TTS_VOICE": ""}) == {"TTS_RATE": "+5% EVIL=1", "TTS_VOICE": None}
    assert envfile.clean({"LOCAL_THINKING": True}) == {"LOCAL_THINKING": "true"}
    with pytest.raises(ValueError):
        envfile.clean({"LLM_PROVIDER": "skynet"})


def test_current_never_returns_a_whole_key(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-zq9vx7wPLUMB-1234")
    fields = {f["key"]: f for g in envfile.current()["groups"] for f in g["fields"]}
    assert fields["OPENAI_API_KEY"]["set"] is True
    assert fields["OPENAI_API_KEY"]["value"].endswith("1234")
    assert "zq9vx7wPLUMB" not in json.dumps(envfile.current())
    assert fields["OPENAI_API_KEY"]["source"] == "environment"


def test_saving_settings_writes_env_and_keeps_command_line_values(server, monkeypatch, tmp_path):  # noqa: F811
    app, port = server
    monkeypatch.chdir(tmp_path)
    for key in ("CHANNEL_NAME", "TTS_RATE"):
        monkeypatch.delenv(key, raising=False)
    out_dir = app.settings.output_dir
    assert req(port, "POST", "/api/settings", {"values": {"CHANNEL_NAME": "Purr Labs"}})[0] == 403  # no token
    st, _, body = req(port, "POST", "/api/settings", {"values": {"CHANNEL_NAME": "Purr Labs"}}, app.token)
    assert st == 200 and json.loads(body)["changed"] == ["CHANNEL_NAME"]
    assert "CHANNEL_NAME=\"Purr Labs\"" in (tmp_path / ".env").read_text()
    assert app.settings.channel_name == "Purr Labs"
    assert app.settings.output_dir == out_dir and app.settings.upload is False  # pinned by the test server
    st, _, body = req(port, "POST", "/api/settings", {"values": {"LLM_PROVIDER": "nope"}}, app.token)
    assert st == 400


# ---------------------------------------------------------------- Ollama downloads
class _Stream:
    def __init__(self, lines, gate=None):
        self.lines, self.gate, self.ok, self.status_code, self.text = lines, gate, True, 200, ""

    def iter_lines(self, decode_unicode=True):
        for i, line in enumerate(self.lines):
            if self.gate is not None and i == 2:
                self.gate.wait(5)
            yield json.dumps(line)

    def close(self):
        pass


def _pull_lines():
    return ([{"status": "pulling manifest"}]
            + [{"status": "pulling abc", "digest": "sha256:abc", "total": 1000, "completed": c} for c in (0, 500, 1000)]
            + [{"status": "verifying sha256 digest"}, {"status": "success"}])


def test_pull_reports_progress_until_success(monkeypatch):
    class H:
        def post(self, url, **kw):
            assert url.endswith("/api/pull") and kw["json"]["model"] == "llama3.2:3b"
            return _Stream(_pull_lines())
    monkeypatch.setattr(localai, "http", lambda: H())
    seen = []
    localai.pull("llama3.2:3b", lambda stage, pct, msg: seen.append(pct))
    assert seen[-1] == 100


def test_pull_refuses_odd_names_and_reports_ollama_errors(monkeypatch):
    with pytest.raises(ValueError):
        localai.pull("../../etc; rm -rf", lambda *a: None)

    class H:
        def post(self, url, **kw):
            return _Stream([{"error": "pull model manifest: file does not exist"}])
    monkeypatch.setattr(localai, "http", lambda: H())
    with pytest.raises(RuntimeError, match="does not exist"):
        localai.pull("nosuchmodel", lambda *a: None)


def test_downloads_run_beside_videos_and_can_be_cancelled(server, monkeypatch):  # noqa: F811
    app, port = server
    gate = threading.Event()

    class H:
        def post(self, url, **kw):
            return _Stream(_pull_lines(), gate)
    monkeypatch.setattr(localai, "http", lambda: H())
    monkeypatch.setattr(localai, "ollama_status", lambda: {"running": True})
    jid = json.loads(req(port, "POST", "/api/local/pull", {"model": "qwen3.5:4b"}, app.token)[2])["job"]
    assert _job(port, jid, until=("running",))["status"] == "running"
    # the video worker is free while the download runs
    did = json.loads(req(port, "POST", "/api/draft", {"offline": True}, app.token)[2])["job"]
    assert _job(port, did)["status"] == "done"
    assert json.loads(req(port, "POST", f"/api/jobs/{jid}/cancel", {}, app.token)[2])["ok"]
    gate.set()
    assert _job(port, jid)["status"] == "cancelled"


def test_local_api_validates_model_names(server):  # noqa: F811
    app, port = server
    st, _, body = req(port, "POST", "/api/local/pull", {"model": "a b; c"}, app.token)
    assert st == 400
    st, _, body = req(port, "GET", "/api/local")
    d = json.loads(body)
    assert {"ollama", "recommended", "offline", "platform"} <= set(d)
    assert all({"name", "size_gb", "fits", "installed"} <= set(m) for m in d["recommended"])


def test_speed_test_does_not_wait_behind_a_download(server, monkeypatch):  # noqa: F811
    app, port = server
    gate = threading.Event()

    class H:
        def post(self, url, **kw):
            return _Stream(_pull_lines(), gate)
    monkeypatch.setattr(localai, "http", lambda: H())
    monkeypatch.setattr(localai, "ollama_status", lambda: {"running": True})
    monkeypatch.setattr(localai, "benchmark", lambda m: {"model": m, "tokens_per_second": 12.0})
    pid = json.loads(req(port, "POST", "/api/local/pull", {"model": "qwen3.5:4b"}, app.token)[2])["job"]
    assert _job(port, pid, until=("running",))["status"] == "running"
    bid = json.loads(req(port, "POST", "/api/local/bench", {"model": "qwen3.5:4b"}, app.token)[2])["job"]
    assert _job(port, bid)["result"]["tokens_per_second"] == 12.0
    gate.set()
    assert _job(port, pid)["status"] == "done"
