"""Saved Create-form recipes ("presets"): a name and the look, voice and format to apply in one click.

Kept in the history database's meta table, so they live with the channel's videos (and survive a desktop app
starting on a different port, which would lose anything kept in the browser).
"""

from __future__ import annotations

import json

META_KEY = "presets"
MAX_PRESETS = 30
# Create-form fields a preset carries. The topic, web page and idea source are left out: a preset is how a
# video looks and sounds, not what it is about.
KEYS = ("style", "language", "duration", "aspect", "caption_style", "caption_position", "grade", "transition",
        "tts", "voice", "voice_b", "provider", "model", "review", "also_langs", "music", "visuals", "background",
        "layout", "sfx", "emphasis", "emoji")


def clean_form(form: dict) -> dict:
    """Only known fields, only plain values, bounded sizes. Values are validated again when a job runs."""
    out: dict = {}
    for k in KEYS:
        v = form.get(k) if isinstance(form, dict) else None
        if isinstance(v, bool) or (isinstance(v, int | float) and not isinstance(v, bool)):
            out[k] = v
        elif isinstance(v, str):
            out[k] = v[:300]
        elif isinstance(v, list):
            out[k] = [str(x)[:40] for x in v[:8]]
    return out


def clean_name(name) -> str:
    return " ".join(str(name or "").split())[:40]


def load(history) -> dict[str, dict]:
    try:
        data = json.loads(history.get_meta(META_KEY) or "{}")
    except (TypeError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def save(history, name, form: dict) -> dict[str, dict]:
    name = clean_name(name)
    if not name:
        raise ValueError("give the preset a name")
    items = load(history)
    if name not in items and len(items) >= MAX_PRESETS:
        raise ValueError(f"up to {MAX_PRESETS} presets: delete one first")
    items[name] = clean_form(form)
    history.set_meta(META_KEY, json.dumps(items))
    return items


def delete(history, name) -> dict[str, dict]:
    items = load(history)
    items.pop(clean_name(name), None)
    history.set_meta(META_KEY, json.dumps(items))
    return items
