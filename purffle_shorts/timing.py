"""Word timing: estimate it, transfer it from an aligner onto the script's own words, split the
narration into scenes and caption chunks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass
class Word:
    text: str
    start: float
    end: float


NO_SPACE_LANGS = {"zh", "ja"}


def tokenize(text: str, language: str = "en") -> list[str]:
    """Split narration into caption tokens. Chinese/Japanese have no spaces, so they are cut into
    short character groups at punctuation (timing for those is approximate)."""
    if language.split("-")[0] not in NO_SPACE_LANGS:
        return [t for t in text.split() if t.strip()]
    tokens: list[str] = []
    for part in re.findall(r"[^，。！？、；：,.!?;:\s]+[，。！？、；：,.!?;:]?", text):
        while len(part) > 5:
            tokens.append(part[:4])
            part = part[4:]
        if part:
            tokens.append(part)
    return tokens


def norm(token: str) -> str:
    return re.sub(r"[^\w]", "", token.lower(), flags=re.UNICODE)


def estimate_timings(tokens: list[str], duration: float, lead: float = 0.05, tail: float = 0.15) -> list[Word]:
    """Spread tokens over ``duration`` by length, with extra time after punctuation (natural pauses)."""
    if not tokens:
        return []
    weights = []
    for t in tokens:
        w = len(norm(t)) + 2.0
        if t[-1:] in ".!?":
            w += 4.0
        elif t[-1:] in ",;:":
            w += 2.0
        weights.append(w)
    span = max(0.1, duration - lead - tail)
    scale = span / sum(weights)
    out, t0 = [], lead
    for tok, w in zip(tokens, weights):
        d = w * scale
        pause = 0.0
        if tok[-1:] in ".!?":
            pause = min(4.0 * scale, d * 0.4)
        elif tok[-1:] in ",;:":
            pause = min(2.0 * scale, d * 0.3)
        out.append(Word(tok, round(t0, 3), round(t0 + d - pause, 3)))
        t0 += d
    return out


def transfer_timings(tokens: list[str], timed: list[Word], duration: float) -> list[Word]:
    """Give every script token a time using an aligner's (possibly different) word list.

    Matching is done on normalized text; tokens the aligner missed are interpolated between
    their matched neighbours so captions keep the script's exact wording and punctuation.
    """
    if not tokens:
        return []
    if not timed:
        return estimate_timings(tokens, duration)
    a = [norm(t) for t in tokens]
    b = [norm(w.text) for w in timed]
    starts: list[float | None] = [None] * len(tokens)
    ends: list[float | None] = [None] * len(tokens)
    for block in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(block.size):
            w = timed[block.b + k]
            starts[block.a + k], ends[block.a + k] = w.start, w.end

    # A token like "1,000" may be spoken as several aligner words; anchor unmatched runs between neighbours.
    n = len(tokens)
    i = 0
    while i < n:
        if starts[i] is not None:
            i += 1
            continue
        j = i
        while j < n and starts[j] is None:
            j += 1
        left = ends[i - 1] if i > 0 and ends[i - 1] is not None else 0.0
        right = starts[j] if j < n and starts[j] is not None else max(left, duration - 0.1)
        right = max(right, left + 0.05 * (j - i))
        sub = estimate_timings(tokens[i:j], right - left, lead=0.0, tail=0.0)
        for k, w in enumerate(sub):
            starts[i + k], ends[i + k] = left + w.start, left + w.end
        i = j

    out = []
    prev_start = 0.0
    for tok, s, e in zip(tokens, starts, ends):
        s = max(float(s), prev_start)  # keep starts monotonic even if the aligner jittered
        e = max(float(e), s + 0.04)
        out.append(Word(tok, round(s, 3), round(e, 3)))
        prev_start = s
    return out


@dataclass
class SceneTiming:
    index: int
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def scene_timeline(scene_texts: list[str], words: list[Word], total: float, language: str = "en") -> list[SceneTiming]:
    """Scene boundaries follow the voice: scene k starts when its first word is spoken."""
    counts = [len(tokenize(t, language)) for t in scene_texts]
    starts, idx = [], 0
    for c in counts:
        if idx < len(words):
            starts.append(words[idx].start)
        else:
            starts.append(starts[-1] if starts else 0.0)
        idx += c
    starts[0] = 0.0
    out = []
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else total
        out.append(SceneTiming(k, s, e))
    # Merge scenes that ended up too short to read (< 1.2s) into their neighbour.
    merged: list[SceneTiming] = []
    for st in out:
        if merged and st.duration < 1.2:
            merged[-1].end = st.end
        else:
            merged.append(st)
    if len(merged) > 1 and merged[-1].duration < 1.2:
        last = merged.pop()
        merged[-1].end = last.end
    return merged


@dataclass
class Chunk:
    words: list[Word]
    start: float
    end: float

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


def caption_chunks(words: list[Word], max_words: int = 3, max_chars: int = 20, total: float | None = None) -> list[Chunk]:
    """Group words into short on-screen captions. Breaks at sentence ends, long pauses and length limits."""
    chunks: list[Chunk] = []
    cur: list[Word] = []

    def flush():
        if cur:
            chunks.append(Chunk(list(cur), cur[0].start, cur[-1].end))
            cur.clear()

    for w in words:
        if cur:
            gap = w.start - cur[-1].end
            chars = sum(len(x.text) + 1 for x in cur) + len(w.text)
            if len(cur) >= max_words or chars > max_chars or gap > 0.45:
                flush()
        cur.append(w)
        if w.text[-1:] in ".!?;:" or (w.text[-1:] == "," and len(cur) >= 2):
            flush()
    flush()
    # Each chunk stays on screen until the next one starts (no flicker between words).
    for k in range(len(chunks) - 1):
        nxt = chunks[k + 1].start
        chunks[k].end = nxt if nxt - chunks[k].end < 0.6 else chunks[k].end + 0.25
    if chunks:
        end = chunks[-1].end + 0.4
        chunks[-1].end = min(end, total) if total else end
    return chunks


def srt(chunks: list[Chunk]) -> str:
    def ts(t: float) -> str:
        ms = int(round(t * 1000))
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    lines = []
    for i, c in enumerate(chunks, 1):
        lines += [str(i), f"{ts(c.start)} --> {ts(c.end)}", c.text, ""]
    return "\n".join(lines)
