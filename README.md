<p align="center">
  <img src="https://img.shields.io/badge/Purffle_Studios-Shorts_Automator-FF0000?style=for-the-badge&logo=youtube&logoColor=white" alt="PurffleShorts"/>
</p>

<h1 align="center">PurffleShorts — Automated YouTube Shorts Creator</h1>

<p align="center">
  <strong>Fully autonomous YouTube Shorts pipeline — picks trending topics, generates scripts, creates videos, and uploads to YouTube on autopilot.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.9+-blue?style=flat-square&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/OpenAI-GPT_3.5-412991?style=flat-square&logo=openai&logoColor=white" />
  <img src="https://img.shields.io/badge/Coqui_TTS-voice_cloning-FF6F00?style=flat-square" />
  <img src="https://img.shields.io/badge/MoviePy-video_engine-FF6F00?style=flat-square" />
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" />
</p>

---

## What It Does

PurffleShorts is a zero-touch content creation engine. It runs continuously, generating and uploading YouTube Shorts without human intervention:

1. **Topic Selection** — Randomly picks from 20+ content categories (mystery, science, true crime, tech, motivation, etc.)
2. **Script Writing** — GPT-3.5 generates an engaging short-form script optimized for viewer retention
3. **Voice Synthesis** — Coqui TTS produces studio-quality AI voiceovers (not robotic Google TTS)
4. **Stock Footage** — Fetches relevant video clips from Pexels and Pixabay APIs
5. **Video Assembly** — MoviePy composites footage, adds animated subtitles with fade effects, overlays background music
6. **Hashtag Generation** — AI generates trending, category-relevant hashtags for maximum reach
7. **Auto Upload** — Publishes directly to YouTube with optimized titles, descriptions, and tags

## Features

- **Fully autonomous** — Set it and forget it. Generates Shorts continuously in a loop
- **Coqui TTS** — Neural text-to-speech for natural, human-like voiceovers
- **Multi-source footage** — Pulls from both Pexels and Pixabay for diverse visuals
- **Smart subtitles** — Word-wrapped, fade-animated captions synced to voiceover timing
- **Background music** — Audio-loops a background track under the voiceover
- **AI hashtags** — GPT generates category-specific trending hashtags per video
- **20+ categories** — Mystery, horror, science, true crime, finance, tech, motivation, and more

## Tech Stack

| Component | Technology |
|-----------|-----------|
| AI Script | OpenAI GPT-3.5 Turbo |
| Voice | Coqui TTS (neural) |
| Video | MoviePy, ImageMagick, Pillow |
| Stock Media | Pexels API, Pixabay API |
| Upload | YouTube Data API v3, OAuth 2.0 |
| Language | Python 3.9+ |

## Quick Start

### Prerequisites

- Python 3.9+
- [ImageMagick](https://imagemagick.org/script/download.php) installed
- API keys for OpenAI, Pexels, and Pixabay
- Google OAuth credentials for YouTube

### Installation

```bash
# Clone the repo
git clone https://github.com/Chamanrajragu/purffle-shorts.git
cd purffle-shorts

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys
```

### Run

```bash
python YT.py
```

The bot will start generating and uploading Shorts autonomously.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | Your OpenAI API key |
| `PEXELS_API_KEY` | Your Pexels API key |
| `PIXABAY_API_KEY` | Your Pixabay API key |
| `GOOGLE_CLIENT_SECRETS_FILE` | Path to Google OAuth credentials |

## Content Categories

The bot randomly selects from these categories for maximum variety:

`Mystery` · `Horror Stories` · `Science` · `True Crime` · `Tech Trends` · `Finance Tips` · `Space Exploration` · `Psychology` · `Motivational` · `Self-Improvement` · `History Mysteries` · `Fun Facts` · `Cars` · `Trending News` · `Interesting People` · and more

## Project Structure

```
purffle-shorts/
├── YT.py                  # Main automation engine
├── el.py                  # Extended logic module
├── ytt.py                 # YouTube utility helpers
├── requirements.txt       # Python dependencies
├── .env.example           # Environment variable template
└── output_videos/         # Generated Shorts (gitignored)
```

---

<p align="center">
  Built with passion by <a href="https://github.com/Chamanrajragu"><strong>Purffle Studios</strong></a>
  <br/>
  <sub>Part of the Purffle ecosystem — PurffleTools · PurffleAI · Purffle.com</sub>
</p>
