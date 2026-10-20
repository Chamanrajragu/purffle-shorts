"""The channel learning loop: format choice from real views (Thompson sampling) and score calibration."""

import random
from datetime import datetime, timedelta, timezone

from purffle_shorts import analytics as A
from purffle_shorts.history import History


def _history(tmp_path, rows):
    """rows: [(style, views, score, hours_ago_published)]"""
    h = History(tmp_path / "h.db")
    for i, (style, views, score, age) in enumerate(rows):
        when = (datetime.now(timezone.utc) - timedelta(hours=age)).isoformat(timespec="seconds")
        rid = h.add_video(title=f"v{i}", style=style, status="uploaded", score=score, youtube_id=f"y{i}",
                          uploaded_at=when)
        h.set_stats(f"y{i}", views, views // 20, views // 100)
        assert h.get(rid)["views"] == views
    return h


def test_no_learning_until_there_is_enough_data(tmp_path):
    h = _history(tmp_path, [("facts", 1000, 70, 100)] * 3)
    assert A.choose_style(h, ["facts", "quiz"]) is None


def test_the_format_that_works_is_chosen_most_but_others_still_get_tried(tmp_path):
    rows = [("quiz", v, 70, 100) for v in (40_000, 55_000, 38_000, 61_000, 47_000)]
    rows += [("facts", v, 70, 100) for v in (900, 1_400, 700, 1_100, 1_000)]
    h = _history(tmp_path, rows)
    rng = random.Random(7)
    picks = [A.choose_style(h, ["facts", "quiz", "story"], rng) for _ in range(400)]
    assert picks.count("quiz") > 0.6 * len(picks)
    assert picks.count("facts") < picks.count("story")   # proven weak < untried
    assert picks.count("story") > 0                      # an untried format still gets explored


def test_videos_too_new_to_judge_are_ignored(tmp_path):
    h = _history(tmp_path, [("quiz", 50_000, 70, 3)] * 10)  # three hours old
    assert A.choose_style(h, ["quiz", "facts"]) is None


def test_spearman():
    assert A.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert A.spearman([1, 2, 3, 4], [9, 7, 5, 1]) == -1.0
    assert A.spearman([1, 1, 2, 3], [5, 5, 6, 7]) == 1.0  # ties share ranks
    assert A.spearman([1, 2], [1, 2]) is None
    assert A.spearman([3, 3, 3], [1, 2, 3]) is None       # no variation in x


def test_calibration_says_whether_the_score_predicts_views(tmp_path):
    rows = [("facts", 1000 * s, s, 100) for s in (55, 60, 70, 80, 90, 65)]
    cal = A.calibration(_history(tmp_path, rows))
    assert cal["score_vs_views"] == 1.0 and "predicts views well" in cal["verdict"]
    assert cal["styles"][0]["style"] == "facts" and cal["scored"] == 6
    assert cal["hours"] and cal["hours"][0]["videos"] >= 2


def test_calibration_with_too_little_data(tmp_path):
    cal = A.calibration(_history(tmp_path, [("quiz", 10, 50, 100)]))
    assert cal["score_vs_views"] is None and "at least 5" in cal["verdict"]
