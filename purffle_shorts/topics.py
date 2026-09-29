"""Where video ideas come from. Mix sources with TOPIC_SOURCES, optionally weighted:
TOPIC_SOURCES=niche:4,trending:1,wikipedia:1

  niche      the AI picks a fresh, specific topic inside one of your NICHES (default)
  trending   today's Google Trends searches for TRENDS_GEO (tragedies and elections are skipped)
  wikipedia  "On this day" historical events
  reddit     r/todayilearned top posts of the day
  file       your own list: one topic per line in topics.txt (each used once)
  rss        the newest unused item from your RSS_FEEDS (blogs, news sites, podcasts)

Ideas saved by the planner (`plan` command or the Studio's Ideas page) are always used first.
A single video can also be made from a web page (--url) or a local text/markdown file (--from-file).
"""

from __future__ import annotations

import html
import logging
import random
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
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
    style: str = ""
    idea_id: int | None = None


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


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def from_rss(settings: Settings, history: History) -> Topic | None:
    feeds = list(settings.rss_feeds)
    random.shuffle(feeds)
    for url in feeds:
        try:
            r = http().get(url, timeout=20)
            raise_for_status(r, f"RSS {url[:60]}")
            root = ET.fromstring(r.content)
        except Exception as e:
            log.warning("RSS feed %s failed: %s", url, e)
            continue
        atom = "{http://www.w3.org/2005/Atom}"
        entries = list(root.iter("item")) or list(root.iter(f"{atom}entry"))
        for e in entries:
            title = _strip_html(e.findtext("title") or e.findtext(f"{atom}title") or "")
            summary = _strip_html(e.findtext("description") or e.findtext(f"{atom}summary")
                                  or e.findtext(f"{atom}content") or "")
            link = (e.findtext("link") or "").strip()
            if not link:
                el = e.find(f"{atom}link")
                link = el.get("href", "") if el is not None else ""
            key = f"rss:{link or title}"
            if not title or history.topic_used(key) or SENSITIVE.search(f"{title} {summary}"):
                continue
            return Topic(title, "rss", key=key, context=summary[:2500])
    return None


class _TextExtractor(HTMLParser):
    """Readable text from an article page: headings, paragraphs and list items, minus navigation."""

    SKIP = {"script", "style", "nav", "footer", "header", "aside", "form", "noscript", "svg", "button"}
    KEEP = {"p", "h1", "h2", "h3", "li", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self.meta_title = ""
        self._skip = 0
        self._keep = 0
        self._in_title = False
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.KEEP:
            self._keep += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            a = dict(attrs)
            if a.get("property") == "og:title" and a.get("content"):
                self.meta_title = a["content"]

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in self.KEEP and self._keep:
            self._keep -= 1
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            self._buf = []
            if len(text) > 30 or tag.startswith("h"):
                self.parts.append(text)
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self._keep and not self._skip:
            self._buf.append(data)


def extract_article(page: str) -> tuple[str, str]:
    """(title, text) from an HTML page."""
    p = _TextExtractor()
    p.feed(page)
    title = (p.meta_title or p.title).strip()
    title = re.split(r"\s+[|–—-]\s+", title)[0].strip() if title else ""
    return title, "\n".join(dict.fromkeys(t for t in p.parts if t))


def from_url(url: str) -> Topic:
    """Turn a web page (article, blog post, docs page, Wikipedia) into a topic with the page as context."""
    if not re.match(r"^https?://", url):
        raise ValueError(f"not a web address: {url}")
    r = http().get(url, timeout=30, headers={"Accept": "text/html,application/xhtml+xml"})
    raise_for_status(r, f"fetch {url[:60]}")
    title, text = extract_article(r.text)
    if len(text) < 200:
        raise ValueError(f"{url}: couldn't find readable article text on that page")
    return Topic(title or url, "url", key=f"url:{url}", context=text[:6000])


def from_document(path: str | Path) -> Topic:
    """A local .txt / .md file (notes, a blog draft, a transcript) as the source of a video."""
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    if p.suffix.lower() in (".html", ".htm"):
        title, text = extract_article(text)
    else:
        first = next((ln.strip("# ").strip() for ln in text.splitlines() if ln.strip()), "")
        title = first[:90]
    if len(text.strip()) < 40:
        raise ValueError(f"{p}: not enough text to make a video from")
    return Topic(title or p.stem, "document", key=f"doc:{p.name}", context=text[:6000])


def pick_topic(settings: Settings, history: History, explicit: str | None = None,
               source: str | None = None) -> Topic:
    if explicit:
        return Topic(explicit, "manual")
    if settings.offline:
        return Topic("octopus superpowers", "manual")
    if source in (None, "queue"):
        idea = history.claim_idea()
        if idea:
            angle = (idea.get("notes") or "").strip()
            subject = f'{idea["subject"]} (angle: {angle})' if angle else idea["subject"]
            return Topic(subject, "idea", key=f'idea:{idea["id"]}', style=idea.get("style") or "",
                         idea_id=idea["id"])
        if source == "queue":
            log.info("The idea queue is empty; using a niche topic")
            return from_niche(settings)
    choices = [(source, 1.0)] if source else _weighted_sources(settings)
    names, weights = zip(*choices)
    name = random.choices(names, weights=weights, k=1)[0] if sum(weights) > 0 else "niche"
    fetch = {"file": from_file, "trending": from_trends, "wikipedia": from_wikipedia, "reddit": from_reddit,
             "rss": from_rss}
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
