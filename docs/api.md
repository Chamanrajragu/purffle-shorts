# PurffleShorts REST API (automation, n8n, Zapier, cron)

The Studio web app is a small JSON API, and anything that can send HTTP requests can drive it:
n8n, Make, Zapier (through a webhook relay), Home Assistant, a cron job, or your own script. The
Studio itself uses the same API.

```bash
purffle-shorts studio --no-browser                        # http://127.0.0.1:8765, this computer only
```

## Authentication

| What | When | How |
|---|---|---|
| Write token | Every `POST` | `X-Studio-Token: <token>` header. Set `STUDIO_TOKEN` in `.env` to choose it; otherwise it is random on each start. |
| Password | Every request, when `STUDIO_PASSWORD` is set | HTTP Basic auth: any user name, the password from `STUDIO_PASSWORD`. |
| Host check | When the Studio listens on 127.0.0.1 | Requests must use `localhost` or `127.0.0.1` as the host name (this blocks DNS-rebinding attacks). |

To call it from another machine or container (for example n8n in Docker), start it on all interfaces
and protect it with a password:

```bash
STUDIO_TOKEN=change-me STUDIO_PASSWORD=also-change-me purffle-shorts studio --host 0.0.0.0 --no-browser
```

Don't expose it to the internet without `STUDIO_PASSWORD`, and put HTTPS in front of it (a reverse
proxy such as Caddy) if it leaves your network.

## Jobs

Making, clipping, planning and uploading run as **jobs**, one at a time, in the order they were sent.
A `POST` returns `{"job": <id>}` at once. Then either poll `GET /api/jobs/<id>`, or listen to
`GET /api/events`, a Server-Sent Events stream that sends the job list whenever anything changes.

```json
{"id": 7, "kind": "make", "label": "why cats purr", "status": "running", "stage": "render", "pct": 72,
 "message": "1080x1920", "eta": 21.4, "result": {}, "log": ["…"]}
```

`status` is `queued`, `running`, `done`, `failed` or `cancelled`. When it is `done`, `result` holds the
outcome. For a video that is `{"ok": true, "id": 12, "title": "…", "status": "rendered", "score": 84,
"youtube_id": null, …}`. `id` is the library id used by the file and upload endpoints.

## Endpoints

| Method and path | Body / query | What it does |
|---|---|---|
| `POST /api/make` | see below | Make a video (job). |
| `POST /api/draft` | same fields as make | Write and review a script without rendering (job). `result.script` is the script JSON. |
| `POST /api/clip` | `source`, `count`, `crop`, `brief`, `jump_cuts`, `zoom`, `min_seconds`, `max_seconds`, `upload` | Clip a long video into Shorts (job). `result.clips` lists each clip with its virality `score` and `reason`. |
| `POST /api/plan` | `count`, `niche` | Add AI-planned ideas to the queue (job). |
| `POST /api/upload/<id>` | | Publish or schedule a rendered video to YouTube and the networks in `PUBLISH_TO` (job). Sending it again only retries what didn't go out; `metadata.json` (`GET /api/videos/<id>`) has each network's result under `published`. |
| `POST /api/jobs/<id>/cancel` | | Cancel a queued job, or stop the running one. |
| `POST /api/ideas` | `subject`, `style`, `notes` | Queue an idea. |
| `POST /api/ideas/<id>/delete` | | Remove an idea. |
| `POST /api/videos/<id>/delete` | | Remove a video from the library and delete its folder (never touches YouTube). |
| `POST /api/stats` | | Refresh YouTube view counts (job). |
| `GET /api/jobs` · `/api/jobs/<id>` | | Recent jobs; one job with its full log. |
| `GET /api/events` | | Server-Sent Events: `event: jobs` with the job list. |
| `GET /api/videos` | `?status=rendered&q=octopus` | The library. |
| `GET /api/videos/<id>` | | One video with its metadata and script. |
| `GET /files/<id>/<name>` | `?download=1` | `short.mp4` (or `video.mp4` for 16:9), `cover.jpg`, `captions.srt`, `metadata.json`, `script.json`. |
| `GET /api/info` · `/api/options` · `/api/doctor` · `/api/channel` · `/api/ideas` · `/api/voices?lang=es` | | Settings summary, form choices (including background videos), self-check, channel stats, idea queue, voices. |

### `POST /api/make` fields

Every field is optional. Anything left out uses your `.env`.

| Field | Example | Meaning |
|---|---|---|
| `topic` | `"why cats purr"` | What the video is about. Empty: the next queued idea, or a fresh topic from your niches. |
| `url` | `"https://…"` | Make it from a web page or a Reddit post. |
| `source` | `"queue"` | Take the next idea from the queue. |
| `script` | `{…}` | A script (from `/api/draft`, edited or not) to render exactly as written. |
| `style` | `"chat"` | facts, story, listicle, myth, quiz, explainer, motivational, news, dialogue, chat, reddit. |
| `language`, `duration`, `aspect` | `"es"`, `45`, `"9:16"` | Language code, target seconds (10–170), 9:16 / 16:9 / 1:1 / 4:5. |
| `caption_style`, `caption_position`, `grade`, `transition` | `"neon"`, `"center"`, `"vivid"`, `"fade"` | The look. |
| `tts`, `voice`, `voice_b` | `"edge"`, `"en-US-AndrewNeural"` | Voice engine and voices. |
| `provider`, `model`, `review` | `"gemini"`, `""`, `"rewrite"` | AI model and Script Doctor mode (off, score, rewrite). |
| `visuals` | `["pexels", "pixabay"]` | Footage sources. |
| `background`, `layout` | `"media/backgrounds/parkour.mp4"`, `"split"` | A video to play under the whole story: `full` (it is the picture) or `split` (footage on top). |
| `music`, `sfx`, `emphasis` | `true` | Background music, sound effects, key words highlighted in colour. |
| `also_langs` | `"es,hi"` | Also make translated copies. |
| `upload` | `true` | Publish when done, to YouTube and the networks in `PUBLISH_TO` (only if `UPLOAD=true` in `.env`). `result.posts` has each network's status and link. |
| `offline` | `true` | Demo mode: no keys, sample script, generated backgrounds. |

## Examples

```bash
TOKEN=change-me
# make a video and wait for it
JOB=$(curl -s -X POST localhost:8765/api/make -H "X-Studio-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"topic": "why octopuses have three hearts", "style": "facts", "duration": 35}' | jq .job)
until curl -s localhost:8765/api/jobs/$JOB | jq -e '.status | test("done|failed|cancelled")' >/dev/null; do sleep 5; done
ID=$(curl -s localhost:8765/api/jobs/$JOB | jq .result.id)
curl -s -o short.mp4 "localhost:8765/files/$ID/short.mp4"

# clip the funniest moments of a podcast, with jump cuts and face framing
curl -s -X POST localhost:8765/api/clip -H "X-Studio-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"source": "/videos/episode-12.mp4", "count": 4, "crop": "face", "brief": "the funniest moments"}'
```

```python
import time, requests

S = requests.Session()
S.headers["X-Studio-Token"] = "change-me"
job = S.post("http://127.0.0.1:8765/api/make", json={"topic": "the loudest animal on Earth"}).json()["job"]
while (j := S.get(f"http://127.0.0.1:8765/api/jobs/{job}").json())["status"] in ("queued", "running"):
    print(j["stage"], j["pct"], "%", j["eta"])
    time.sleep(3)
print(j["result"])
```

## n8n recipe: a Short from every new RSS item

1. **RSS Feed Trigger** on your blog or a news feed.
2. **HTTP Request**: `POST http://<studio-host>:8765/api/make`, header `X-Studio-Token`, Basic auth with
   `STUDIO_PASSWORD`, JSON body `{"url": "{{$json.link}}", "upload": false}`. Save `{{$json.job}}`.
3. **Wait** 60 s, then **HTTP Request** `GET /api/jobs/{{job}}` in a loop (an **If** on `status`) until it
   is `done` or `failed`.
4. On `done`: send `http://<studio-host>:8765/files/{{result.id}}/short.mp4` to Telegram, Slack or Google
   Drive for review, or call `POST /api/upload/{{result.id}}` to publish it.

The same pattern works for a Google Sheet of topics (`{"topic": …}`), a form, or a schedule.
