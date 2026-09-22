import sys
import types

import pytest

from purffle_shorts import llm as L
from purffle_shorts.config import Settings
from purffle_shorts.utils import PermanentError


class FakeResp:
    def __init__(self, status=200, data=None):
        self.status_code, self._data = status, data or {}
        self.text = str(self._data)

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self.resp


def _ok(content='{"x": 1}'):
    return FakeResp(200, {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})


def test_auto_picks_first_configured(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("GEMINI_API_KEY", "m")
    assert L.resolve_provider_name(Settings()) == "gemini"


def test_no_provider_gives_helpful_error(monkeypatch):
    monkeypatch.setattr(L, "_ollama_up", lambda url: False)
    with pytest.raises(L.LLMError, match="demo"):
        L.resolve_provider_name(Settings())


def test_openai_payload_for_chat_model(monkeypatch):
    sess = FakeSession(_ok())
    monkeypatch.setattr(L, "http", lambda: sess)
    p = L.OpenAICompatible(L.PRESETS["openai"], "gpt-4o-mini", "k", L.PRESETS["openai"].base_url)
    assert p.complete("sys", "user", schema={}) == '{"x": 1}'
    body = sess.calls[0]["json"]
    assert body["temperature"] == 0.9 and body["max_tokens"] == 4000
    assert body["response_format"] == {"type": "json_object"}
    assert sess.calls[0]["headers"]["Authorization"] == "Bearer k"


def test_reasoning_models_skip_temperature(monkeypatch):
    sess = FakeSession(_ok())
    monkeypatch.setattr(L, "http", lambda: sess)
    L.OpenAICompatible(L.PRESETS["openai"], "gpt-5-mini", "k", "https://x/v1").complete("s", "u", schema={})
    body = sess.calls[0]["json"]
    assert "temperature" not in body and body["max_completion_tokens"] >= 8000


def test_json_mode_is_dropped_when_unsupported(monkeypatch):
    calls = []

    class S:
        def post(self, url, json=None, headers=None, timeout=None):
            calls.append(dict(json))
            if "response_format" in json:
                return FakeResp(400, {"error": "response_format not supported"})
            return _ok()
    monkeypatch.setattr(L, "http", lambda: S())
    p = L.OpenAICompatible(L.PRESETS["groq"], "m", "k", "https://x/v1")
    assert p.complete("s", "u", schema={}) == '{"x": 1}'
    assert "response_format" in calls[0] and "response_format" not in calls[1]


def test_fallback_chain_uses_next_provider():
    class Bad(L.Provider):
        name, model = "bad", "m"

        def complete(self, *a, **k):
            raise PermanentError("401 bad key")

    class Good(L.Provider):
        name, model = "good", "m"

        def complete(self, *a, **k):
            return '```json\n{"ok": true}\n```'

    chain = object.__new__(L.LLM)
    chain.settings, chain.providers = Settings(), [Bad(), Good()]
    assert chain.complete_json("s", "u") == {"ok": True}


def _fake_anthropic(monkeypatch, captured):
    mod = types.ModuleType("anthropic")

    class Err(Exception):
        pass
    for name in ("BadRequestError", "AuthenticationError", "PermissionDeniedError", "NotFoundError",
                 "RateLimitError", "APIStatusError", "APIConnectionError"):
        setattr(mod, name, type(name, (Err,), {}))

    reply = types.SimpleNamespace(stop_reason="end_turn",
                                  content=[types.SimpleNamespace(type="text", text='{"a": 1}')])

    class Messages:
        def __init__(self, kind):
            self.kind = kind

        def create(self, **kw):
            captured.append((self.kind, kw))
            return reply

    class Client:
        def __init__(self, api_key=None):
            self.messages = Messages("messages")
            self.beta = types.SimpleNamespace(messages=Messages("beta"))
    mod.Anthropic = Client
    monkeypatch.setitem(sys.modules, "anthropic", mod)


def test_anthropic_opus_uses_structured_output_and_fallbacks(monkeypatch):
    captured = []
    _fake_anthropic(monkeypatch, captured)
    p = L.AnthropicProvider("claude-opus-5", "key")
    assert p.complete("sys", "user", schema={"type": "object"}) == '{"a": 1}'
    kind, kw = captured[0]
    assert kind == "beta" and kw["fallbacks"] == "default"
    assert kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert "temperature" not in kw and kw["system"] == "sys"


def test_anthropic_other_models_use_plain_messages(monkeypatch):
    captured = []
    _fake_anthropic(monkeypatch, captured)
    L.AnthropicProvider("claude-haiku-4-5", "key").complete("s", "u", schema={})
    kind, kw = captured[0]
    assert kind == "messages" and "fallbacks" not in kw and "output_config" not in kw


@pytest.mark.parametrize("host,url", [
    ("", "http://localhost:11434/v1"),
    ("127.0.0.1:11434", "http://127.0.0.1:11434/v1"),
    ("http://gpu-box:11434/", "http://gpu-box:11434/v1"),
])
def test_ollama_url_accepts_bare_host(monkeypatch, host, url):
    monkeypatch.setenv("OLLAMA_HOST", host)
    assert L.ollama_url() == url


def test_ollama_uses_an_installed_model_when_default_missing(monkeypatch):
    monkeypatch.setattr(L, "ollama_models", lambda url: ["granite4.1:3b", "qwen3:8b"])
    assert L.build_provider("ollama", Settings()).model == "granite4.1:3b"
    assert L.build_provider("ollama", Settings(), "qwen3:8b").model == "qwen3:8b"
    monkeypatch.setattr(L, "ollama_models", lambda url: ["llama3.1:latest"])
    assert L.build_provider("ollama", Settings()).model == "llama3.1"
    assert L.ollama_has(["llama3.1:latest"], "llama3.1") and not L.ollama_has(["llama3.1:8b"], "llama3.1")
