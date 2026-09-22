"""AI scriptwriting: one LLM call returns the whole Short — hook, scenes with per-scene footage
queries, title, description, hashtags and tags — so everything describes the same video."""

from __future__ import annotations

import logging
import random
import re
from dataclasses import asdict, dataclass, field

from .config import Settings
from .utils import clean_narration, strip_emoji, truncate_words

log = logging.getLogger("purffle")

LANGUAGES = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian", "pt": "Portuguese",
    "hi": "Hindi", "ta": "Tamil", "te": "Telugu", "bn": "Bengali", "mr": "Marathi", "ur": "Urdu",
    "ar": "Arabic", "ru": "Russian", "ja": "Japanese", "ko": "Korean", "zh": "Chinese (Mandarin)",
    "id": "Indonesian", "tr": "Turkish", "nl": "Dutch", "pl": "Polish", "vi": "Vietnamese", "th": "Thai",
    "fil": "Filipino", "uk": "Ukrainian", "sv": "Swedish",
}

STYLES = {
    "facts": "Rapid-fire surprising facts about one specific subject, each one more surprising than the last.",
    "story": "A tight true story: a hook that opens a loop, rising tension, then a satisfying twist or payoff.",
    "listicle": "A top-3 countdown (number 3, number 2, number 1) where number 1 is the most surprising.",
    "myth": "Myth vs. fact: state a belief most people hold, then bust it with clear evidence.",
    "quiz": "Open with a question the viewer will try to answer, build suspense, reveal the answer at the end.",
    "motivational": "A punchy real-life micro-story or principle that ends with a memorable one-line takeaway.",
    "news": "Explain a current story neutrally: what happened, why it matters, what happens next.",
    "explainer": "Explain one idea so a 12-year-old gets it, using one vivid analogy.",
}
AUTO_STYLES = ["facts", "facts", "story", "story", "listicle", "myth", "quiz", "explainer"]

# YouTube video category ids
CATEGORIES = {
    "education": "27", "science": "28", "entertainment": "24", "people": "22", "howto": "26",
    "news": "25", "gaming": "20", "autos": "2", "sports": "17", "travel": "19", "comedy": "23",
    "film": "1", "music": "10", "pets": "15",
}

SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {"type": "string"},
        "title": {"type": "string"},
        "hook_text": {"type": "string"},
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "narration": {"type": "string"},
                    "search_query": {"type": "string"},
                    "image_prompt": {"type": "string"},
                },
                "required": ["narration", "search_query", "image_prompt"],
                "additionalProperties": False,
            },
        },
        "description": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "tags": {"type": "array", "items": {"type": "string"}},
        "category": {"type": "string", "enum": list(CATEGORIES)},
    },
    "required": ["topic", "title", "hook_text", "scenes", "description", "hashtags", "tags", "category"],
    "additionalProperties": False,
}

WORDS_PER_SECOND = 2.6


@dataclass
class Scene:
    narration: str
    search_query: str
    image_prompt: str = ""


@dataclass
class Script:
    topic: str
    title: str
    hook_text: str
    scenes: list[Scene]
    description: str
    hashtags: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    category: str = "education"
    style: str = "facts"
    language: str = "en"

    @property
    def narration(self) -> str:
        return " ".join(s.narration for s in self.scenes)

    @property
    def category_id(self) -> str:
        return CATEGORIES.get(self.category, "27")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Script:
        d = dict(d)
        d["scenes"] = [Scene(**s) for s in d.get("scenes", [])]
        return cls(**d)


def pick_style(settings: Settings, source: str) -> str:
    if settings.style in STYLES:
        return settings.style
    if source == "trending":
        return "news"
    if source in ("wikipedia", "reddit"):
        return "story"
    return random.choice(AUTO_STYLES)


def build_prompt(subject: str, style: str, settings: Settings, avoid: list[str], context: str = "") -> tuple[str, str]:
    lang = LANGUAGES.get(settings.language, settings.language)
    words = int(settings.target_seconds * WORDS_PER_SECOND)
    n_scenes = max(4, min(10, round(settings.target_seconds / 5.5)))
    system = (
        "You are a top YouTube Shorts scriptwriter and editor. You write fast, factual, highly "
        "re-watchable vertical videos. You reply with a single JSON object and nothing else."
    )
    avoid_block = ""
    if avoid:
        avoid_block = "Do NOT repeat any of these recent videos:\n" + "\n".join(f"- {a}" for a in avoid[:40]) + "\n\n"
    ctx = f"Background information (use it, don't invent beyond it):\n{context.strip()}\n\n" if context else ""
    user = f"""Write one YouTube Short.

Subject: {subject}
If the subject is broad, choose ONE specific, surprising, lesser-known topic inside it.
Format: {STYLES[style]}
Audience: {settings.audience}
Language: {lang} for narration, title, hook_text and description. search_query and image_prompt are ALWAYS English.

{ctx}{avoid_block}Rules:
- Total narration about {words} words (~{settings.target_seconds} seconds spoken), split into {n_scenes} scenes of 1-2 short sentences.
- Scene 1 is the hook: a bold claim or question that stops the scroll in under 2 seconds. Never "In this video", never a greeting.
- Every sentence earns its place: concrete details, numbers, names. Only well-established facts; no made-up statistics.
- The last scene lands the payoff, then a short call to action (max 8 words), e.g. asking viewers to comment or follow.
- Narration is spoken by a voice: no emojis, hashtags, labels, brackets or stage directions.
- search_query: 1-4 English words describing concrete, filmable stock footage for that scene (e.g. "octopus underwater", "old library books"). No abstract words.
- image_prompt: one vivid English sentence for an AI image of that scene, no text or letters in the image.
- title: max 60 characters, curiosity-driven but honest, no hashtags, no quotes.
- hook_text: max 6 words shown on screen during the first seconds.
- description: 2-3 sentences plus one question that invites comments. No hashtags.
- hashtags: 3-5 relevant hashtags. tags: 8-15 search keywords.
- category: one of {", ".join(CATEGORIES)}.

Return JSON with keys: topic, title, hook_text, scenes (array of {{narration, search_query, image_prompt}}), description, hashtags, tags, category."""
    return system, user


def _clean_tag(tag: str) -> str:
    return re.sub(r"[<>\"#]", "", strip_emoji(str(tag))).strip()


def _clean_hashtag(tag: str) -> str:
    t = re.sub(r"[^\w]", "", strip_emoji(str(tag)), flags=re.UNICODE)
    return f"#{t}" if t else ""


def normalize(data: dict, subject: str, style: str, language: str) -> Script:
    raw_scenes = data.get("scenes") or []
    scenes: list[Scene] = []
    for s in raw_scenes:
        if isinstance(s, str):
            s = {"narration": s}
        narration = clean_narration(str(s.get("narration", "")))
        if not narration:
            continue
        query = _clean_tag(s.get("search_query") or "") or subject
        scenes.append(Scene(narration=narration, search_query=truncate_words(query, 60),
                            image_prompt=str(s.get("image_prompt") or query).strip()))
    if not scenes:
        raise ValueError("script has no narration")
    while len(scenes) > 12:  # merge the shortest neighbours to keep cuts watchable
        i = min(range(len(scenes) - 1), key=lambda k: len(scenes[k].narration) + len(scenes[k + 1].narration))
        a, b = scenes[i], scenes.pop(i + 1)
        a.narration = f"{a.narration} {b.narration}"

    title = re.sub(r"#\w+", "", strip_emoji(str(data.get("title") or subject)))
    title = re.sub(r"[<>\"“”]", "", title).strip(" '-:")
    title = truncate_words(title or subject.title(), 90)

    hook = re.sub(r"[<>\"“”]", "", strip_emoji(str(data.get("hook_text") or ""))).strip()
    hook = truncate_words(hook, 48) if hook else truncate_words(title, 40)

    hashtags, seen = ["#shorts"], {"#shorts"}
    for h in data.get("hashtags") or []:
        h = _clean_hashtag(h)
        if h and h.lower() not in seen:
            seen.add(h.lower())
            hashtags.append(h)
    hashtags = hashtags[:6]

    tags, total, seen_t = [], 0, set()
    for t in list(data.get("tags") or []) + [subject, "shorts"]:
        t = truncate_words(_clean_tag(t), 60)
        cost = len(t) + (2 if " " in t else 0) + 1
        if t and t.lower() not in seen_t and total + cost <= 450:  # YouTube's tag limit is 500 chars
            seen_t.add(t.lower())
            tags.append(t)
            total += cost

    category = str(data.get("category") or "education").lower()
    if category not in CATEGORIES:
        category = "education"

    description = re.sub(r"(?<!\w)#\w+", "", strip_emoji(str(data.get("description") or ""))).strip()
    return Script(
        topic=str(data.get("topic") or subject).strip(),
        title=title,
        hook_text=hook,
        scenes=scenes,
        description=description,
        hashtags=hashtags,
        tags=tags,
        category=category,
        style=style,
        language=language,
    )


def write_script(llm, subject: str, settings: Settings, *, source: str = "niche",
                 avoid: list[str] | None = None, context: str = "", style: str | None = None) -> Script:
    style = style if style in STYLES else pick_style(settings, source)
    if llm is None:
        return offline_script(subject, settings, style)
    system, user = build_prompt(subject, style, settings, avoid or [], context)
    data = llm.complete_json(system, user, SCRIPT_SCHEMA)
    script = normalize(data, subject, style, settings.language)
    log.info("Script (%s, %d words, %d scenes): %s", style, len(script.narration.split()),
             len(script.scenes), script.title)
    return script


# --------------------------------------------------------------------------------------------------
# Offline writer — lets `demo` produce a real video with no API keys at all.
# --------------------------------------------------------------------------------------------------
_DEMO = {
    "title": "Octopuses Are Basically Aliens",
    "hook_text": "THIS ANIMAL HAS 3 HEARTS",
    "scenes": [
        ("An octopus has three hearts, and one of them stops when it swims.", "octopus swimming"),
        ("Its blood is blue, because it carries oxygen with copper instead of iron.", "blue ocean water"),
        ("Most of its neurons are not in its head. They are spread through its eight arms.", "octopus tentacles"),
        ("Each arm can taste what it touches, using thousands of sensors in its suckers.", "octopus suckers closeup"),
        ("And it changes color in a split second to vanish against the reef.", "coral reef fish"),
        ("Which fact surprised you most? Follow for more.", "deep sea diver"),
    ],
    "description": "Three hearts, blue blood and arms that can taste. The octopus might be the strangest "
                   "animal on Earth. Which fact surprised you most?",
    "hashtags": ["#octopus", "#ocean", "#animals", "#facts"],
    "tags": ["octopus facts", "ocean animals", "marine biology", "weird animals", "animal facts"],
    "category": "education",
}


def offline_script(subject: str, settings: Settings, style: str = "facts") -> Script:
    if not subject or "octopus" in subject.lower() or subject.lower() in {"demo", "random"}:
        d = _DEMO
        data = dict(d, topic="octopus superpowers",
                    scenes=[{"narration": n, "search_query": q, "image_prompt": q} for n, q in d["scenes"]])
        return normalize(data, "octopus superpowers", "facts", "en")
    s = subject.strip()
    lines = [
        f"Most people think they know {s}. They don't.",
        f"The story of {s} is stranger than it looks.",
        "The details surprised even the experts who studied it.",
        "And one small fact changes how you see the whole thing.",
        "Would you have guessed that? Follow for more.",
    ]
    data = {
        "topic": s, "title": f"The Truth About {s.title()}", "hook_text": "YOU WON'T EXPECT THIS",
        "scenes": [{"narration": n, "search_query": s, "image_prompt": s} for n in lines],
        "description": f"A quick look at {s}. What would you add?",
        "hashtags": ["#facts"], "tags": [s, "facts"], "category": "education",
    }
    return normalize(data, s, style, settings.language)
