"""Search demand from YouTube's own search box. The suggestions YouTube shows while someone types are the
phrases people actually search for, ranked by how often. They are used three ways:

  * as a topic source (TOPIC_SOURCES=search): questions people ask about one of your niches, such as
    "why do octopuses have three hearts"; the script writer answers the one that fits best;
  * as keywords for the script writer (SEO_KEYWORDS, on by default): the title, description and tags can
    use the exact words people search with, instead of the LLM's guess at them;
  * as inspiration for the content planner (`plan`).

No key is needed. Every call is best effort: if suggestions are unavailable, nothing else changes.
"""

from __future__ import annotations

import logging
import random
import re

from .utils import http

log = logging.getLogger("purffle")

SUGGEST_URL = "https://suggestqueries.google.com/complete/search"
# Suggestions that are about a kind of video, not about the subject itself
OFF_TOPIC = re.compile(
    r"\b(in (hindi|tamil|telugu|urdu|bangla|bengali|marathi|english)|for kids|drawing|draw|song|songs|lyrics|"
    r"podcast|documentary|full movie|movie|episode|edit|edits|meme|memes|tiktok|shorts|status|reaction|"
    r"asmr|minecraft|roblox|fortnite|gta|live stream|livestream|trailer|ppt|pdf|class \d+|fancy dress|"
    r"crochet|joe rogan|mukbang)\b", re.I)
ADULT = re.compile(r"\b(sex\w*|porn\w*|nude\w*|nsfw|xxx|onlyfans|hentai|boobs?|strip club|gaydar|"
                   r"18\+)", re.I)
QUESTION = re.compile(r"^(why|how|what|when|where|who|which|can|do|does|did|is|are|was|were|will|should)\b", re.I)
GENERIC = {"facts", "fact", "mind", "blowing", "mind-blowing", "strange", "but", "true", "and", "the", "of",
           "tips", "stories", "story", "things", "about", "around", "world", "weird", "famous", "amazing",
           "interesting", "random", "cool", "fun", "best", "top", "for", "with", "how", "why", "what"}
QUESTION_STARTS = ("why do", "why is", "how do", "how does", "what if", "what happens when")


def suggestions(query: str, language: str = "en", geo: str = "US", timeout: float = 6.0) -> list[str]:
    """What YouTube's search box suggests for ``query``, most searched first. [] when unavailable."""
    q = query.strip()
    if not q:
        return []
    try:
        r = http().get(SUGGEST_URL, params={"client": "firefox", "ds": "yt", "hl": language.split("-")[0],
                                            "gl": geo or "US", "q": q}, timeout=timeout)
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception as e:
        log.debug("YouTube suggestions for %r unavailable: %s", q, e)
        return []
    items = data[1] if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list) else []
    return [s.strip() for s in items if isinstance(s, str) and s.strip()]


def _clean(phrase: str) -> str:
    return re.sub(r"\s+", " ", phrase.lower()).strip(" ?!.,")


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[^\W\d_][\w'-]*", text.lower()) if w not in GENERIC and len(w) > 2]


def _stems(text: str) -> set[str]:
    from .media import _stem
    return {_stem(w) for w in _words(text)}


def _shares(phrase: str, subject_stems: set[str], need: int) -> bool:
    """The phrase contains at least ``need`` of the subject's words as whole words ("body" matches
    "bodies", never "bodybuilders")."""
    return len(_stems(phrase) & subject_stems) >= need


def usable(phrase: str) -> bool:
    """A suggestion that could be a video's subject: 2-12 words, about the thing itself."""
    from .topics import SENSITIVE
    n = len(phrase.split())
    return 2 <= n <= 12 and not (OFF_TOPIC.search(phrase) or SENSITIVE.search(phrase) or ADULT.search(phrase))


def search_phrases(subject: str, language: str = "en", geo: str = "US", limit: int = 8) -> list[str]:
    """Real YouTube searches about ``subject``: what people type after it, and the questions they ask
    about its main word. Most searched first, without duplicates or off-topic ones."""
    core = " ".join(subject.split()[:6])
    seeds = [core]
    words = _words(core)
    if words and language.split("-")[0] == "en":
        seeds += [f"{start} {words[0]}" for start in ("why do", "why is", "how do")]
    stems = _stems(core)
    need = min(2, len(stems))  # a search about "space marines" is not about "space and the universe"
    out: list[str] = []
    for seed in seeds:
        for s in suggestions(seed, language, geo):
            p = _clean(s)
            if p and p != _clean(seed) and usable(p) and _shares(p, stems, need) and p not in out:
                out.append(p)
        if len(out) >= limit:
            break
    return out[:limit]


def question_topics(niche: str, used, language: str = "en", geo: str = "US", limit: int = 8) -> list[str]:
    """Questions people search for about ``niche`` that ``used(phrase)`` says haven't been made yet. Ranked
    by how many of the niche's words they share, then by its first word (usually the subject: "ocean" in
    "ocean mysteries"). Questions make the best Shorts: the video is the answer. Autocomplete can't tell
    "space" the universe from "space marines", so the script writer is shown several and picks one."""
    words = _words(niche)
    if not words:
        return []
    stems = _stems(niche)
    main = _stems(words[0])
    seeds: list[tuple[str, str]] = []
    for w in words[:2]:
        starts = list(QUESTION_STARTS)
        random.shuffle(starts)
        seeds += [(f"{start} {w}", w) for start in starts[:4]]
    scored: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for n, (seed, word) in enumerate(seeds):
        taken = 0
        for s in suggestions(seed, language, geo):
            p = _clean(s)
            if (taken < 3 and p not in seen and QUESTION.match(p) and len(p.split()) >= 4 and usable(p)
                    and _shares(p, _stems(word), 1) and not used(p)):
                seen.add(p)
                taken += 1
                score = 2 * len(_stems(p) & stems) + (1 if _stems(p) & main else 0)
                scored.append((-score, n, p))
    return [p for _, _, p in sorted(scored)[:limit]]


def keywords_block(phrases: list[str]) -> str:
    """The prompt section that hands real searches to the script writer."""
    if not phrases:
        return ""
    lines = "\n".join(f"- {p}" for p in phrases)
    return ("Real searches people type into YouTube about this subject (most searched first):\n"
            f"{lines}\n"
            "Where one matches the video you write, use its exact words naturally in the title or the first "
            "sentence of the description, and add the matching ones as tags. Never force one that doesn't fit.")
