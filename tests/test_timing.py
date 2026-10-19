from purffle_shorts.timing import (
    SceneTiming,
    Word,
    anchored_timings,
    caption_chunks,
    estimate_timings,
    scene_timeline,
    split_shots,
    srt,
    tokenize,
    transfer_timings,
)


def test_estimate_timings_monotonic_and_bounded():
    words = estimate_timings(["Did", "you", "know?", "Octopuses", "have", "three", "hearts."], 3.0)
    assert len(words) == 7
    assert words[0].start >= 0 and words[-1].end <= 3.0
    assert all(a.start <= b.start for a, b in zip(words, words[1:]))
    assert all(w.end > w.start for w in words)


def test_transfer_keeps_script_words_and_fills_gaps():
    tokens = ["Hello,", "world!", "It", "has", "1,000", "cats."]
    timed = [Word("Hello", 0.0, 0.3), Word("world", 0.35, 0.7), Word("It", 0.9, 1.0), Word("has", 1.0, 1.2),
             Word("one", 1.25, 1.4), Word("thousand", 1.4, 1.8), Word("cats", 1.85, 2.2)]
    out = transfer_timings(tokens, timed, 2.5)
    assert [w.text for w in out] == tokens
    assert out[0].start == 0.0 and out[1].start == 0.35
    assert out[3].end <= out[4].start <= out[5].start == 1.85
    assert all(a.start <= b.start for a, b in zip(out, out[1:]))


def test_transfer_without_aligner_estimates():
    out = transfer_timings(["a", "b", "c"], [], 1.5)
    assert len(out) == 3 and out[-1].end <= 1.5


def test_scene_timeline_follows_voice():
    scenes = ["One two three.", "Four five.", "Six seven eight nine."]
    words = [Word(t, i * 0.7, i * 0.7 + 0.5) for i, t in enumerate(" ".join(scenes).split())]
    tl = scene_timeline(scenes, words, total=8.0)
    assert [round(s.start, 2) for s in tl] == [0.0, 2.1, 3.5]
    assert tl[-1].end == 8.0


def test_scene_timeline_merges_tiny_scenes():
    scenes = ["One two three four five.", "Six.", "Seven eight nine ten eleven twelve."]
    words = [Word(t, i * 0.4, i * 0.4 + 0.3) for i, t in enumerate(" ".join(scenes).split())]
    tl = scene_timeline(scenes, words, total=6.0)
    assert len(tl) == 2 and all(s.duration >= 1.2 for s in tl)


def test_caption_chunks_break_on_punctuation_and_limits():
    words = estimate_timings("An octopus has three hearts. Its blood is blue.".split(), 4.0)
    chunks = caption_chunks(words, max_words=3)
    assert all(len(c.words) <= 3 for c in chunks)
    assert any(c.text.endswith("hearts.") for c in chunks)
    for a, b in zip(chunks, chunks[1:]):
        assert a.end <= b.start + 1e-6


def test_tokenize_no_space_languages():
    toks = tokenize("章鱼有三颗心脏。它的血液是蓝色的！", "zh")
    assert len(toks) >= 4 and all(len(t) <= 5 for t in toks)
    assert tokenize("hello  world", "en") == ["hello", "world"]


def test_srt_format():
    text = srt(caption_chunks([Word("Hi", 0.0, 0.5), Word("there.", 0.5, 1.0)], max_words=3))
    assert text.startswith("1\n00:00:00,000 --> 00:00:01,")


def _words(spec):
    """[(text, start, end), ...] -> Words"""
    return [Word(t, a, b) for t, a, b in spec]


def test_split_shots_cuts_long_scenes_on_pauses():
    # A 9-second scene with a clear pause (after "reef,") near the middle.
    words = _words([("It", 0.0, 0.3), ("hides", 0.4, 0.9), ("in", 1.0, 1.2), ("plain", 1.3, 1.8), ("sight", 1.9, 2.4),
                    ("on", 2.5, 2.7), ("the", 2.8, 3.0), ("reef,", 3.1, 3.7), ("changing", 4.4, 5.0),
                    ("colour", 5.1, 5.6), ("in", 5.7, 5.9), ("under", 6.0, 6.4), ("a", 6.5, 6.6),
                    ("second.", 6.7, 8.6)])
    shots = split_shots([SceneTiming(0, 0.0, 9.0)], words, max_len=4.5)
    assert [s.part for s in shots] == [0, 1]
    assert shots[0].start == 0.0 and shots[-1].end == 9.0
    assert shots[0].end == shots[1].start == 4.4  # the word after the pause, not the exact middle (4.5)
    assert all(s.index == 0 for s in shots)


def test_split_shots_respects_min_length_and_short_scenes():
    words = _words([(f"w{i}", i * 0.5, i * 0.5 + 0.4) for i in range(30)])
    shots = split_shots([SceneTiming(0, 0.0, 3.0), SceneTiming(1, 3.0, 15.0)], words, max_len=4.0, min_len=1.6)
    assert shots[0] == SceneTiming(0, 0.0, 3.0)          # short scene untouched
    rest = shots[1:]
    assert len(rest) == 3 and rest[0].start == 3.0 and rest[-1].end == 15.0
    assert all(s.duration >= 1.6 for s in rest)
    assert all(a.end == b.start for a, b in zip(rest, rest[1:]))
    assert split_shots([SceneTiming(0, 0.0, 12.0)], words, max_len=0) == [SceneTiming(0, 0.0, 12.0)]


def test_split_shots_without_words_cuts_evenly():
    shots = split_shots([SceneTiming(0, 0.0, 10.0)], [], max_len=4.0)
    assert [round(s.end, 3) for s in shots] == [3.333, 6.667, 10.0]


TEXT = "Octopuses have three hearts. And their blood is blue, because of copper. Follow for more."
PAUSES = [(0.0, 0.3), (2.1, 2.55), (4.9, 5.05), (6.2, 6.8), (8.2, 9.0)]


def test_anchored_timings_pin_phrase_ends_to_pauses():
    toks = tokenize(TEXT)
    words, pinned = anchored_timings(toks, 9.0, PAUSES)
    assert pinned == 3 and [w.text for w in words] == toks
    by = {w.text: w for w in words}
    assert words[0].start == 0.3 and by["hearts."].end == 2.1 and by["And"].start == 2.55
    assert by["blue,"].end == 4.9 and by["because"].start == 5.05
    assert by["copper."].end == 6.2 and by["Follow"].start == 6.8 and words[-1].end == 8.2
    assert all(a.end <= b.start + 1e-6 for a, b in zip(words, words[1:]))


def test_anchored_timings_ignore_pauses_that_dont_fit():
    toks = tokenize("One two three, four five six. Seven eight nine.")
    # a breath in the middle of the first clause, and no pause at the comma
    words, pinned = anchored_timings(toks, 6.0, [(0.0, 0.2), (0.7, 0.85), (3.3, 3.7), (5.8, 6.0)])
    assert pinned == 1  # only the sentence end
    assert next(w for w in words if w.text == "six.").end == 3.3
    assert all(w.end > w.start for w in words) and words[-1].end <= 6.0
    assert all(a.start <= b.start for a, b in zip(words, words[1:]))


def test_anchored_timings_without_pauses_is_an_estimate():
    toks = tokenize("Just one sentence with no pauses at all.")
    words, pinned = anchored_timings(toks, 3.0, [])
    assert pinned == 0 and len(words) == len(toks) and words[-1].end <= 3.0
