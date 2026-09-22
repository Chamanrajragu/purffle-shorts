"""Visual sourcing: per-scene stock footage and photos (Pexels, Pixabay), your own media folder,
and AI-generated images (OpenAI gpt-image-1 / DALL·E, Pollinations). Clips are never reused across
videos, portrait footage is preferred, and a scene always gets *something* (animated gradient)."""

from __future__ import annotations

import base64
import concurrent.futures
import logging
import random
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from .config import Settings
from .utils import PermanentError, download, http, raise_for_status, redact, with_retries

log = logging.getLogger("purffle")

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
STOP_WORDS = {"the", "a", "an", "of", "and", "in", "on", "with", "for", "to", "at", "by", "from", "closeup"}


@dataclass
class MediaItem:
    source: str
    id: str
    kind: str                     # video | image | generated
    url: str = ""
    width: int = 0
    height: int = 0
    duration: float = 0.0
    credit: str = ""
    path: Path | None = None
    query: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.id}"

    @property
    def portrait(self) -> bool:
        return self.height > self.width


# ------------------------------------------------------------------------------------------ Pexels
def _pexels_pick_file(files: list[dict], prefer_4k: bool) -> dict | None:
    files = [f for f in files if f.get("link") and f.get("width") and f.get("height")
             and f.get("file_type", "video/mp4") == "video/mp4"]
    if not files:
        return None
    cap = 4096 if prefer_4k else 2160

    def short(f):
        return min(f["width"], f["height"])
    good = [f for f in files if 1080 <= short(f) <= cap]
    if good:
        return min(good, key=short) if not prefer_4k else max(good, key=short)
    return max(files, key=short)


def pexels_videos(query: str, key: str, prefer_4k: bool = False, orientation: str = "portrait") -> list[MediaItem]:
    params = {"query": query, "per_page": 15, "size": "medium"}
    if orientation:
        params["orientation"] = orientation
    r = http().get("https://api.pexels.com/videos/search", params=params, headers={"Authorization": key}, timeout=30)
    raise_for_status(r, "Pexels video search")
    items = []
    for v in r.json().get("videos", []):
        f = _pexels_pick_file(v.get("video_files", []), prefer_4k)
        if not f:
            continue
        items.append(MediaItem("pexels", str(v["id"]), "video", f["link"], f["width"], f["height"],
                               float(v.get("duration") or 0), (v.get("user") or {}).get("name", ""), query=query))
    return items


def pexels_photos(query: str, key: str, orientation: str = "portrait") -> list[MediaItem]:
    params = {"query": query, "per_page": 15}
    if orientation:
        params["orientation"] = orientation
    r = http().get("https://api.pexels.com/v1/search", params=params, headers={"Authorization": key}, timeout=30)
    raise_for_status(r, "Pexels photo search")
    items = []
    for p in r.json().get("photos", []):
        src = p.get("src") or {}
        url = src.get("original")
        if not url:
            continue
        url += ("&" if "?" in url else "?") + "auto=compress&cs=tinysrgb&h=2400"
        items.append(MediaItem("pexels-photo", str(p["id"]), "image", url, p.get("width", 0), p.get("height", 0),
                               credit=p.get("photographer", ""), query=query))
    return items


# ------------------------------------------------------------------------------------------ Pixabay
def pixabay_videos(query: str, key: str, prefer_4k: bool = False) -> list[MediaItem]:
    r = http().get("https://pixabay.com/api/videos/", timeout=30, params={
        "key": key, "q": query[:100], "per_page": 20, "safesearch": "true"})
    raise_for_status(r, "Pixabay video search")
    order = ["large", "medium", "small"] if prefer_4k else ["medium", "large", "small"]
    items = []
    for h in r.json().get("hits", []):
        vids = h.get("videos") or {}
        f = next((vids[q] for q in order if (vids.get(q) or {}).get("url")), None)
        if not f:
            continue
        items.append(MediaItem("pixabay", str(h["id"]), "video", f["url"], f.get("width", 0), f.get("height", 0),
                               float(h.get("duration") or 0), h.get("user", ""), query=query))
    return items


def pixabay_photos(query: str, key: str) -> list[MediaItem]:
    r = http().get("https://pixabay.com/api/", timeout=30, params={
        "key": key, "q": query[:100], "image_type": "photo", "orientation": "vertical",
        "per_page": 20, "safesearch": "true"})
    raise_for_status(r, "Pixabay photo search")
    return [MediaItem("pixabay-photo", str(h["id"]), "image", h["largeImageURL"], h.get("imageWidth", 0),
                      h.get("imageHeight", 0), credit=h.get("user", ""), query=query)
            for h in r.json().get("hits", []) if h.get("largeImageURL")]


# ------------------------------------------------------------------------------------------ AI images
def openai_image(prompt: str, dest: Path, key: str, model: str) -> Path:
    body = {"model": model, "prompt": prompt, "n": 1}
    if model.startswith("dall-e"):
        body.update(size="1024x1792", response_format="b64_json", quality="hd" if model == "dall-e-3" else "standard")
    else:
        body.update(size="1024x1536", quality="medium")

    def _do():
        r = http().post("https://api.openai.com/v1/images/generations", json=body, timeout=240,
                        headers={"Authorization": f"Bearer {key}"})
        raise_for_status(r, "OpenAI image")
        d = r.json()["data"][0]
        if d.get("b64_json"):
            dest.write_bytes(base64.b64decode(d["b64_json"]))
        else:
            download(d["url"], dest)
        return dest

    return with_retries(_do, attempts=2, label="OpenAI image")


_POLLINATIONS_LOCK = threading.Lock()


def pollinations_image(prompt: str, dest: Path, width: int, height: int) -> Path:
    url = (f"https://image.pollinations.ai/prompt/{quote(prompt[:900])}"
           f"?width={width}&height={height}&nologo=true&model=flux&seed={random.randint(1, 10**9)}")
    # Anonymous use allows one queued request per IP; parallel scenes would all get HTTP 429.
    with _POLLINATIONS_LOCK:
        return download(url, dest, timeout=180, max_bytes=30 * 1024 * 1024)


# ------------------------------------------------------------------------------------------ selection
def simplify_query(query: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z]+", query.lower()) if w not in STOP_WORDS]
    return " ".join(words[:2])


def _score(item: MediaItem, need: float) -> float:
    s = 0.0
    if item.portrait:
        s += 3
    if item.kind == "video":
        s += 2 if item.duration >= need else (1 if item.duration >= need * 0.6 else 0)
    if min(item.width, item.height) >= 1080:
        s += 1
    return s + random.uniform(0, 1.5)  # a little variety between similar candidates


class Visuals:
    def __init__(self, settings: Settings, used_keys: set[str] | None = None):
        self.s = settings
        self.used = set(used_keys or ())
        self.lock = threading.Lock()
        self._search_cache: dict[tuple[str, str], list[MediaItem]] = {}
        self.sources = [x for x in settings.visual_sources if x]
        if settings.offline:
            self.sources = ["local"]
        self.credits: set[str] = set()

    # -- search per source (cached per query) --
    def _search(self, source: str, query: str) -> list[MediaItem]:
        ck = (source, query.lower())
        if ck in self._search_cache:
            return self._search_cache[ck]
        s = self.s
        items: list[MediaItem] = []
        try:
            if source == "pexels" and s.pexels_api_key:
                items = pexels_videos(query, s.pexels_api_key, s.prefer_4k)
                if len(items) < 3:
                    items += pexels_videos(query, s.pexels_api_key, s.prefer_4k, orientation="")
                if not items:
                    items = pexels_photos(query, s.pexels_api_key)
            elif source == "pexels-photos" and s.pexels_api_key:
                items = pexels_photos(query, s.pexels_api_key)
            elif source == "pixabay" and s.pixabay_api_key:
                items = pixabay_videos(query, s.pixabay_api_key, s.prefer_4k) or pixabay_photos(query, s.pixabay_api_key)
            elif source == "pixabay-photos" and s.pixabay_api_key:
                items = pixabay_photos(query, s.pixabay_api_key)
            elif source == "local":
                items = self._local(query)
            seen: set[str] = set()
            items = [i for i in items if not (i.key in seen or seen.add(i.key))]
        except PermanentError as e:
            log.warning("%s search failed permanently (%s); disabling it for this video", source, redact(e))
            self.sources = [x for x in self.sources if x != source]
        except Exception as e:
            log.warning("%s search for %r failed: %s", source, query, redact(e))
        self._search_cache[ck] = items
        return items

    def _local(self, query: str) -> list[MediaItem]:
        root = Path(self.s.media_dir)
        if not root.is_dir():
            return []
        words = set(simplify_query(query).split()) | set(query.lower().split())
        items = []
        for p in root.rglob("*"):
            ext = p.suffix.lower()
            if ext not in VIDEO_EXT | IMAGE_EXT:
                continue
            stem = set(re.findall(r"[a-z]+", p.stem.lower()))
            item = MediaItem("local", str(p), "video" if ext in VIDEO_EXT else "image", path=p, query=query)
            item.extra["overlap"] = len(words & stem)
            items.append(item)
        items.sort(key=lambda i: i.extra["overlap"], reverse=True)
        return items

    def _claim(self, candidates: list[MediaItem], need: float) -> MediaItem | None:
        with self.lock:
            fresh = [c for c in candidates if c.key not in self.used]
            if not fresh:
                return None
            if fresh[0].source == "local":
                best = fresh[0] if fresh[0].extra.get("overlap") else random.choice(fresh)
            else:
                best = max(fresh, key=lambda c: _score(c, need))
            self.used.add(best.key)
            return best

    def _fetch(self, item: MediaItem, dest_dir: Path, idx: int) -> MediaItem:
        if item.source == "local":
            return item
        ext = ".mp4" if item.kind == "video" else ".jpg"
        item.path = download(item.url, dest_dir / f"scene{idx:02d}_{item.source}_{item.id}{ext}")
        return item

    def _ai(self, source: str, prompt: str, dest_dir: Path, idx: int) -> MediaItem | None:
        s = self.s
        full = f"{prompt}. {s.visual_style}. No text, no letters, no watermark."
        dest = dest_dir / f"scene{idx:02d}_ai.png"
        try:
            if source in ("openai-images", "ai", "dalle", "gpt-image") and s.openai_api_key:
                openai_image(full, dest, s.openai_api_key, s.image_model)
            elif source == "pollinations":
                pollinations_image(full, dest.with_suffix(".jpg"), s.width, s.height)
                dest = dest.with_suffix(".jpg")
            else:
                return None
        except Exception as e:
            log.warning("AI image (%s) for scene %d failed: %s", source, idx + 1, redact(e))
            return None
        log.info("Scene %d: %s image", idx + 1, source)
        return MediaItem(source, dest.name, "image", path=dest, width=s.width, height=s.height, query=prompt)

    def for_scene(self, idx: int, query: str, image_prompt: str, topic: str, need: float, dest_dir: Path) -> MediaItem:
        queries = []
        for q in (query, simplify_query(query), simplify_query(topic), topic):
            q = (q or "").strip()
            if q and q.lower() not in [x.lower() for x in queries]:
                queries.append(q)
        for source in list(self.sources):
            if source in ("openai-images", "ai", "dalle", "gpt-image", "pollinations"):
                item = self._ai(source, image_prompt or query, dest_dir, idx)
                if item:
                    return item
                continue
            for q in queries:
                cand = self._search(source, q)
                item = self._claim(cand, need)
                if not item:
                    continue
                try:
                    self._fetch(item, dest_dir, idx)
                except Exception as e:
                    log.warning("Download failed for %s: %s", item.key, redact(e))
                    continue
                if item.source.startswith("pexels"):
                    self.credits.add("Pexels")
                elif item.source.startswith("pixabay"):
                    self.credits.add("Pixabay")
                log.info("Scene %d: %s %s (%r)", idx + 1, item.source, item.kind, q)
                return item
        log.info("Scene %d: no footage found for %r — using an animated background", idx + 1, query)
        return MediaItem("generated", f"gradient-{idx}", "generated", query=query)

    def for_scenes(self, jobs: list[tuple[str, str, float]], topic: str, dest_dir: Path) -> list[MediaItem]:
        """jobs: [(search_query, image_prompt, seconds_needed)] -> one MediaItem per scene."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        workers = 2 if any(s in ("openai-images", "ai", "pollinations") for s in self.sources) else 4
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(self.for_scene, i, q, p, topic, need, dest_dir) for i, (q, p, need) in enumerate(jobs)]
            return [f.result() for f in futs]
