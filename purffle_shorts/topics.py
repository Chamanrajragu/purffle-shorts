"""Where video ideas come from. Mix sources with TOPIC_SOURCES, optionally weighted:
TOPIC_SOURCES=niche:4,trending:1,wikipedia:1

  niche      the AI picks a fresh, specific topic inside one of your NICHES (default)
  trending   today's Google Trends searches for TRENDS_GEO (tragedies and elections are skipped)
  wikipedia  "On this day" historical events
  reddit     r/todayilearned top posts of the day
  file       your own list: one topic per line in topics.txt (each used once)
"""

from __future__ import annotations

import logging
import random
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import Settings
from .history import History
from .utils import http, raise_for_status

log = logging.getLogger("purffle")

SENSITIVE = re.compile(
    r"\b(dies|died|dead|death|killed|kills|murder\w*|shooting|shot|crash\w*|funeral|obituary|suicide|attack\w*|"
    r"wars?|bomb\w*|hostage|victims?|arrested|charged|rape|abuse|massacre|genocide|terror\w*|assassinat\w*|coup|"
    r"elect\w*|ballot|campaign|president|prime minister|parliament)\b", re.I)


@dataclass
class Topic:
    subject: str
    source: str
    key: str = ""
    context: str = ""


def _weighted_sources(settings: Settings) -> list[tuple[str, float]]:
    out = []
    for item in settings.topic_sources or ["niche"]:
        name, _, w = item.partition(":")
        try:
            weight = float(w) if w else 1.0
        except ValueError:
            weight = 1.0
        out.append((name.strip().lower(), max(0.0, weight)))
    return out or [("niche", 1.0)]


def from_niche(settings: Settings) -> Topic:
    niche = random.choice(settings.niches or ["interesting facts"])
    return Topic(niche, "niche", key="")


def from_file(settings: Settings, history: History) -> Topic | None:
    p = Path(settings.topics_file)
    if not p.exists():
        return None
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key = f"file:{line}"
        if not history.topic_used(key):
            return Topic(line, "file", key=key)
    log.info("All topics in %s have been used", p)
    return None


def from_trends(settings: Settings, history: History) -> Topic | None:
    r = http().get("https://trends.google.com/trending/rss", params={"geo": settings.trends_geo}, timeout=20)
    raise_for_status(r, "Google Trends RSS")
    root = ET.fromstring(r.content)
    ns = {"ht": "https://trends.google.com/trending/rss"}
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        news = [((n.findtext("ht:news_item_title", namespaces=ns) or "") + " — " +
                 (n.findtext("ht:news_item_snippet", namespaces=ns) or "")).strip(" —")
                for n in item.findall("ht:news_item", ns)]
        blob = " ".join([title, *news])
        key = f"trend:{title}"
        if not title or history.topic_used(key) or SENSITIVE.search(blob):
            continue
        return Topic(title, "trending", key=key, context="\n".join(news[:3]))
    return None


def from_wikipedia(settings: Settings, history: History) -> Topic | None:
    today = datetime.now()
    lang = settings.language.split("-")[0]
    url = f"https://{lang}.wikipedia.org/api/rest_v1/feed/onthisday/events/{today:%m}/{today:%d}"
    r = http().get(url, timeout=20)
    raise_for_status(r, "Wikipedia On This Day")
    events = r.json().get("events", [])
    random.shuffle(events)
    for ev in events:
        text, year = ev.get("text", ""), ev.get("year")
        key = f"wiki:{year}:{text[:80]}"
        if not text or history.topic_used(key) or SENSITIVE.search(text):
            continue
        pages = ev.get("pages") or []
        extract = next((p.get("extract", "") for p in pages if p.get("extract")), "")
        return Topic(f"On this day in {year}: {text}", "wikipedia", key=key, context=extract[:1500])
    return None


def from_reddit(settings: Settings, history: History) -> Topic | None:
    # The JSON API now rejects anonymous clients; the public Atom feed still works.
    r = http().get("https://www.reddit.com/r/todayilearned/top/.rss", params={"t": "day"}, timeout=20)
    raise_for_status(r, "Reddit TIL")
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for entry in ET.fromstring(r.content).findall("a:entry", ns):
        raw = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
        title = re.sub(r"^TIL\s*(that\s*)?", "", raw, flags=re.I).strip(" :-")
        key = f"reddit:{entry.findtext('a:id', default=raw, namespaces=ns)}"
        if not title or history.topic_used(key) or SENSITIVE.search(title):
            continue
        return Topic(title, "reddit", key=key, context=raw)
    return None


def pick_topic(settings: Settings, history: History, explicit: str | None = None,
               source: str | None = None) -> Topic:
    if explicit:
        return Topic(explicit, "manual")
    if settings.offline:
        return Topic("octopus superpowers", "manual")
    choices = [(source, 1.0)] if source else _weighted_sources(settings)
    names, weights = zip(*choices)
    name = random.choices(names, weights=weights, k=1)[0] if sum(weights) > 0 else "niche"
    fetch = {"file": from_file, "trending": from_trends, "wikipedia": from_wikipedia, "reddit": from_reddit}
    if name in fetch:
        try:
            topic = fetch[name](settings, history)
            if topic:
                return topic
            log.info("Topic source '%s' had nothing new; falling back to a niche topic", name)
        except Exception as e:
            log.warning("Topic source '%s' failed (%s); falling back to a niche topic", name, e)
    elif name != "niche":
        log.warning("Unknown topic source '%s'; using niche", name)
    return from_niche(settings)
