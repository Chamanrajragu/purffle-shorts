"""Webhook notifications: a message to Discord, Slack or any URL when a video is rendered, uploaded,
scheduled or fails, so an autopilot running on another machine can be watched from a phone.

    NOTIFY_WEBHOOK=https://discord.com/api/webhooks/...   (or https://hooks.slack.com/services/...)

Any other URL receives the event as JSON. Notifications never stop or slow down a video: failures are
logged and ignored.
"""

from __future__ import annotations

import logging
import threading

from .config import Settings
from .utils import http, redact

log = logging.getLogger("purffle")

ICONS = {"rendered": "🎬", "uploaded": "✅", "scheduled": "🗓️", "queued": "⏳", "failed": "❌"}


def message(event: str, title: str, *, url: str = "", detail: str = "") -> str:
    icon = ICONS.get(event, "•")
    parts = [f"{icon} **{event.capitalize()}**: {title or 'video'}"]
    if url:
        parts.append(url)
    if detail:
        parts.append(detail[:300])
    return "\n".join(parts)


def payload(webhook: str, event: str, data: dict) -> dict:
    text = message(event, data.get("title", ""), url=data.get("url", ""), detail=data.get("detail", ""))
    if "discord.com/api/webhooks" in webhook or "discordapp.com/api/webhooks" in webhook:
        return {"content": text[:1900], "username": "PurffleShorts"}
    if "hooks.slack.com" in webhook:
        return {"text": text.replace("**", "*")}
    return {"event": event, "text": text, **data}


def send(settings: Settings, event: str, **data) -> threading.Thread | None:
    """Post in the background. Returns the thread (tests join it)."""
    hook = settings.notify_webhook
    if not hook:
        return None

    def _post():
        try:
            r = http().post(hook, json=payload(hook, event, data), timeout=15)
            if r.status_code >= 400:
                log.warning("Notification webhook answered HTTP %s", r.status_code)
        except Exception as e:
            log.warning("Notification failed: %s", redact(e))

    t = threading.Thread(target=_post, name="notify", daemon=True)
    t.start()
    return t
