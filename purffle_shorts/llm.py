"""Pluggable LLMs: any OpenAI-compatible endpoint plus native Anthropic Claude, with a fallback chain.

Pick one with LLM_PROVIDER (or --provider) and LLM_MODEL (or --model). With LLM_PROVIDER=auto the
first provider whose API key is present is used. LLM_FALLBACKS=anthropic,gemini adds backups that
are tried in order when the primary fails.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

from .config import Settings
from .utils import PermanentError, http, raise_for_status, with_retries

log = logging.getLogger("purffle")


class LLMError(RuntimeError):
    pass


class LLMConfigError(LLMError):
    """Missing key, unknown provider, etc. — stop instead of retrying every video."""


@dataclass(frozen=True)
class Preset:
    name: str
    label: str
    base_url: str
    key_envs: tuple[str, ...]
    default_model: str
    kind: str = "openai"          # openai (chat/completions compatible) | anthropic
    json_mode: bool = True        # supports response_format={"type":"json_object"}
    local: bool = False


PRESETS: dict[str, Preset] = {p.name: p for p in [
    Preset("openai", "OpenAI (GPT)", "https://api.openai.com/v1", ("OPENAI_API_KEY",), "gpt-4o-mini"),
    Preset("anthropic", "Anthropic (Claude)", "", ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
           "claude-opus-5", kind="anthropic"),
    Preset("gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai",
           ("GEMINI_API_KEY", "GOOGLE_API_KEY"), "gemini-2.5-flash"),
    Preset("groq", "Groq (Llama, fast)", "https://api.groq.com/openai/v1", ("GROQ_API_KEY",),
           "llama-3.3-70b-versatile"),
    Preset("openrouter", "OpenRouter (hundreds of models)", "https://openrouter.ai/api/v1",
           ("OPENROUTER_API_KEY",), "openai/gpt-4o-mini"),
    Preset("deepseek", "DeepSeek", "https://api.deepseek.com/v1", ("DEEPSEEK_API_KEY",), "deepseek-chat"),
    Preset("mistral", "Mistral", "https://api.mistral.ai/v1", ("MISTRAL_API_KEY",), "mistral-small-latest"),
    Preset("together", "Together AI", "https://api.together.xyz/v1", ("TOGETHER_API_KEY",),
           "meta-llama/Llama-3.3-70B-Instruct-Turbo", json_mode=False),
    Preset("xai", "xAI (Grok)", "https://api.x.ai/v1", ("XAI_API_KEY",), "grok-3-mini"),
    Preset("ollama", "Ollama (local, free)", "http://localhost:11434/v1", (), "llama3.1", local=True),
    Preset("lmstudio", "LM Studio (local, free)", "http://localhost:1234/v1", (), "local-model",
           json_mode=False, local=True),
    Preset("custom", "Any OpenAI-compatible URL (LLM_BASE_URL)", "", ("LLM_API_KEY",), ""),
]}

AUTO_ORDER = ["openai", "anthropic", "gemini", "groq", "openrouter", "deepseek", "mistral", "together", "xai"]

# Claude models whose requests get server-side refusal fallbacks by default.
_CLAUDE_FALLBACK_MODELS = re.compile(r"^claude-(opus-5|fable-5)")


def _key_for(preset: Preset, settings: Settings) -> str:
    if preset.name == "custom":
        return settings.llm_api_key
    for env in preset.key_envs:
        if os.getenv(env):
            return os.environ[env]
    return settings.llm_api_key if preset.name == settings.llm_provider else ""


def _ollama_up(base_url: str) -> bool:
    try:
        root = base_url.rsplit("/v1", 1)[0]
        return http().get(root + "/api/tags", timeout=1.5).ok
    except Exception:
        return False


def ollama_url() -> str:
    host = os.getenv("OLLAMA_HOST", "").rstrip("/") or PRESETS["ollama"].base_url
    if not host.startswith("http"):
        host = "http://" + host
    return host if host.endswith("/v1") else host + "/v1"


def ollama_models(base_url: str) -> list[str] | None:
    """Models pulled into Ollama, or None when Ollama is not reachable."""
    try:
        r = http().get(base_url.rsplit("/v1", 1)[0] + "/api/tags", timeout=1.5)
        return [m.get("name", "") for m in r.json().get("models", [])] if r.ok else None
    except Exception:
        return None


def ollama_has(installed: list[str], model: str) -> bool:
    return model in installed or (":" not in model and f"{model}:latest" in installed)


def available_providers(settings: Settings) -> list[str]:
    """Providers that have credentials configured (in auto order)."""
    return [n for n in AUTO_ORDER if _key_for(PRESETS[n], settings)]


def resolve_provider_name(settings: Settings) -> str:
    name = settings.llm_provider or "auto"
    if name != "auto":
        if name not in PRESETS:
            raise LLMConfigError(f"Unknown LLM_PROVIDER '{name}'. Choose one of: {', '.join(PRESETS)}")
        return name
    if settings.llm_base_url:
        return "custom"
    found = available_providers(settings)
    if found:
        return found[0]
    if _ollama_up(ollama_url()):
        return "ollama"
    raise LLMConfigError(
        "No LLM is configured. Set one API key in .env (OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY, "
        "GROQ_API_KEY, OPENROUTER_API_KEY, DEEPSEEK_API_KEY, MISTRAL_API_KEY, ...), run Ollama locally, "
        "or try the no-key demo:  python -m purffle_shorts demo"
    )


def extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object out of a model reply that may include code fences or chatter."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I | re.S).strip()
    try:
        val = json.loads(t)
        if isinstance(val, dict):
            return val
    except json.JSONDecodeError:
        pass
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end > start:
        chunk = t[start:end + 1]
        try:
            return json.loads(chunk)
        except json.JSONDecodeError:
            # Trailing commas are the most common model mistake.
            return json.loads(re.sub(r",\s*([}\]])", r"\1", chunk))
    raise LLMError(f"Model did not return JSON: {text[:200]!r}")


class Provider:
    name: str = ""
    model: str = ""

    def complete(self, system: str, user: str, *, schema: dict | None = None,
                 temperature: float = 0.9, max_tokens: int = 4000) -> str:
        raise NotImplementedError

    def __str__(self) -> str:
        return f"{self.name}:{self.model}"


class OpenAICompatible(Provider):
    def __init__(self, preset: Preset, model: str, api_key: str, base_url: str):
        self.name, self.preset, self.model = preset.name, preset, model
        self.api_key, self.base_url = api_key, base_url.rstrip("/")
        self._json_mode = preset.json_mode

    def _is_reasoning_model(self) -> bool:
        return bool(re.match(r"^(o\d|gpt-5)", self.model.split("/")[-1]))

    def complete(self, system, user, *, schema=None, temperature=0.9, max_tokens=4000) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if self._is_reasoning_model():
            payload["max_completion_tokens"] = max(max_tokens, 8000)  # room for hidden reasoning tokens
        else:
            payload["temperature"] = temperature
            payload["max_tokens"] = max_tokens
        if schema is not None and self._json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.name == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/Chamanrajragu/purffle-shorts"
            headers["X-Title"] = "PurffleShorts"
        try:
            r = http().post(f"{self.base_url}/chat/completions", json=payload, headers=headers, timeout=180)
            raise_for_status(r, f"{self}")
        except PermanentError as e:
            if "response_format" in payload and "response_format" in str(e):
                self._json_mode = False  # endpoint doesn't support JSON mode; rely on prompt + parser
                return self.complete(system, user, schema=schema, temperature=temperature, max_tokens=max_tokens)
            raise
        data = r.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"{self}: unexpected response {str(data)[:200]}") from e
        if not content:
            raise LLMError(f"{self}: empty reply (finish_reason={data['choices'][0].get('finish_reason')})")
        return content


class AnthropicProvider(Provider):
    """Native Claude via the official Anthropic SDK (structured JSON output + refusal fallbacks)."""

    def __init__(self, model: str, api_key: str, effort: str = ""):
        try:
            import anthropic
        except ImportError as e:
            raise LLMConfigError("The Anthropic provider needs the SDK:  pip install anthropic") from e
        self.name, self.model, self.effort = "anthropic", model, effort
        self._anthropic = anthropic
        # With no explicit key the SDK resolves ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / `ant auth login`.
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    def complete(self, system, user, *, schema=None, temperature=0.9, max_tokens=4000) -> str:
        a = self._anthropic
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 16000,  # thinking is on by default on current Claude models; leave room
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        output_config: dict[str, Any] = {}
        if schema:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        if self.effort:
            output_config["effort"] = self.effort
        if output_config:
            kwargs["output_config"] = output_config
        # Sampling params (temperature) are rejected by current Claude models, so none are sent.
        try:
            if _CLAUDE_FALLBACK_MODELS.match(self.model):
                resp = self.client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
            else:
                resp = self.client.messages.create(**kwargs)
        except (a.BadRequestError, a.AuthenticationError, a.PermissionDeniedError, a.NotFoundError) as e:
            raise PermanentError(f"{self}: {e}") from e
        except (a.RateLimitError, a.APIStatusError, a.APIConnectionError) as e:
            raise LLMError(f"{self}: {e}") from e
        if resp.stop_reason == "refusal":
            raise PermanentError(f"{self}: request declined by the model")
        text = "".join(b.text for b in resp.content if b.type == "text")
        if not text.strip():
            raise LLMError(f"{self}: empty reply (stop_reason={resp.stop_reason})")
        return text


def build_provider(name: str, settings: Settings, model: str = "") -> Provider:
    preset = PRESETS[name]
    chosen = model
    model = model or preset.default_model
    key = _key_for(preset, settings)
    if preset.kind == "anthropic":
        return AnthropicProvider(model, key, settings.anthropic_effort)
    base_url = preset.base_url
    if name == "custom":
        base_url = settings.llm_base_url
        if not base_url or not model:
            raise LLMConfigError("LLM_PROVIDER=custom needs LLM_BASE_URL and LLM_MODEL")
    elif name == "ollama":
        base_url = ollama_url()
        installed = None if chosen else ollama_models(base_url)
        if installed and not ollama_has(installed, model):
            # No model chosen and the default is not pulled: use one that is, instead of failing every video.
            log.info("Ollama has no '%s'; using installed model '%s' (set LLM_MODEL to choose)", model, installed[0])
            model = installed[0]
    if settings.llm_base_url and name == settings.llm_provider:
        base_url = settings.llm_base_url
    if not key and not preset.local and name != "custom":
        raise LLMConfigError(f"{preset.label}: set {' or '.join(preset.key_envs)} in .env")
    return OpenAICompatible(preset, model, key, base_url)


class LLM:
    """Primary provider + ordered fallbacks. ``complete_json`` returns a parsed dict."""

    def __init__(self, settings: Settings):
        self.settings = settings
        primary = resolve_provider_name(settings)
        names = [primary] + [n for n in settings.llm_fallbacks if n != primary]
        self.providers: list[Provider] = []
        for n in names:
            if n not in PRESETS:
                log.warning("Ignoring unknown LLM fallback '%s'", n)
                continue
            try:
                self.providers.append(build_provider(n, settings, settings.llm_model if n == primary else ""))
            except LLMError as e:
                if n == primary:
                    raise
                log.warning("Skipping fallback %s: %s", n, e)

    @property
    def label(self) -> str:
        return str(self.providers[0])

    def complete_json(self, system: str, user: str, schema: dict | None = None,
                      max_tokens: int = 4000) -> dict[str, Any]:
        errors = []
        for p in self.providers:
            def _call(p=p):
                text = p.complete(system, user, schema=schema if schema is not None else {}, max_tokens=max_tokens,
                                  temperature=self.settings.llm_temperature)
                return extract_json(text)
            try:
                result = with_retries(_call, attempts=2, base_delay=3, label=f"LLM {p}")
                if p is not self.providers[0]:
                    log.info("Used fallback LLM %s", p)
                return result
            except Exception as e:  # try the next provider
                errors.append(f"{p}: {e}")
                log.warning("LLM %s failed: %s", p, e)
        raise LLMError("All LLM providers failed:\n  " + "\n  ".join(errors))
