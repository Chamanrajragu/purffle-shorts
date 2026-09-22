# Contributing to PurffleShorts

Thanks for helping. Bug reports, ideas, new voices, caption styles and providers are all welcome.

## Dev setup

```bash
git clone https://github.com/Chamanrajragu/purffle-shorts.git
cd purffle-shorts
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -e ".[dev]"
```

## Checks

```bash
ruff check .
pytest -q
```

The tests need no API keys and no network. They include an end-to-end test that renders a real video with ffmpeg (the bundled `imageio-ffmpeg` binary is enough). CI runs the same checks on Python 3.10, 3.11, 3.12 and 3.13.

## Pull requests

- Keep a change focused on one thing, and add a test for new behaviour.
- Never commit keys, `.env`, `credentials.json`, `token.json` or rendered videos. `.gitignore` covers them.
- New settings go in `config.py` and are documented in `.env.example`.
- If a change affects what users see, update `README.md` and `CHANGELOG.md`.

## Reporting bugs

Open an issue with the command you ran, the output of `python -m purffle_shorts doctor`, and the end of `data/logs/purffle.log`. Remove API keys and personal details first.
