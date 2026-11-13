# Desktop builds

PurffleShorts Studio as a double-click app for Windows, macOS and Linux. The app is the same Studio as
`purffle-shorts studio`; `purffle_shorts/desktop.py` adds what a double-clicked program needs:

| Need | What the launcher does |
| --- | --- |
| A folder for settings and videos | `Documents/PurffleShorts` (or `PURFFLE_HOME`), created on first run |
| Clicking the icon twice | The second launch opens the Studio that is already running |
| Port 8765 taken by another program | Uses a free port instead |
| No console window | Output goes to `logs/desktop.log`; the app log stays in `logs/purffle.log` |

ffmpeg comes inside the app (from `imageio-ffmpeg`), so people don't install anything else.
Local models run through Ollama, which people install from ollama.com; the Studio's **Local AI** page
finds it, starts it and downloads models.

## Build

PyInstaller can't cross-compile, so build on each OS (or in CI on `windows-latest`, `macos-latest`,
`macos-15-intel` for Intel, and `ubuntu-22.04`):

```bash
python -m pip install -e . pyinstaller
pyinstaller packaging/purffle-studio.spec --noconfirm
```

- macOS: `dist/PurffleShorts.app`
- Windows and Linux: the folder `dist/PurffleShorts/` with `PurffleShorts.exe` / `PurffleShorts`

The build leaves out the big optional extras (Kokoro voice, faster-whisper, OpenCV, Torch) to keep the
download small. Videos still get a free voice (edge-tts, or the system voice offline).

## Before publishing on the website

- **Icons:** `icon.icns` (macOS), `icon.ico` (Windows) and `icon.png` are in this folder and the spec
  picks them up. After changing the logo, run `python packaging/make_icons.py` to redraw them.
- **CI:** `.github/workflows/desktop.yml` builds all four apps (Windows, macOS Apple silicon and Intel,
  Linux) on every published release and attaches them as zips; run it by hand from the Actions tab too.
- **macOS:** sign with a Developer ID and notarize, or Gatekeeper blocks the app:
  `codesign --deep --options runtime --sign "Developer ID Application: …" dist/PurffleShorts.app`, then
  `xcrun notarytool submit … --wait` and `xcrun stapler staple`. Ship it inside a `.dmg`.
- **Windows:** sign `PurffleShorts.exe` (SmartScreen warns about unsigned apps) and wrap the folder in
  an installer (Inno Setup or NSIS) that adds a Start menu entry.
- **Linux:** ship the folder as a `.tar.gz`, or as an AppImage with `appimagetool`.
- Build each platform from a clean virtual environment, so nothing extra ends up in the bundle.
