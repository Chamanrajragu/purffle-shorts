# PyInstaller recipe for the desktop app. Build on each OS (PyInstaller can't cross-compile):
#   pip install -e ".[dev]" pyinstaller
#   pyinstaller packaging/purffle-studio.spec --noconfirm
# Output: dist/PurffleShorts/ (Windows, Linux) or dist/PurffleShorts.app (macOS). See packaging/README.md.
# ruff: noqa
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
NAME = "PurffleShorts"

datas = collect_data_files("purffle_shorts")  # web/ (HTML, CSS, JS, fonts) and any other package files
binaries = []
hidden = collect_submodules("purffle_shorts")
# ffmpeg ships inside imageio-ffmpeg, so people don't have to install it; edge-tts and certifi carry data files
for pkg in ("imageio_ffmpeg", "edge_tts", "certifi", "PIL"):
    d, b, h = collect_all(pkg)
    datas, binaries, hidden = datas + d, binaries + b, hidden + h

a = Analysis([str(ROOT / "packaging" / "launch.py")], pathex=[str(ROOT)], datas=datas, binaries=binaries,
             hiddenimports=hidden,
             # big optional extras stay out of the default download (offline voice/transcription install later)
             excludes=["torch", "kokoro", "faster_whisper", "ctranslate2", "TTS", "cv2", "matplotlib", "tkinter",
                       "pytest", "IPython", "notebook"],
             noarchive=False)
pyz = PYZ(a.pure)
icon = {"win32": "icon.ico", "darwin": "icon.icns"}.get(sys.platform)
icon = str(ROOT / "packaging" / icon) if icon and (ROOT / "packaging" / icon).exists() else None
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME, console=False, icon=icon,
          upx=False, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME, upx=False)
if sys.platform == "darwin":
    app = BUNDLE(coll, name=f"{NAME}.app", icon=icon, bundle_identifier="com.purffle.shorts",
                 info_plist={"CFBundleShortVersionString": "3.0.0", "NSHighResolutionCapable": True,
                             "LSApplicationCategoryType": "public.app-category.video"})
