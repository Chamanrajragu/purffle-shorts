"""Autopilot for the Studio: make a video every few hours while the Studio is open.

The command line has had this for long (``purffle-shorts run``); this brings it to people who only use the
desktop app. It takes the oldest idea in the queue, or picks a fresh topic from the channel's niches when
the queue is empty, uses a saved preset (or the Settings defaults), keeps to a daily cap, and publishes only
if asked and allowed in Settings. Its state lives in the history database, so it carries on after a restart.
"""

from __future__ import annotations

import json
import time
from datetime import datetime

META_KEY = "autopilot"
DEFAULTS = {"on": False, "every_hours": 4.0, "per_day": 3, "upload": False, "preset": "",
            "last_run": 0.0, "day": "", "made": 0}


def today(now: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if now is None else now).strftime("%Y-%m-%d")


def load(history) -> dict:
    try:
        data = json.loads(history.get_meta(META_KEY) or "{}")
    except (TypeError, ValueError):
        data = {}
    return {**DEFAULTS, **(data if isinstance(data, dict) else {})}


def save(history, state: dict) -> dict:
    state = {k: state.get(k, v) for k, v in DEFAULTS.items()}
    history.set_meta(META_KEY, json.dumps(state))
    return state


def update(history, body: dict) -> dict:
    """Apply the user's changes (on/off, pace, cap, publishing, preset); the run counters are kept."""
    st = load(history)
    if isinstance(body.get("on"), bool):
        if body["on"] and not st["on"]:
            st["last_run"] = 0.0      # turning it on starts the first video soon, not hours later
        st["on"] = body["on"]
    if "every_hours" in body:
        try:
            st["every_hours"] = max(0.5, min(48.0, float(body["every_hours"])))
        except (TypeError, ValueError):
            raise ValueError("every_hours must be a number of hours") from None
    if "per_day" in body:
        try:
            st["per_day"] = max(1, min(48, int(body["per_day"])))
        except (TypeError, ValueError):
            raise ValueError("per_day must be a whole number") from None
    if isinstance(body.get("upload"), bool):
        st["upload"] = body["upload"]
    if "preset" in body:
        st["preset"] = " ".join(str(body.get("preset") or "").split())[:40]
    return save(history, st)


def made_today(st: dict, now: float | None = None) -> int:
    return int(st.get("made") or 0) if st.get("day") == today(now) else 0


def next_at(st: dict, now: float | None = None) -> float | None:
    """When the next video starts (epoch seconds), or None when it is off. With today's cap reached, it is
    the start of tomorrow."""
    if not st.get("on"):
        return None
    now = time.time() if now is None else now
    at = max(now, float(st.get("last_run") or 0) + float(st["every_hours"]) * 3600)
    if made_today(st, now) >= int(st["per_day"]):
        tomorrow = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() + 86400
        at = max(at, tomorrow)
    return at


def due(st: dict, busy: bool, now: float | None = None) -> bool:
    """Start a video now? Never while another video job is waiting or running."""
    at = next_at(st, now)
    return at is not None and not busy and (time.time() if now is None else now) >= at


def mark_started(history, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    st = load(history)
    st["made"] = made_today(st, now) + 1
    st["day"], st["last_run"] = today(now), now
    return save(history, st)


def public(st: dict, now: float | None = None) -> dict:
    return {k: st[k] for k in ("on", "every_hours", "per_day", "upload", "preset")} | {
        "made_today": made_today(st, now), "next_at": next_at(st, now)}
