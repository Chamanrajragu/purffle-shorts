"""Small shared helpers: retries, HTTP, slugs, text cleanup."""

from __future__ import annotations

import logging
import os
import random
import re
import time
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import requests

log = logging.getLogger("purffle")

T = TypeVar("T")

USER_AGENT = "PurffleShorts/2.0 (+https://github.com/Chamanrajragu/purffle-shorts)"


class PermanentError(Exception):
    """An error that retrying will not fix (bad key, 4xx, invalid input)."""


def with_retries(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 2.0,
    label: str = "operation",
    retry_on: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    """Call ``fn`` with exponential backoff + jitter. PermanentError is never retried."""
    for i in range(1, attempts + 1):
        try:
            return fn()
        except PermanentError:
            raise
        except retry_on as e:
            if i == attempts:
                log.error("%s failed after %d attempts: %s", label, attempts, redact(e))
                raise
            wait = base_delay * (2 ** (i - 1)) + random.uniform(0, 0.5)
            log.warning("%s attempt %d/%d failed: %s — retrying in %.1fs", label, i, attempts, redact(e), wait)
            time.sleep(wait)
    raise RuntimeError("unreachable")


_session: requests.Session | None = None


def http() -> requests.Session:
    """A shared requests session with a descriptive User-Agent."""
    global _session
    if _session is None:
        s = requests.Session()
        s.headers["User-Agent"] = USER_AGENT
        _session = s
    return _session


def raise_for_status(resp: requests.Response, what: str) -> None:
    """Raise PermanentError for 4xx (except 408/429) and a retryable error otherwise."""
    if resp.status_code < 400:
        return
    body = resp.text[:300].replace("\n", " ")
    msg = f"{what}: HTTP {resp.status_code} — {body}"
    if 400 <= resp.status_code < 500 and resp.status_code not in (408, 409, 429):
        raise PermanentError(msg)
    raise RuntimeError(msg)


def download(url: str, dest: Path, *, headers: dict | None = None, timeout: int = 60,
             max_bytes: int = 400 * 1024 * 1024) -> Path:
    """Stream ``url`` to ``dest`` atomically (via a .part file), with retries."""
    dest.parent.mkdir(parents=True, exist_ok=True)

    def _do() -> Path:
        tmp = dest.with_suffix(dest.suffix + ".part")
        with http().get(url, stream=True, timeout=timeout, headers=headers or {}) as r:
            raise_for_status(r, f"download {url[:80]}")
            size = 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    if chunk:
                        size += len(chunk)
                        if size > max_bytes:
                            raise PermanentError(f"download too large (> {max_bytes >> 20} MB): {url[:80]}")
                        f.write(chunk)
        if size == 0:
            raise RuntimeError(f"empty download: {url[:80]}")
        os.replace(tmp, dest)
        return dest

    return with_retries(_do, attempts=3, label=f"download {dest.name}")


_SECRET_RE = re.compile(r"(?i)\b((?:api_?)?key|token|access_token)=[^&\s'\"]+")
# Some services echo your IP in error bodies (e.g. "Queue full for IP: ..."); logs get pasted into issues.
_IP_RE = re.compile(r"(?i)(?<![\w:.])(?:(?:[0-9a-f]{1,4}:){4,7}[0-9a-f]{1,4}|(?:\d{1,3}\.){3}\d{1,3})(?![\w:.])")


def redact(text: object) -> str:
    """Hide API keys that some services (e.g. Pixabay) put in URLs, and IP addresses, before they reach a log."""
    return _IP_RE.sub("<ip>", _SECRET_RE.sub(r"\1=***", str(text)))


def slugify(text: str, max_len: int = 48) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text[:max_len].rstrip("-")) or "short"


_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0000FE0F\U0000200D\U00002190-\U000021FF\U00002B00-\U00002BFF]+"
)


def strip_emoji(text: str) -> str:
    return _EMOJI_RE.sub("", text)


def clean_narration(text: str) -> str:
    """Remove things a TTS voice should never read aloud: stage directions, labels, emoji, hashtags, markdown."""
    t = strip_emoji(text)
    t = re.sub(r"\[[^\]]*\]", " ", t)                      # [Hook], [Music]
    t = re.sub(r"\((?:pause|beat|music|sfx|laughs?)[^)]*\)", " ", t, flags=re.I)
    t = re.sub(r"^\s*(?:narrator|voice ?over|vo|host|scene \d+|hook|cta)\s*:\s*", "", t, flags=re.I | re.M)
    t = re.sub(r"(?<!\w)#\w+", " ", t)                     # hashtags
    t = re.sub(r"[*_`~>|]+", " ", t)                        # markdown
    t = re.sub(r"https?://\S+", " ", t)
    t = t.replace("—", ", ").replace("–", ", ")   # dashes read better as pauses
    t = re.sub(r"\s+", " ", t).strip()
    return t


def truncate_words(text: str, limit: int) -> str:
    """Trim to ``limit`` characters on a word boundary."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return cut or text[:limit]
