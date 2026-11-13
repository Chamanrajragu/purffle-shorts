"""Entry script PyInstaller freezes (it can't start from a module with relative imports)."""

import multiprocessing

from purffle_shorts.desktop import main

if __name__ == "__main__":
    multiprocessing.freeze_support()  # Windows: child processes of a frozen app re-run this file
    raise SystemExit(main())
