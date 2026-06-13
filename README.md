<div align="center">

# PurffleShorts — Automated YouTube Shorts Creator

**Fully autonomous YouTube Shorts pipeline — picks trending topics, writes scripts, generates voiceovers, assembles videos, and uploads to YouTube on autopilot.**

[![Python](https://img.shields.io/badge/python-3.9+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT-412991?style=for-the-badge&logo=openai&logoColor=white)](https://openai.com)
[![YouTube](https://img.shields.io/badge/YouTube-auto_upload-FF0000?style=for-the-badge&logo=youtube&logoColor=white)](https://youtube.com)
[![License: MIT](https://img.shields.io/badge/license-MIT-22c55e?style=for-the-badge)](LICENSE)

[Features](#-features) · [How It Works](#-how-it-works) · [Quick Start](#-quick-start) · [Categories](#-content-categories) · [Tech Stack](#-tech-stack)

</div>

---

## 🤖 What is PurffleShorts?

PurffleShorts is a **zero-touch content creation engine** that generates and publishes YouTube Shorts autonomously. Once started, it runs in a continuous loop — selecting trending topics, creating scripts, producing voiceovers, assembling professional short-form videos, and uploading them directly to YouTube.

Built for **content creators**, **YouTube channels**, and **digital marketers** who want to scale short-form video production without manual editing.

---

## 🔄 How It Works

```
Topic Selection → AI Script → Neural Voiceover → Stock Footage → Video Assembly → Auto Upload → Repeat
```

| Step | What Happens | Technology |
|------|-------------|------------|
| 1. **Topic** | Randomly picks from 20+ content categories | Built-in category engine |
| 2. **Script** | GPT writes a retention-optimized short-form script | OpenAI GPT-3.5 |
| 3. **Voice** | Neural TTS produces natural, human-like voiceover | Coqui TTS |
| 4. **Footage** | Fetches relevant stock clips from multiple sources | Pexels + Pixabay APIs |
| 5. **Assembly** | Composites footage, animated subtitles, background music | MoviePy + ImageMagick |
| 6. **Hashtags** | AI generates trending, category-relevant tags | OpenAI GPT |
| 7. **Upload** | Publishes to YouTube with optimized metadata | YouTube Data API v3 |

The entire pipeline repeats automatically — producing Shorts 24/7 without intervention.

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| **Fully autonomous** | Set it and forget it — generates Shorts continuously in a loop |
| **Neural TTS** | Coqui TTS for natural, studio-quality AI voiceovers |
| **Multi-source footage** | Pulls from both Pexels and Pixabay for diverse visuals |
| **Smart subtitles** | Word-wrapped, fade-animated captions synced to timing |
| **Background music** | Audio-loops a background track under the voiceover |
| **AI hashtags** | GPT generates trending hashtags per video category |
| **20+ categories** | Mystery, science, true crime, tech, finance, motivation, and more |
| **Auto upload** | Direct YouTube publishing with titles, descriptions, and tags |

---

## 🚀 Quick Start

### Prerequisites

- Python 3.9+
- [ImageMagick](https://imagemagick.org/script/download.php) installed
- API keys: [OpenAI](https://platform.openai.com/api-keys), [Pexels](https://www.pexels.com/api/), [Pixabay](https://pixabay.com/api/docs/)
- Google OAuth credentials for YouTube upload

### Install & Run

```bash
# Clone
git clone https://github.com/Chamanrajragu/purffle-shorts.git
cd purffle-shorts

# Setup
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env → add your API keys

# Run
python YT.py
```

The bot starts generating and uploading Shorts autonomously.

---

## 🔑 Environment Variables

| Variable | Required | Description |
|----------|:--------:|-------------|
| `OPENAI_API_KEY` | ✅ | OpenAI API key for scripts and hashtags |
| `PEXELS_API_KEY` | ✅ | Pexels API key for stock footage |
| `PIXABAY_API_KEY` | ✅ | Pixabay API key for additional footage |

---

## 🎯 Content Categories

The bot randomly selects from these categories for maximum variety:

`Mystery` · `Horror Stories` · `Science` · `True Crime` · `Tech Trends` · `Finance Tips` · `Space Exploration` · `Psychology` · `Motivational` · `Self-Improvement` · `History Mysteries` · `Fun Facts` · `Cars` · `Trending News` · `Interesting People` · `Philosophy` · `Nature` · `Gaming` · `Health` · `AI & Future`

---

## 🏗️ Tech Stack

| Component | Technology |
|-----------|-----------|
| **AI Script** | OpenAI GPT-3.5 Turbo |
| **Voice** | Coqui TTS (neural text-to-speech) |
| **Video** | MoviePy, ImageMagick, Pillow |
| **Stock Media** | Pexels API, Pixabay API |
| **Upload** | YouTube Data API v3, OAuth 2.0 |
| **Language** | Python 3.9+ |

---

## 📁 Project Structure

```
purffle-shorts/
├── YT.py                  # Main automation engine
├── el.py                  # Extended logic module
├── ytt.py                 # YouTube upload helpers
├── requirements.txt       # Python dependencies
├── .env.example           # API key template
└── output_videos/         # Generated Shorts (gitignored)
```

---

## ⚠️ Disclaimer

> This is an open-source automation tool for educational purposes. Requires your own API keys. Always review AI-generated content before publishing. Comply with YouTube's Terms of Service and Community Guidelines. Not affiliated with YouTube, OpenAI, Pexels, or Pixabay.

---

<div align="center">

**Built by [Chaman Raj](https://github.com/Chamanrajragu)**

Part of the **Purffle** ecosystem — PurffleTools · PurffleAI · [Purffle.com](https://purffle.com)

</div>
