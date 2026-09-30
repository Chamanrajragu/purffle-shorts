<div align="center">

# PurffleShorts — 無料の AI YouTube Shorts 自動生成・自動アップロードツール

[English](README.md) · [简体中文](README.zh-CN.md) · [Español](README.es.md) · [Português](README.pt-BR.md) · [हिन्दी](README.hi.md) · **日本語**

**YouTube Shorts、TikTok、Instagram Reels 向けのオープンソース AI 動画生成ツールです。トピック、Web ページ、Reddit の投稿、長いポッドキャストを渡すと、完成した縦型動画（台本、ナレーション、映像素材、字幕）を作成し、YouTube にアップロードまたは予約投稿します。**

[![CI](https://github.com/Chamanrajragu/purffle-shorts/actions/workflows/ci.yml/badge.svg)](https://github.com/Chamanrajragu/purffle-shorts/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-22c55e)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/Chamanrajragu/purffle-shorts?style=social)](https://github.com/Chamanrajragu/purffle-shorts/stargazers)

<img src="docs/hero.gif" alt="PurffleShorts で作成した 3 本の Shorts を並べて再生している様子：単語ハイライト字幕付きのフラミンゴの雑学動画、話者の名前タグ付きで 2 人の声がタコについて話す対話動画、アニメーションするスマホ画面上で展開するメッセージ風ストーリー" width="770">

<sub>編集なしの実際の出力です。無料の Microsoft ニューラル音声と AI 画像を使用しています。GIF には音声がありません。</sub>

**API キーもサインアップも不要で試せます**（[uv](https://docs.astral.sh/uv/) が必要です）：

```bash
uvx --from git+https://github.com/Chamanrajragu/purffle-shorts purffle-shorts demo --style chat
```

**⭐ PurffleShorts で時間を節約できたら、スターを付けていただけると他のクリエイターが見つけやすくなります。**

</div>

> これは簡略版です。完全なドキュメント（すべての設定、AI モデル、音声、字幕、公開、コマンドライン、Studio、トラブルシューティング）は [英語版 README](README.md) にあります。

## PurffleShorts とは？

PurffleShorts は、顔出しなしのチャンネル向けの YouTube Shorts 自動化ツールです。一度起動すれば、あとは自動で回り続けます。新しいトピックを決め、選んだ AI モデルが台本を書き、それを 2 回目の AI パスでレビューして引き締めます。さらに自然な AI ナレーション、内容に合った映像素材、話される単語ごとに同期した字幕を付けて丁寧にレンダリングし、アップロードまたは予約公開まで行います。

小さなスタジオとしても使えます。レンダリング前に台本のどの行でも編集でき、2 人の声による対話動画、メッセージ風ストーリー、Reddit 風ストーリーを作れるほか、記事や Reddit の投稿を Short にしたり、ポッドキャストを切り抜いて Shorts にしたり、同じ動画を複数の言語で公開したりできます。自分のコンピューター（macOS、Windows、Linux、Docker）で動作し、9:16 の MP4 ファイルは TikTok や Instagram Reels でもそのまま使えます。

## 機能

- **どの AI モデルでも使える：** OpenAI GPT、Anthropic Claude、Google Gemini、DeepSeek、Mistral、xAI Grok、Groq、OpenRouter、Together AI、Ollama と LM Studio（ローカルで無料）、または任意の OpenAI 互換 API に対応します。`LLM_FALLBACKS` に予備のプロバイダーを指定しておけば、メインが失敗したときに順番に試します。
- **Script Doctor：** 2 回目の AI パスが、視聴者をどれだけ引き留められるかという観点で各台本を 0〜100 点で採点し、弱い点を挙げたうえで書き直します。
- **75 言語に対応した 322 種類の無料ニューラル音声**を単語単位のタイミング付きで利用でき、キーは不要です。対話動画とチャットストーリーでは 2 つの声を使います。
- **すべての文に映像素材：** Pexels または Pixabay のストック動画（無料キー）、AI 画像、または自分のメディアフォルダーから用意します。
- **単語ごとにアニメーションする字幕**を 6 種類のスタイルで用意しており、ラテン文字、インド系文字、アラビア文字、タイ文字、CJK の各文字体系に対応しています。
- **9:16、16:9、1:1、4:5** で出力し、ffmpeg でレンダリングします。GPU は不要です。
- **YouTube へのアップロード**、または各動画を次の空き時間枠に予約投稿でき、AI 生成コンテンツの開示設定も行います。
- **1 本の動画を多言語で：** `--also-lang es,hi` で、同じ映像素材を再利用した翻訳版を作成します。
- **Studio Web アプリ**を自分のコンピューター上で使えます。下書き、編集、レンダリング、進捗のリアルタイム確認、ライブラリの閲覧ができます。
- **MCP サーバー：** Claude Desktop、Claude Code、Cursor に動画の作成、切り抜き、アップロードを頼めます。

## フォーマット

| フォーマット | 仕上がり |
|---|---|
| `facts` · `story` · `listicle` · `myth` · `quiz` · `explainer` · `motivational` · `news` | ナレーター 1 人、シーンごとの映像素材、単語ハイライト字幕 |
| `dialogue` | 2 人がそれぞれ自分の声で会話します。字幕には話者の名前と色が表示されます |
| `chat` | メッセージ風のストーリー：読み上げに合わせて、アニメーションするスマホ画面にメッセージが次々と表示され、入力中インジケーターも出ます |
| `reddit` | Reddit の投稿のように一人称で語られるストーリー：タイトルの読み上げ中は投稿カードを表示し、その後に字幕付きで本編が流れます |

```bash
purffle-shorts make --style chat --topic "ベビーシッターに知らない番号からメッセージが届く"
purffle-shorts make --style reddit --topic "何度もうちのはしごを借りに来る隣人"
```

## クイックスタート

Python 3.10 以降が必要です。ffmpeg がインストールされていればそれを使い、なければ同梱のものを使います。

```bash
git clone https://github.com/Chamanrajragu/purffle-shorts.git
cd purffle-shorts
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -e .
python -m purffle_shorts demo                        # サンプル動画（キー不要）
python -m purffle_shorts studio                      # Web アプリ
```

次に `.env.example` を `.env` にコピーし、AI のキーを 1 つ（または Ollama を起動）と、無料の Pexels または Pixabay のキーを追加してから、`python -m purffle_shorts doctor` でセットアップを確認します。`python -m purffle_shorts make --topic "why octopuses have three hearts" --no-upload` で動画を 1 本作成し、`python -m purffle_shorts auth` で YouTube チャンネルを接続し、`python -m purffle_shorts run` でオートパイロットを開始します。

## 長い動画を切り抜いて Shorts にする

```bash
pip install faster-whisper yt-dlp
purffle-shorts clip podcast.mp4 --count 3 --no-upload
```

動画を文字起こしし、AI がそれだけで成り立つ場面を選び、それぞれを字幕付きの縦型クリップにします。Opus Clip と同じような仕組みですが、自分のコンピューター上で動作し、分単位の料金もかかりません。切り抜くのは、自分が所有している動画か、再利用の許可を得ている動画だけにしてください。

## Claude などの AI アプリから使う（MCP）

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

あとは、たとえば「幽霊が取り憑いたスマートスピーカーについての 30 秒のメッセージ風ストーリーを、スペイン語で作って」のように頼むだけです。頼まない限り、何もアップロードされません。

## よくある質問

**無料ですか？** はい。MIT ライセンスで、自分のコンピューター上で動作します。音声、Ollama のモデル、Pexels と Pixabay の API は無料です。費用がかかるのは、OpenAI や ElevenLabs など、自分で選んだ有料 API だけです。

**API キーなしで試せますか？** はい。`demo` コマンドを使えば、キーなしでサンプル動画をレンダリングできます。

**TikTok や Instagram にも投稿できますか？** アップロード先は YouTube のみです。どの動画もカバー画像と字幕が付いた標準的な MP4 なので、同じファイルを TikTok や Reels に自分で投稿できます（YouTube へのアップロード後、MP4 は削除されます。残すには `KEEP_VIDEOS=true` を設定してください）。

**GPU は必要ですか？** いいえ。レンダリングには CPU 上の ffmpeg を使います。

**自動アップロードは許可されていますか？** 公式の YouTube Data API を、あなた自身の Google アカウントでサインインして利用し、YouTube の合成コンテンツの開示設定も行います。動画は自分で確認し、YouTube のポリシーに従ってください。

## ライセンス

MIT。開発：[Chaman Raj](https://github.com/Chamanrajragu) · [purffle.com](https://purffle.com/purffle-shorts/)。YouTube、OpenAI、Anthropic、Google、Microsoft、Pexels、Pixabay、Pollinations、Reddit とは提携していません。
