"""The keyed path end to end with fakes: LLM -> Pexels search + download -> render -> upload/schedule/queue."""

import json
import subprocess

import pytest

from purffle_shorts import ffmpeg
from purffle_shorts import media as M
from purffle_shorts import pipeline as P
from purffle_shorts import utils as U

from .conftest import needs_ffmpeg

SCRIPT = {
    "topic": "Octopus hearts", "title": "Why Octopuses Have Three Hearts", "hook_text": "3 HEARTS?!",
    "scenes": [
        {"narration": "An octopus has three hearts.", "search_query": "octopus", "image_prompt": "octopus"},
        {"narration": "Two pump blood through the gills.", "search_query": "octopus gills", "image_prompt": "gills"},
        {"narration": "Follow for more ocean facts.", "search_query": "ocean", "image_prompt": "ocean"},
    ],
    "description": "Three hearts, one octopus.", "hashtags": ["#octopus"], "tags": ["octopus"],
    "category": "science",
}


class FakeLLM:
    def __init__(self, settings):
        self.providers, self.label = [object()], "fake:model"

    def complete_json(self, system, user, schema=None, max_tokens=4000):
        assert "JSON" in system
        return json.loads(json.dumps(SCRIPT))


class Resp:
    def __init__(self, data=None, path=None):
        self.status_code, self._data, self._path, self.text = 200, data, path, ""

    def json(self):
        return self._data

    def iter_content(self, chunk_size=65536):
        with open(self._path, "rb") as f:
            while chunk := f.read(chunk_size):
                yield chunk

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def clip(tmp_path):
    path = tmp_path / "clip.mp4"
    subprocess.run([ffmpeg.ffmpeg_bin(), "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=6",
                    "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


@pytest.fixture
def online(settings, monkeypatch, clip):
    searches = []

    class Session:
        def get(self, url, params=None, headers=None, timeout=None, stream=False):
            if "api.pexels.com/videos/search" in url:
                searches.append(params["query"])
                base = abs(hash(params["query"])) % 1000 * 10
                vids = [{"id": base + i, "duration": 6, "user": {"name": "Ann"},
                         "video_files": [{"link": f"http://fake/{base + i}.mp4", "width": 640, "height": 360,
                                          "file_type": "video/mp4"}]} for i in range(2)]
                return Resp({"videos": vids})
            if url.startswith("http://fake/"):
                return Resp(path=clip)
            raise AssertionError(f"unexpected request {url}")

    monkeypatch.setattr(M, "http", lambda: Session())
    monkeypatch.setattr(U, "http", lambda: Session())
    monkeypatch.setattr(P, "LLM", FakeLLM)
    s = settings.with_overrides(tts_engine="silent", resolution=(360, 640), fps=24, music_volume=0.0,
                                visual_sources=["pexels"], pexels_api_key="k", upload=True)
    return s, searches


@needs_ffmpeg
def test_keyed_pipeline_uploads_and_dedupes(online, monkeypatch):
    s, searches = online
    uploads = []
    monkeypatch.setattr(P.youtube, "upload", lambda settings, video, body: uploads.append(body) or {"id": "vid1"})
    studio = P.Studio(s)
    r = studio.make()
    assert r.ok, r.error
    assert r.status == "uploaded" and r.youtube_id == "vid1"
    assert searches[:1] == ["octopus"]
    body = uploads[0]
    assert body["snippet"]["title"] == "Why Octopuses Have Three Hearts #shorts"
    assert body["snippet"]["categoryId"] == "28"
    assert "Footage: Pexels" in body["snippet"]["description"]
    assert not r.video.exists()                        # KEEP_VIDEOS=false removes the MP4 after upload
    used = studio.history.used_media()
    assert len(used) == 3 and all(k.startswith("pexels:") for k in used)


@needs_ffmpeg
def test_schedule_and_quota_queue(online, monkeypatch):
    s, _ = online
    monkeypatch.setattr(P.youtube, "upload", lambda settings, video, body: {"id": "v"})
    s = s.with_overrides(publish_times=["09:00", "21:00"], keep_videos=True, daily_upload_limit=1)
    studio = P.Studio(s)
    first = studio.make()
    assert first.status == "scheduled" and first.publish_at
    second = studio.make()
    assert second.status == "queued" and second.video.exists()
    assert [row["id"] for row in studio.history.pending_uploads()] == [second.record_id]
