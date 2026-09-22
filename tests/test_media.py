from purffle_shorts import media as M
from purffle_shorts.config import Settings


class R:
    def __init__(self, data):
        self.status_code, self._d, self.text = 200, data, ""

    def json(self):
        return self._d


class S:
    def __init__(self, data):
        self.data, self.params = data, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.params.append(params)
        return R(self.data)


def test_pexels_file_choice_prefers_1080_not_4k():
    files = [
        {"link": "u4k", "width": 2160, "height": 3840, "file_type": "video/mp4"},
        {"link": "u1080", "width": 1080, "height": 1920, "file_type": "video/mp4"},
        {"link": "u720", "width": 720, "height": 1280, "file_type": "video/mp4"},
        {"link": "", "width": 1080, "height": 1920},
        {"link": "hls", "width": None, "height": None},
    ]
    assert M._pexels_pick_file(files, prefer_4k=False)["link"] == "u1080"
    assert M._pexels_pick_file(files, prefer_4k=True)["link"] == "u4k"
    assert M._pexels_pick_file(files[2:3], False)["link"] == "u720"


def test_pexels_videos_parse(monkeypatch):
    data = {"videos": [{"id": 7, "duration": 12, "user": {"name": "Ann"},
                        "video_files": [{"link": "a", "width": 1080, "height": 1920, "file_type": "video/mp4"}]}]}
    sess = S(data)
    monkeypatch.setattr(M, "http", lambda: sess)
    items = M.pexels_videos("octopus", "key")
    assert items[0].key == "pexels:7" and items[0].portrait and items[0].duration == 12
    assert sess.params[0]["orientation"] == "portrait"


def test_pixabay_prefers_medium(monkeypatch):
    data = {"hits": [{"id": 3, "duration": 9, "user": "bob", "videos": {
        "large": {"url": "L", "width": 3840, "height": 2160},
        "medium": {"url": "Md", "width": 1920, "height": 1080},
        "small": {"url": "", "width": 0, "height": 0}}}]}
    monkeypatch.setattr(M, "http", lambda: S(data))
    assert M.pixabay_videos("x", "k")[0].url == "Md"
    assert M.pixabay_videos("x", "k", prefer_4k=True)[0].url == "L"


def test_claim_skips_used_media():
    v = M.Visuals(Settings(), used_keys={"pexels:1"})
    a = M.MediaItem("pexels", "1", "video", width=1080, height=1920, duration=10)
    b = M.MediaItem("pexels", "2", "video", width=1920, height=1080, duration=10)
    assert v._claim([a, b], 5).key == "pexels:2"
    assert v._claim([a, b], 5) is None


def test_simplify_query():
    assert M.simplify_query("The octopus in the deep ocean") == "octopus deep"


def test_no_footage_falls_back_to_generated(tmp_path):
    v = M.Visuals(Settings(visual_sources=["local"], media_dir=str(tmp_path / "none")))
    item = v.for_scene(0, "octopus", "octopus", "sea", 3.0, tmp_path)
    assert item.kind == "generated"
