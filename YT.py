"""Backwards-compatible entry point for PurffleShorts 1.x users.

    python YT.py                 # autopilot: make + upload Shorts on a loop
    python YT.py --once          # one batch, then exit
    python YT.py --no-upload     # render only, keep the MP4s
    python YT.py --count 3       # stop after 3 videos

Everything now lives in the `purffle_shorts` package; see `python -m purffle_shorts --help`.
"""

import sys

from purffle_shorts.cli import main

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0].startswith("-"):
        args = ["run", *args]
    raise SystemExit(main(args))
