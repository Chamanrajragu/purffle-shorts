"""Channel learning loop: read the view, like and comment counts of the videos PurffleShorts uploaded,
and show the LLM which ones worked and which flopped, so new scripts lean toward what your audience
actually watches.

    LEARN_FROM_STATS=true
    YOUTUBE_API_KEY=...     optional: a plain API key reads public stats without touching your OAuth token.
                            Without it, run `purffle-shorts auth` once more to grant read access.
"""

from __future__ import annotations

import logging
import math
import random
from datetime import datetime
from statistics import median

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


# ------------------------------------------------------------------------------------------ learning loop
MIN_RESULTS = 8  # videos with stats before the channel's own numbers steer anything


def _log_views(v: dict) -> float:
    return math.log1p(max(0, v.get("views") or 0))


def choose_style(history: History, candidates: list[str], rng: random.Random | None = None) -> str | None:
    """Pick the format for the next video by Thompson sampling over the channel's own results.

    Each format's typical (log) view count gets a posterior that starts at the channel average and narrows
    as videos of that format come in; one draw per format, best draw wins. Formats that work get chosen more
    often, untried or unlucky ones still get a fair chance, and nothing is decided on two lucky videos.
    Returns None until there are enough results to learn from."""
    rng = rng or random.Random()
    rows = [r for r in history.results() if r.get("style")]
    if len(rows) < MIN_RESULTS:
        return None
    values = [_log_views(r) for r in rows]
    mean0 = sum(values) / len(values)
    sd0 = max(0.35, math.sqrt(sum((x - mean0) ** 2 for x in values) / max(1, len(values) - 1)))
    prior = 2.0  # the channel average counts like two videos of evidence
    best, best_draw = None, -math.inf
    for style in candidates:
        xs = [_log_views(r) for r in rows if r["style"] == style]
        n = len(xs)
        mean = (prior * mean0 + sum(xs)) / (prior + n)
        draw = rng.gauss(mean, sd0 / math.sqrt(prior + n))
        if draw > best_draw:
            best, best_draw = style, draw
    return best


def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1  # ties share the average rank
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Rank correlation (-1..1): does a higher x go with a higher y? None when it can't be computed."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return round(cov / (sx * sy), 3) if sx and sy else None


def _local_hour(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().hour
    except ValueError:
        return None


def calibration(history: History) -> dict:
    """How well the predictions hold up against real views: the Script Doctor's score vs. views (Spearman),
    median views per format, and the publish hours that did best."""
    rows = history.results()
    scored = [r for r in rows if r.get("score") is not None]
    rho = spearman([r["score"] for r in scored], [r["views"] for r in scored]) if len(scored) >= 5 else None
    styles: dict[str, list[int]] = {}
    hours: dict[int, list[int]] = {}
    for r in rows:
        styles.setdefault(r.get("style") or "other", []).append(r["views"])
        h = _local_hour(r.get("publish_at") or r.get("uploaded_at"))
        if h is not None:
            hours.setdefault(h, []).append(r["views"])
    return {
        "videos": len(rows),
        "scored": len(scored),
        "score_vs_views": rho,
        "verdict": _verdict(rho, len(scored)),
        "styles": sorted(({"style": k, "videos": len(v), "median_views": int(median(v))} for k, v in styles.items()),
                         key=lambda x: -x["median_views"]),
        "hours": sorted(({"hour": h, "videos": len(v), "median_views": int(median(v))}
                         for h, v in hours.items() if len(v) >= 2), key=lambda x: -x["median_views"])[:5],
    }


def _verdict(rho: float | None, n: int) -> str:
    if rho is None:
        return f"needs at least 5 scored videos with stats (has {n})"
    if rho >= 0.5:
        return "the score predicts views well"
    if rho >= 0.25:
        return "the score predicts views somewhat"
    if rho > -0.1:
        return "the score does not predict views on this channel yet"
    return "higher scores went with fewer views here: trust your own judgement over the score"
