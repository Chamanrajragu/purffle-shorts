"""Double-click launcher for the desktop builds (Windows .exe, macOS .app, Linux AppImage).

What it does that ``purffle-shorts studio`` in a terminal doesn't need to:

* picks a home folder the user can find and write to (a .app starts in ``/``, an .exe wherever it was
  clicked from): ``PURFFLE_HOME`` if set, otherwise ``Documents/PurffleShorts``;
* opens the Studio that is already running instead of starting a second copy;
* uses another port when 8765 is taken by some other program;
* gives a windowed build (no console, so ``sys.stdout`` is None) somewhere to print.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import urllib.request
import webbrowser
from pathlib import Path

PORT = 8765
APP_DIR = "PurffleShorts"


def home_dir() -> Path:
    if os.getenv("PURFFLE_HOME"):
        return Path(os.environ["PURFFLE_HOME"]).expanduser()
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / APP_DIR


def running_studio(port: int) -> bool:
    """Is our own Studio already answering on this port?"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/info", timeout=1.5) as r:
            return "llm" in json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError):
        return False


def free_port(preferred: int = PORT) -> int:
    for port in (preferred, 0):  # 0: let the system pick one
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            # like the Studio's own server: a port a closed Studio left in TIME_WAIT is still ours to use
            if sys.platform != "win32":
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return s.getsockname()[1]
    raise OSError("no free port")


def _console(home: Path) -> None:
    if sys.stdout is None or sys.stderr is None:
        out = open(home / "logs" / "desktop.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stdout = sys.stdout or out
        sys.stderr = sys.stderr or out


def main(argv: list[str] | None = None) -> int:
    home = home_dir()
    (home / "logs").mkdir(parents=True, exist_ok=True)
    _console(home)
    if running_studio(PORT):
        webbrowser.open(f"http://127.0.0.1:{PORT}/")
        return 0
    os.environ["PURFFLE_HOME"] = str(home)
    from .cli import main as cli_main
    return cli_main(["studio", "--port", str(free_port()), *(argv if argv is not None else sys.argv[1:])])


if __name__ == "__main__":
    raise SystemExit(main())
