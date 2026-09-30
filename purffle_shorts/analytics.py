"""Channel learning loop: read the view, like and comment counts of the videos PurffleShorts uploaded,
and show the LLM which ones worked and which flopped, so new scripts lean toward what your audience
actually watches.

    LEARN_FROM_STATS=true
    YOUTUBE_API_KEY=...     optional: a plain API key reads public stats without touching your OAuth token.
                            Without it, run `purffle-shorts auth` once more to grant read access.
"""

from __future__ import annotations

import logging

from .config import Settings
from .history import History
from .utils import http, raise_for_status, redact

log = logging.getLogger("purffle")

API = "https://www.googleapis.com/youtube/v3/videos"


def _fetch_with_key(ids: list[str], key: str) -> list[dict]:
    r = http().get(API, params={"part": "statistics", "id": ",".join(ids), "key": key}, timeout=30)
    raise_for_status(r, "YouTube stats")
    return r.json().get("items", [])


def _fetch_with_oauth(ids: list[str], settings: Settings) -> list[dict]:
    from . import youtube
    yt = youtube.service(settings, interactive=False, extra_scopes=[youtube.SCOPE_READONLY])
    return yt.videos().list(part="statistics", id=",".join(ids), maxResults=50).execute().get("items", [])


def sync_stats(settings: Settings, history: History) -> int:
    """Refresh stats for every uploaded video (1 quota unit per 50 videos). Returns how many were updated."""
    ids = history.live_video_ids()
    updated = 0
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        try:
            items = (_fetch_with_key(batch, settings.youtube_api_key) if settings.youtube_api_key
                     else _fetch_with_oauth(batch, settings))
        except Exception as e:
            log.warning("Could not read channel stats: %s", redact(e))
            break
        for it in items:
            st = it.get("statistics") or {}
            history.set_stats(it.get("id", ""), int(st.get("viewCount") or 0), int(st.get("likeCount") or 0),
                              int(st.get("commentCount") or 0))
            updated += 1
    if updated:
        log.info("Channel stats refreshed for %d video(s)", updated)
    return updated


def insights(history: History, n: int = 5) -> str:
    """A prompt block that shows the LLM the channel's winners and losers (empty until there is data)."""
    best = history.performers(n, best=True)
    if len(best) < 3:
        return ""
    worst = [w for w in history.performers(n, best=False) if w["id"] not in {b["id"] for b in best}]

    def row(v: dict) -> str:
        return f'- "{v["title"]}" ({v["style"] or "?"}): {v["views"]:,} views, {v["likes"] or 0:,} likes'
    text = "What performed best on this channel so far:\n" + "\n".join(row(v) for v in best)
    if worst:
        text += "\nWhat performed worst:\n" + "\n".join(row(v) for v in worst[:3])
    text += ("\nLearn from this: give the new video the kind of hook, subject and angle the winners have. "
             "Don't copy their titles.")
    return text
