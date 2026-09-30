<div align="center">

# PurffleShorts — 免费 AI YouTube Shorts 短视频生成器与自动上传工具

[English](README.md) · **简体中文** · [Español](README.es.md) · [Português](README.pt-BR.md) · [हिन्दी](README.hi.md) · [日本語](README.ja.md)

**一款开源的 AI 视频生成器，适用于 YouTube Shorts、TikTok 和 Instagram Reels。给它一个主题、一个网页、一篇 Reddit 帖子或一期长播客，它就能生成完整的竖屏成片（脚本、配音、画面素材、字幕），然后上传到 YouTube 或定时发布。**

[![CI](https://github.com/Chamanrajragu/purffle-shorts/actions/workflows/ci.yml/badge.svg)](https://github.com/Chamanrajragu/purffle-shorts/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-22c55e)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/Chamanrajragu/purffle-shorts?style=social)](https://github.com/Chamanrajragu/purffle-shorts/stargazers)

<img src="docs/hero.gif" alt="PurffleShorts 生成的三条 Shorts 并排播放：一条关于火烈鸟的冷知识视频，带逐词高亮字幕；一段关于章鱼的双人配音对话，带说话人名字标签；以及一个在动画手机屏幕上展开的短信聊天故事" width="770">

<sub>真实输出，未经剪辑。使用免费的 Microsoft 神经网络语音和 AI 图片。GIF 动图没有声音。</sub>

**无需 API 密钥、无需注册即可试用**（需要安装 [uv](https://docs.astral.sh/uv/)）：

```bash
uvx --from git+https://github.com/Chamanrajragu/purffle-shorts purffle-shorts demo --style chat
```

**⭐ 如果 PurffleShorts 帮你节省了时间，点个 Star 能让更多创作者发现它。**

</div>

> 这是精简版。完整文档（所有设置、AI 模型、语音、字幕、发布、命令行、Studio、故障排查）请参阅 [英文版 README](README.md)。

## PurffleShorts 是什么？

PurffleShorts 是一款面向无人出镜频道的 YouTube Shorts 自动化工具。启动后它就会持续运转：挑选新主题，由你选择的 AI 模型撰写脚本，再经过第二轮 AI 审阅和精简，生成自然的 AI 配音，匹配相关的画面素材，加上与配音逐词同步的字幕，渲染出精良的成片，最后上传或定时发布。

它同时也是一个小型工作室：渲染前可以修改脚本的任意一行，可以制作双人对话、短信聊天故事和 Reddit 风格的故事，把一篇文章或一篇 Reddit 帖子做成一条 Short，把播客剪成多条 Shorts，还能用多种语言发布同一个视频。它在你自己的电脑上运行（macOS、Windows、Linux 或 Docker），生成的 9:16 MP4 文件同样适用于 TikTok 和 Instagram Reels。

## 功能特性

- **支持任意 AI 模型**：OpenAI GPT、Anthropic Claude、Google Gemini、DeepSeek、Mistral、xAI Grok、Groq、OpenRouter、Together AI、Ollama 和 LM Studio（本地运行，免费），或任何兼容 OpenAI 的 API。在 `LLM_FALLBACKS` 中列出备用服务商后，主服务商失败时会按顺序尝试。
- **Script Doctor**：由第二轮 AI 按留住观众的效果给每个脚本打分（0 到 100 分），列出薄弱之处并加以改写。
- **322 种免费神经网络语音，覆盖 75 种语言**，带词级时间戳，无需密钥。对话和聊天故事可使用两个不同的声音。
- **每句话都有画面**：来自 Pexels 或 Pixabay 的素材库视频（可免费申请密钥）、AI 图片，或你自己的媒体文件夹。
- **逐词动画字幕**，提供六种样式，支持拉丁文、印度系文字、阿拉伯文、泰文和中日韩文字。
- **9:16、16:9、1:1 或 4:5** 画幅输出，使用 ffmpeg 渲染，无需 GPU。
- **上传到 YouTube**，或把每个视频排进你的下一个空闲时段定时发布，并设置好 AI 内容声明。
- **一个视频，多种语言**：`--also-lang es,hi` 会生成复用同一套画面素材的翻译版本。
- **Studio 网页应用**，运行在你的电脑上：起草、编辑、渲染、实时查看进度、浏览视频库。
- **MCP 服务器**：让 Claude Desktop、Claude Code 或 Cursor 帮你制作、剪辑或上传视频。

## 视频类型

| 类型 | 生成效果 |
|---|---|
| `facts` · `story` · `listicle` · `myth` · `quiz` · `explainer` · `motivational` · `news` | 单人旁白，每个场景都有画面素材，逐词高亮字幕 |
| `dialogue` | 两个人对话，各自使用不同的声音；字幕会标出说话人的名字和对应颜色 |
| `chat` | 短信聊天故事：随着朗读，消息在动画手机屏幕上逐条弹出，并带有“正在输入”提示 |
| `reddit` | 以 Reddit 帖子形式讲述的第一人称故事：朗读标题时显示帖子卡片，随后配合字幕讲述正文 |

```bash
purffle-shorts make --style chat --topic "保姆收到陌生号码发来的短信"
purffle-shorts make --style reddit --topic "总来借我梯子的邻居"
```

## 快速开始

需要 Python 3.10 或更高版本。如果已安装 ffmpeg 则直接使用，否则使用自带的版本。

```bash
git clone https://github.com/Chamanrajragu/purffle-shorts.git
cd purffle-shorts
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -e .
python -m purffle_shorts demo                        # 示例视频，无需任何密钥
python -m purffle_shorts studio                      # Web 应用
```

然后把 `.env.example` 复制为 `.env`，填入一个 AI 密钥（或运行 Ollama）以及一个免费的 Pexels 或 Pixabay 密钥，再运行 `python -m purffle_shorts doctor` 检查配置。`python -m purffle_shorts make --topic "why octopuses have three hearts" --no-upload` 生成一个视频；`python -m purffle_shorts auth` 连接你的 YouTube 频道；`python -m purffle_shorts run` 启动全自动模式。

## 把长视频剪成 Shorts

```bash
pip install faster-whisper yt-dlp
purffle-shorts clip podcast.mp4 --count 3 --no-upload
```

视频会先被转录成文字，AI 挑出能单独成立的片段，每个片段都会变成一条带字幕的竖屏短片。功能类似 Opus Clip，但在你自己的电脑上运行，也不按分钟收费。请只剪辑你拥有版权或已获授权二次使用的视频。

## 在 Claude 和其他 AI 应用中使用（MCP）

```json
{
  "mcpServers": {
    "purffle-shorts": {
      "command": "purffle-shorts",
      "args": ["mcp"],
      "env": { "PURFFLE_HOME": "/path/to/your/purffle/folder" }
    }
  }
}
```

然后直接提需求，例如：“用西班牙语做一个 30 秒的短信故事，讲一个闹鬼的智能音箱。”除非你要求，否则不会上传任何内容。

## 常见问题

**免费吗？** 是的。项目采用 MIT 许可证，在你的电脑上运行。语音、Ollama 模型以及 Pexels 和 Pixabay 的 API 都是免费的；只有你选用的付费 API（比如 OpenAI 或 ElevenLabs）才需要付费。

**没有 API 密钥能试用吗？** 可以：`demo` 命令无需任何密钥即可渲染一个示例视频。

**能发布到 TikTok 或 Instagram 吗？** 它只支持上传到 YouTube。每个视频都是标准 MP4，附带封面图和字幕，所以你可以自己把同一个文件发布到 TikTok 和 Reels（上传到 YouTube 后 MP4 会被删除，除非设置 `KEEP_VIDEOS=true`）。

**需要 GPU 吗？** 不需要。渲染由 ffmpeg 在 CPU 上完成。

**允许自动上传吗？** 它使用官方的 YouTube Data API，通过你自己的 Google 账号登录，并设置 YouTube 的合成内容声明。请审核你的视频，并遵守 YouTube 的相关政策。

## 许可证

MIT。由 [Chaman Raj](https://github.com/Chamanrajragu) 开发 · [purffle.com](https://purffle.com/purffle-shorts/)。与 YouTube、OpenAI、Anthropic、Google、Microsoft、Pexels、Pixabay、Pollinations 或 Reddit 均无关联。
