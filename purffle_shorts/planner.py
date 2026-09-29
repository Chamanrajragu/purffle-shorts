"""Content planner: the LLM brainstorms a batch of specific, non-repeating video ideas for your niches
and puts them in the idea queue. The autopilot always makes queued ideas first, so a week of videos can
be planned (and pruned) in one go:

    purffle-shorts plan --count 14 --niche "space and the universe"
"""

from __future__ import annotations

import logging
import random

from .config import Settings
from .history import History
from .script import LANGUAGES, STYLES

log = logging.getLogger("purffle")

IDEAS_SCHEMA = {
    "type": "object",
    "properties": {
        "ideas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "style": {"type": "string", "enum": list(STYLES)},
                    "angle": {"type": "string"},
                },
                "required": ["subject", "style", "angle"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["ideas"],
    "additionalProperties": False,
}


def plan_prompt(settings: Settings, count: int, niches: list[str], avoid: list[str], insights: str = "") -> tuple[str, str]:
    lang = LANGUAGES.get(settings.language, settings.language)
    formats = ", ".join(f"{k} ({v.split(':')[0].split('.')[0].lower()})" for k, v in STYLES.items())
    system = ("You are the content strategist of a fast-growing faceless YouTube Shorts channel. You reply with "
              "a single JSON object and nothing else.")
    avoid_block = ("Already made or planned (never repeat these or near-duplicates):\n"
                   + "\n".join(f"- {a}" for a in avoid[:80]) + "\n\n") if avoid else ""
    ins = f"{insights}\n\n" if insights else ""
    user = f"""Plan {count} YouTube Shorts for a channel about: {"; ".join(niches)}.
Audience: {settings.audience}. Language of the videos: {lang} (write subject and angle in English).

{ins}{avoid_block}Each idea:
- subject: one specific, surprising, searchable topic (not a broad theme), e.g. "why octopuses have blue blood".
- style: the format that fits it best, one of: {formats}. Mix formats; use each at most {max(2, count // 3)} times.
- angle: one sentence with the hook or twist that makes people stop scrolling.
Prefer evergreen topics with real facts behind them. Return JSON: {{"ideas": [{{subject, style, angle}}, ...]}}."""
    return system, user


def plan_ideas(llm, settings: Settings, history: History, count: int = 10, niches: list[str] | None = None,
               insights: str = "") -> list[dict]:
    count = max(1, min(50, count))
    niches = niches or random.sample(settings.niches, min(3, len(settings.niches))) or ["interesting facts"]
    avoid = history.recent_titles(60) + [i["subject"] for i in history.ideas("pending")]
    system, user = plan_prompt(settings, count, niches, avoid, insights)
    data = llm.complete_json(system, user, IDEAS_SCHEMA, max_tokens=6000)
    seen = {a.lower() for a in avoid}
    saved = []
    for idea in data.get("ideas") or []:
        if len(saved) >= count:
            break
        if not isinstance(idea, dict):
            continue
        subject = str(idea.get("subject") or "").strip()
        if len(subject) < 4 or subject.lower() in seen:
            continue
        seen.add(subject.lower())
        style = idea.get("style") if idea.get("style") in STYLES else ""
        angle = str(idea.get("angle") or "").strip()
        iid = history.add_idea(subject, style, angle)
        saved.append({"id": iid, "subject": subject, "style": style, "notes": angle})
    log.info("Planner added %d idea(s) to the queue", len(saved))
    return saved
