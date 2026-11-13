"""Tell desktop users when a newer PurffleShorts is out.

The Studio asks GitHub for the newest release at most once a day and remembers the answer in the history
database. Nothing about the user is sent: it is one anonymous GET to GitHub's public API. ``CHECK_UPDATES=false``
turns it off. Any failure (offline, rate limit, odd reply) is ignored; the next try is a day later.
"""

from __future__ import annotations

import json
import logging
import re
import time

from . import __version__

log = logging.getLogger(__name__)

REPO = "Chamanrajragu/purffle-shorts"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES = f"https://github.com/{REPO}/releases/latest"
META_KEY = "update_check"
EVERY = 24 * 3600


def parse(version: str) -> tuple[int, ...]:
    """'v3.1.0' -> (3, 1, 0). Pre-release suffixes are dropped; anything unreadable is (0,)."""
    m = re.match(r"\s*v?(\d+(?:\.\d+)*)", str(version or ""))
    return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)


def newer(latest: str, current: str = __version__) -> bool:
    a, b = parse(latest), parse(current)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def load(history) -> dict:
    try:
        data = json.loads(history.get_meta(META_KEY) or "{}")
    except (TypeError, ValueError):
        data = {}
    return data if isinstance(data, dict) else {}


def fetch(timeout: float = 8.0) -> dict | None:
    """The newest release on GitHub: {'version', 'url'}, or None."""
    import requests
    r = requests.get(API, timeout=timeout, headers={"Accept": "application/vnd.github+json",
                                                     "User-Agent": f"PurffleShorts/{__version__}"})
    if r.status_code != 200:
        return None
    data = r.json()
    tag = str(data.get("tag_name") or "")
    if not tag or data.get("draft") or data.get("prerelease"):
        return None
    url = str(data.get("html_url") or "")
    return {"version": tag.lstrip("v"), "url": url if url.startswith("https://github.com/") else RELEASES}


def check(history, now: float | None = None, fetcher=fetch) -> dict:
    """Refresh the remembered answer when it is a day old. Returns what is remembered."""
    now = time.time() if now is None else now
    st = load(history)
    if now - float(st.get("at") or 0) < EVERY:
        return st
    st = {**st, "at": now}
    try:
        got = fetcher()
        if got:
            st.update(latest=got["version"], url=got["url"])
    except Exception as e:  # offline, DNS, rate limit, bad JSON: try again tomorrow
        log.debug("Update check failed: %s", e)
    history.set_meta(META_KEY, json.dumps(st))
    return st


def available(history) -> dict | None:
    """{'version', 'url'} when the remembered newest release is newer than this one."""
    st = load(history)
    latest = st.get("latest")
    if latest and newer(latest):
        return {"version": str(latest), "url": str(st.get("url") or RELEASES)}
    return None
