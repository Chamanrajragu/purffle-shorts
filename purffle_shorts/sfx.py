"""Sound design: short effects synthesised on the fly and mixed under the voice. A whoosh rides each
scene transition, a soft pop lands with each text message, and a low hit marks the hook title.

Everything is generated from noise and sine waves, so there are no sound files to download or license,
and the same effect never sounds exactly the same twice."""

from __future__ import annotations

import math
import random
import wave
from array import array
from pathlib import Path

RATE = 48000
PEAK = 0.5         # each effect peaks at -6 dBFS before SFX_VOLUME; the voice sits well above it

# Where each effect is loudest, in seconds from its start: placed so that moment lands on the event.
ATTACK = {"whoosh": 0.22, "pop": 0.004, "hit": 0.006}


def _normalise(x: list[float], peak: float = PEAK) -> list[float]:
    m = max((abs(v) for v in x), default=0.0)
    return [v * peak / m for v in x] if m > 0 else x


def whoosh(seconds: float = 0.5, rng: random.Random | None = None) -> list[float]:
    """Air rushing past: noise through a band-pass whose centre sweeps up and back down while the level
    swells and fades (a state-variable filter, retuned every sample)."""
    rng = rng or random.Random()
    n = int(seconds * RATE)
    lo, top = rng.uniform(280, 420), rng.uniform(2200, 3200)
    peak_at = ATTACK["whoosh"] / seconds
    low = band = 0.0
    q = 0.55                      # damping: lower = narrower, more "whistly" band
    out = []
    for i in range(n):
        p = i / n
        # frequency rises to the peak, then falls to a little above where it started
        sweep = p / peak_at if p < peak_at else 1 - (p - peak_at) / (1 - peak_at) * 0.85
        fc = lo + (top - lo) * sweep * sweep
        f = 2 * math.sin(math.pi * fc / RATE)
        x = rng.uniform(-1.0, 1.0)
        low += f * band
        high = x - low - q * band
        band += f * high
        env = (math.sin(0.5 * math.pi * p / peak_at) ** 2 if p < peak_at
               else math.exp(-4.5 * (p - peak_at) / (1 - peak_at)))
        out.append(band * env)
    return _normalise(out)


def pop(seconds: float = 0.09, rng: random.Random | None = None) -> list[float]:
    """A bubble pop for a message landing: a sine whose pitch drops fast, with a tiny click on top."""
    rng = rng or random.Random()
    n = int(seconds * RATE)
    f0, f1 = rng.uniform(1250, 1500), rng.uniform(330, 420)
    phase, out = 0.0, []
    for i in range(n):
        t = i / RATE
        fc = f1 + (f0 - f1) * math.exp(-t / 0.012)
        phase += 2 * math.pi * fc / RATE
        env = math.exp(-t / 0.022)
        click = rng.uniform(-0.3, 0.3) * math.exp(-t / 0.0015)
        out.append(math.sin(phase) * env + click)
    return _normalise(out, PEAK * 0.8)


def hit(seconds: float = 0.65, rng: random.Random | None = None) -> list[float]:
    """A low cinematic hit for the hook: a sub-bass drop under a short burst of dark noise."""
    rng = rng or random.Random()
    n = int(seconds * RATE)
    f0, f1 = rng.uniform(140, 170), rng.uniform(55, 65)   # high enough to be felt on a phone speaker
    phase, low, out = 0.0, 0.0, []
    a = 1 - math.exp(-2 * math.pi * 900 / RATE)   # one-pole low-pass for the noise
    for i in range(n):
        t = i / RATE
        fc = f1 + (f0 - f1) * math.exp(-t / 0.06)
        phase += 2 * math.pi * fc / RATE
        body = math.sin(phase) * math.exp(-t / 0.22)
        low += a * (rng.uniform(-1.0, 1.0) - low)
        burst = low * 1.8 * math.exp(-t / 0.035)
        out.append(body + burst)
    return _normalise(out)


SOUNDS = {"whoosh": whoosh, "pop": pop, "hit": hit}


def track(events: list[tuple[float, str]], total: float, dest: Path, *, volume: float = 1.0,
          seed: int | None = None) -> Path | None:
    """A mono WAV ``total`` seconds long with each (time, sound) event placed so that its loudest moment
    lands on ``time``. None when there is nothing to play."""
    events = [(t, k) for t, k in events if k in SOUNDS and 0 <= t < total]
    if not events or volume <= 0:
        return None
    rng = random.Random(seed)
    n = int(total * RATE)
    pcm = array("h", bytes(2 * n))  # silence; only the samples under an effect are touched
    gain = 32767 * volume
    for t, kind in sorted(events):
        sound = SOUNDS[kind](rng=rng)
        start = int((t - ATTACK[kind]) * RATE)
        for j, v in enumerate(sound[max(0, -start):], start=max(0, start)):
            if j >= n:
                break
            pcm[j] = max(-32767, min(32767, pcm[j] + int(v * gain)))
    dest.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    return dest


def events_for(*, scene_starts: list[float], message_starts: list[float] | None = None, hook: bool = False,
               min_gap: float = 1.2) -> list[tuple[float, str]]:
    """Which effect goes where: a hit under the hook, a pop per text message, a whoosh per scene change
    (thinned out so quick cuts don't turn into a constant rush of air)."""
    ev: list[tuple[float, str]] = []
    if hook:
        ev.append((0.05, "hit"))
    if message_starts:
        ev += [(t, "pop") for t in message_starts]
        return ev
    last = -9.0
    for t in scene_starts:
        if t - last >= min_gap:
            ev.append((t, "whoosh"))
            last = t
    return ev
