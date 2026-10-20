"""Word timing: estimate it, transfer it from an aligner onto the script's own words, split the
narration into scenes and caption chunks."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass
class Word:
    text: str
    start: float
    end: float
    speaker: str = "A"


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


def _weight(token: str) -> float:
    """How long a token takes to say, relative to the others: its length, plus a pause after punctuation."""
    w = len(norm(token)) + 2.0
    if token[-1:] in ".!?":
        w += 4.0
    elif token[-1:] in ",;:":
        w += 2.0
    return w


def estimate_timings(tokens: list[str], duration: float, lead: float = 0.05, tail: float = 0.15) -> list[Word]:
    """Spread tokens over ``duration`` by length, with extra time after punctuation (natural pauses)."""
    if not tokens:
        return []
    weights = [_weight(t) for t in tokens]
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


SENTENCE_MARKS, CLAUSE_MARKS = ".!?。！？", ",;:，；：、"


def _anchor(tokens: list[str], weights: list[float], lo: int, hi: int, t0: float, t1: float,
            silences: list[tuple[float, float]], marks: str) -> list[tuple[int, float, float]]:
    """Walk the phrase ends in tokens[lo:hi] and pin each one to the pause in the audio closest to where the
    words before it should end. The prediction restarts from every pinned pause, so errors don't add up."""
    cuts: list[tuple[int, float, float]] = []
    seg_tok, seg_t = lo, t0
    for i in range(lo, hi - 1):
        if tokens[i][-1:] not in marks:
            continue
        rest = sum(weights[seg_tok:hi])
        pred = seg_t + (t1 - seg_t) * sum(weights[seg_tok:i + 1]) / rest
        window = 0.35 * (pred - seg_t) + 0.2
        near = [(a, b) for a, b in silences if seg_t < (a + b) / 2 < t1 and abs((a + b) / 2 - pred) <= window]
        if near:  # closest to the prediction, and a longer pause is a likelier phrase end
            a, b = min(near, key=lambda c: abs((c[0] + c[1]) / 2 - pred) - 0.5 * (c[1] - c[0]))
            cuts.append((i, a, b))
            seg_tok, seg_t = i + 1, b
    return cuts


def anchored_timings(tokens: list[str], duration: float,
                     silences: list[tuple[float, float]]) -> tuple[list[Word], int]:
    """Word times for audio without a word-level timestamp: sentence ends, then clause ends, are pinned to the
    real pauses found in the audio (ffmpeg silencedetect), and only the words between two pauses are
    estimated. Returns the words and how many phrase boundaries were pinned."""
    if not tokens:
        return [], 0
    silences = sorted(silences)
    lead = silences[0][1] if silences and silences[0][0] <= 0.05 else 0.05
    end = silences[-1][0] if silences and silences[-1][1] >= duration - 0.05 else max(lead + 0.1, duration - 0.15)
    inner = [(a, b) for a, b in silences if a > lead + 0.02 and b < end - 0.02]
    weights = [_weight(t) for t in tokens]
    cuts = _anchor(tokens, weights, 0, len(tokens), lead, end, inner, SENTENCE_MARKS)
    bounds = [(-1, lead, lead)] + cuts + [(len(tokens) - 1, end, end)]
    finer: list[tuple[int, float, float]] = []
    for (i0, _, b0), (i1, a1, _) in zip(bounds, bounds[1:]):  # clause pauses inside each sentence
        finer += _anchor(tokens, weights, i0 + 1, i1 + 1, b0, a1, inner, CLAUSE_MARKS)
    cuts = sorted(cuts + finer)
    bounds = [(-1, lead, lead)] + cuts + [(len(tokens) - 1, end, end)]
    words: list[Word] = []
    for (i0, _, b0), (i1, a1, _) in zip(bounds, bounds[1:]):
        part = tokens[i0 + 1:i1 + 1]
        if not part:
            continue
        # The pause after the phrase is already outside [b0, a1], so its last word gets no pause allowance.
        bare = part[:-1] + [part[-1].rstrip(SENTENCE_MARKS + CLAUSE_MARKS) or part[-1]]
        est = estimate_timings(bare, max(0.05, a1 - b0), lead=0.0, tail=0.0)
        words += [Word(tok, round(b0 + w.start, 3), round(b0 + w.end, 3)) for tok, w in zip(part, est)]
        words[-1].end = round(a1, 3)
    return words, len(cuts)


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
    part: int = 0   # shot number inside the scene (long scenes are cut into several shots)

    @property
    def duration(self) -> float:
        return self.end - self.start


def scene_timeline(scene_texts: list[str], words: list[Word], total: float, language: str = "en",
                   starts: list[float] | None = None, min_len: float = 1.2) -> list[SceneTiming]:
    """Scene boundaries follow the voice: scene k starts when its first word is spoken. ``starts`` can
    give them directly (multi-voice audio is made line by line, so the boundaries are exact)."""
    if starts is None:
        counts = [len(tokenize(t, language)) for t in scene_texts]
        starts, idx = [], 0
        for c in counts:
            if idx < len(words):
                starts.append(words[idx].start)
            else:
                starts.append(starts[-1] if starts else 0.0)
            idx += c
    starts = list(starts)
    starts[0] = 0.0
    out = []
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else total
        out.append(SceneTiming(k, s, e))
    # Grow each shot until it lasts at least min_len (too-short scenes can't be read), then start the next;
    # a short final shot joins the one before it.
    merged: list[SceneTiming] = []
    for st in out:
        if merged and merged[-1].duration < min_len:
            merged[-1].end = st.end
        else:
            merged.append(st)
    if len(merged) > 1 and merged[-1].duration < min_len:
        last = merged.pop()
        merged[-1].end = last.end
    return merged


def split_shots(timeline: list[SceneTiming], words: list[Word], max_len: float,
                min_len: float = 1.6) -> list[SceneTiming]:
    """Cut scenes longer than ``max_len`` into shots, the way an editor keeps the picture moving. Each cut
    lands on the start of a spoken word close to the ideal point, preferring the pauses after commas and
    sentence ends, and no shot is shorter than ``min_len``."""
    if max_len <= 0:
        return list(timeline)
    out: list[SceneTiming] = []
    for st in timeline:
        k = math.ceil(st.duration / max_len - 1e-6)
        if k <= 1 or st.duration < 2 * min_len:
            out.append(st)
            continue
        k = min(k, int(st.duration // min_len))
        cands = []  # (time, pause before it)
        for i, w in enumerate(words):
            if st.start + min_len <= w.start <= st.end - min_len:
                cands.append((w.start, w.start - words[i - 1].end if i else 0.0))
        cuts: list[float] = []
        prev = st.start
        for j in range(1, k):
            ideal = st.start + st.duration * j / k
            pool = [c for c in cands if c[0] - prev >= min_len and st.end - c[0] >= min_len * (k - j)]
            if pool:
                t = min(pool, key=lambda c: abs(c[0] - ideal) - min(0.8, 2.0 * max(0.0, c[1])))[0]
            elif not cands and ideal - prev >= min_len:
                t = ideal  # no words to snap to (silence, music): cut evenly
            else:
                continue
            cuts.append(t)
            prev = t
        bounds = [st.start, *cuts, st.end]
        out += [SceneTiming(st.index, a, b, part) for part, (a, b) in enumerate(zip(bounds, bounds[1:]))]
    return out


@dataclass
class Chunk:
    words: list[Word]
    start: float
    end: float

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def speaker(self) -> str:
        return self.words[0].speaker if self.words else "A"


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
            if len(cur) >= max_words or chars > max_chars or gap > 0.45 or w.speaker != cur[-1].speaker:
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
