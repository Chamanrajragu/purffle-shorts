"""Presets, batches and the Studio's autopilot."""

import json
from datetime import datetime

import pytest

from purffle_shorts import autopilot as AP
from purffle_shorts import presets as P
from tests.test_studio import req, server  # noqa: F401  (pytest fixture)


class Meta:
    def __init__(self):
        self.d = {}

    def get_meta(self, k):
        return self.d.get(k)

    def set_meta(self, k, v):
        self.d[k] = v


# ------------------------------------------------------------------ presets
def test_clean_form_keeps_only_known_plain_fields():
    out = P.clean_form({"style": "facts", "duration": 45, "music": False, "visuals": ["pexels"] * 20,
                        "topic": "not kept", "voice": "x" * 999, "grade": {"evil": 1}})
    assert out == {"style": "facts", "duration": 45, "music": False, "visuals": ["pexels"] * 8, "voice": "x" * 300}


def test_presets_save_load_delete_and_limits():
    h = Meta()
    assert P.load(h) == {}
    P.save(h, "  Space   facts ", {"style": "facts"})
    assert P.load(h) == {"Space facts": {"style": "facts"}}
    with pytest.raises(ValueError):
        P.save(h, "   ", {})
    for n in range(P.MAX_PRESETS - 1):
        P.save(h, f"p{n}", {})
    with pytest.raises(ValueError):
        P.save(h, "one too many", {})
    P.save(h, "Space facts", {"style": "story"})  # overwriting is always allowed
    assert P.load(h)["Space facts"] == {"style": "story"}
    assert "Space facts" not in P.delete(h, "Space facts")
    h.d[P.META_KEY] = "not json"
    assert P.load(h) == {}


# ------------------------------------------------------------------ autopilot
def ts(y, mo, d, hh=0, mm=0):
    return datetime(y, mo, d, hh, mm).timestamp()


def test_autopilot_update_clamps_and_validates():
    h = Meta()
    st = AP.update(h, {"on": True, "every_hours": 0.01, "per_day": 999, "upload": True, "preset": "  A  b "})
    assert (st["on"], st["every_hours"], st["per_day"], st["upload"], st["preset"]) == (True, 0.5, 48, True, "A b")
    with pytest.raises(ValueError):
        AP.update(h, {"every_hours": "soon"})
    with pytest.raises(ValueError):
        AP.update(h, {"per_day": None})


def test_autopilot_schedule_and_daily_cap():
    h = Meta()
    noon = ts(2026, 11, 14, 12)
    assert AP.next_at(AP.load(h), noon) is None                       # off
    AP.update(h, {"on": True, "every_hours": 2, "per_day": 2})
    st = AP.load(h)
    assert AP.due(st, busy=False, now=noon) and not AP.due(st, busy=True, now=noon)
    AP.mark_started(h, noon)
    st = AP.load(h)
    assert AP.made_today(st, noon) == 1
    assert AP.next_at(st, noon) == noon + 2 * 3600
    assert not AP.due(st, False, noon + 3600) and AP.due(st, False, noon + 2 * 3600)
    AP.mark_started(h, noon + 2 * 3600)
    st = AP.load(h)                                                    # cap of 2 reached: wait for tomorrow
    assert AP.next_at(st, noon + 5 * 3600) == ts(2026, 11, 15)
    assert AP.made_today(st, ts(2026, 11, 15, 1)) == 0
    pub = AP.public(st, noon)
    assert set(pub) == {"on", "every_hours", "per_day", "upload", "preset", "made_today", "next_at"}


def test_turning_autopilot_on_starts_soon():
    h = Meta()
    AP.update(h, {"on": True})
    AP.mark_started(h, ts(2026, 11, 14, 9))
    AP.update(h, {"on": False})
    AP.update(h, {"on": True})
    assert AP.load(h)["last_run"] == 0


# ------------------------------------------------------------------ Studio API
class Sink:
    def __init__(self):
        self.jobs = []

    def put(self, job):
        self.jobs.append(job)


def test_preset_endpoints(server):  # noqa: F811
    app, port = server
    assert json.loads(req(port, "GET", "/api/presets")[2]) == {}
    assert req(port, "POST", "/api/presets", {"name": "Quick", "form": {"style": "facts"}})[0] == 403
    status, _, body = req(port, "POST", "/api/presets", {"name": "Quick", "form": {"style": "facts"}}, app.token)
    assert status == 200 and json.loads(body) == {"Quick": {"style": "facts"}}
    assert req(port, "POST", "/api/presets", {"name": "", "form": {}}, app.token)[0] == 400
    req(port, "POST", "/api/presets/delete", {"name": "Quick"}, app.token)
    assert json.loads(req(port, "GET", "/api/presets")[2]) == {}


def test_batch_queues_one_video_per_unique_topic(server):  # noqa: F811
    app, port = server
    app.queue = Sink()
    assert req(port, "POST", "/api/batch", {"topics": ["", "  "]}, app.token)[0] == 400
    status, _, body = req(port, "POST", "/api/batch",
                          {"topics": "Why cats purr\nwhy cats purr\n\nHow bees count", "style": "facts",
                           "script": {"evil": 1}}, app.token)
    assert status == 200 and len(json.loads(body)["jobs"]) == 2
    assert [(j.kind, j.params["topic"], j.params["style"], "script" in j.params) for j in app.queue.jobs] == [
        ("make", "Why cats purr", "facts", False), ("make", "How bees count", "facts", False)]


def test_autopilot_endpoint_and_tick(server):  # noqa: F811
    app, port = server
    app.queue = Sink()
    h = app.studio.history
    st = json.loads(req(port, "GET", "/api/autopilot")[2])
    assert st["on"] is False and st["next_at"] is None
    assert req(port, "POST", "/api/autopilot", {"every_hours": "x"}, app.token)[0] == 400
    P.save(h, "Look", {"style": "facts", "duration": 30})
    h.add_idea("Why the sky is blue", "", "")
    status, _, body = req(port, "POST", "/api/autopilot", {"on": True, "preset": "Look", "upload": True}, app.token)
    assert status == 200
    # turning it on starts the first video right away, from the idea queue, with the preset
    [job] = app.queue.jobs
    assert job.kind == "make" and job.params["source"] == "queue" and job.params["style"] == "facts"
    assert job.params["upload"] is True and job.label.startswith("Autopilot")
    assert json.loads(body)["made_today"] == 1
    # while that video waits, nothing else starts, even when the next one is due
    AP.save(h, {**AP.load(h), "last_run": 0})
    assert app.autopilot_tick() is None
    job.status = "done"
    assert app.autopilot_tick() is not None


def test_post_text_and_kit_zip(server, tmp_path):  # noqa: F811
    import io
    import zipfile
    app, port = server
    folder = tmp_path / "001-why-cats-purr"
    folder.mkdir()
    (folder / "short.mp4").write_bytes(b"\x00video")
    (folder / "cover.jpg").write_bytes(b"\xff\xd8jpg")
    (folder / "captions.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n")
    vid = app.studio.history.add_video(status="rendered", title="Why cats purr", description="Short answer.",
                                       tags=json.dumps(["cats", "pet facts", "!!"]), folder=str(folder),
                                       video_path=str(folder / "short.mp4"))
    status, headers, body = req(port, "GET", f"/files/{vid}/post.txt")
    assert status == 200 and headers["Content-Type"].startswith("text/plain")
    assert body.decode() == "TITLE\nWhy cats purr\n\nDESCRIPTION\nShort answer.\n\nHASHTAGS\n#cats #petfacts\n"
    status, headers, body = req(port, "GET", f"/files/{vid}/kit.zip")
    assert status == 200 and "001-why-cats-purr.zip" in headers["Content-Disposition"]
    z = zipfile.ZipFile(io.BytesIO(body))
    assert sorted(z.namelist()) == ["captions.srt", "cover.jpg", "post.txt", "short.mp4"]
    assert z.read("short.mp4") == b"\x00video" and z.read("post.txt").startswith(b"TITLE\nWhy cats purr")
    assert req(port, "GET", "/files/9999/kit.zip")[0] == 404
    assert req(port, "GET", "/files/9999/post.txt")[0] == 404
