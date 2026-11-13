"""The double-click launcher used by the desktop builds."""

import socket

from purffle_shorts import desktop


def test_home_is_purffle_home_or_documents(monkeypatch, tmp_path):
    monkeypatch.setenv("PURFFLE_HOME", str(tmp_path / "mine"))
    assert desktop.home_dir() == tmp_path / "mine"
    monkeypatch.delenv("PURFFLE_HOME")
    monkeypatch.setattr(desktop.Path, "home", lambda: tmp_path)
    assert desktop.home_dir() == tmp_path / "PurffleShorts"
    (tmp_path / "Documents").mkdir()
    assert desktop.home_dir() == tmp_path / "Documents" / "PurffleShorts"


def test_free_port_moves_off_a_taken_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        taken = s.getsockname()[1]
        port = desktop.free_port(taken)
    assert port != taken and port > 0


def test_second_launch_opens_the_running_studio(monkeypatch, tmp_path):
    monkeypatch.setenv("PURFFLE_HOME", str(tmp_path))
    opened, started = [], []
    monkeypatch.setattr(desktop, "running_studio", lambda port: True)
    monkeypatch.setattr(desktop.webbrowser, "open", opened.append)
    monkeypatch.setattr("purffle_shorts.cli.main", lambda argv: started.append(argv) or 0)
    assert desktop.main([]) == 0
    assert opened == ["http://127.0.0.1:8765/"] and not started
    assert (tmp_path / "logs").is_dir()


def test_first_launch_starts_studio_in_the_home_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("PURFFLE_HOME", str(tmp_path))
    started = []
    monkeypatch.setattr(desktop, "running_studio", lambda port: False)
    monkeypatch.setattr(desktop, "free_port", lambda preferred=8765: 9123)
    monkeypatch.setattr("purffle_shorts.cli.main", lambda argv: started.append(argv) or 0)
    assert desktop.main([]) == 0
    assert started == [["studio", "--port", "9123"]]


def test_running_studio_is_false_when_nothing_answers():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert desktop.running_studio(port) is False
