"""Publishing to TikTok, Instagram Reels and other networks besides YouTube:

    PUBLISH_TO=youtube,tiktok,instagram

Two ways to get there:

  * Upload-Post (upload-post.com), a relay that holds each network's sign-in: create a profile in its
    dashboard, connect TikTok, Instagram and the rest to it, and set UPLOAD_POST_API_KEY and
    UPLOAD_POST_USER (the profile's name). TikTok only lets audited apps publish public videos through
    its own API, so TikTok always goes this way. Upload-Post's free plan doesn't include TikTok.
  * The official Instagram API, free, for Instagram only: INSTAGRAM_USER_ID and INSTAGRAM_ACCESS_TOKEN
    from a Meta app with Facebook Login for Business (permission instagram_content_publish). The video
    is sent straight from this computer with a resumable upload; no public URL is needed.

Posting never stops a video: each network gets its own result (posted, scheduled, submitted, draft,
failed or skipped), saved in the video's metadata.json, and a later `upload --id N` only retries what
did not go out.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings
from .utils import Cancelled, check_cancel, http, redact

log = logging.getLogger("purffle")

PLATFORMS = ("youtube", "tiktok", "instagram", "facebook", "threads", "x", "linkedin", "bluesky", "pinterest")
RELAYED = set(PLATFORMS) - {"youtube"}
NAMES = {"youtube": "YouTube", "tiktok": "TikTok", "instagram": "Instagram", "facebook": "Facebook",
         "threads": "Threads", "x": "X", "linkedin": "LinkedIn", "bluesky": "Bluesky", "pinterest": "Pinterest"}
UPLOAD_POST = "https://api.upload-post.com/api"
# The longest caption each network takes (characters).
CAPTION_LIMIT = {"x": 280, "bluesky": 300, "threads": 500, "pinterest": 500}
TIKTOK_PRIVACY = ("PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY")
DONE = {"posted", "scheduled", "submitted", "draft"}   # nothing more to do for these


@dataclass
class Post:
    platform: str
    status: str                 # posted | scheduled | submitted | draft | failed | skipped
    url: str = ""
    id: str = ""
    error: str = ""
    at: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v and k != "platform"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def caption(meta: dict, platform: str = "") -> str:
    """The post text: the title, then the description with its hashtags and credits. "#shorts" means
    nothing outside YouTube, so it is dropped."""
    title = re.sub(r"\s*#shorts\b", "", str(meta.get("title") or ""), flags=re.I).strip()
    desc = re.sub(r"(?<!\w)#shorts\b[ \t]*", "", str(meta.get("description") or ""), flags=re.I).strip()
    text = f"{title}\n\n{desc}".strip() if desc else title
    limit = CAPTION_LIMIT.get(platform, 2200)
    if len(text) <= limit:
        return text
    return text[:limit - 1].rsplit(" ", 1)[0].rstrip(" ,.;:") + "…"


def routes(settings: Settings, platforms: list[str]) -> tuple[bool, list[str]]:
    """(Instagram goes direct, the platforms that go through Upload-Post)."""
    direct = "instagram" in platforms and bool(settings.instagram_user_id and settings.instagram_access_token)
    relay = [p for p in platforms if p in RELAYED and not (p == "instagram" and direct)]
    return direct, relay


def publish(settings: Settings, video: Path, meta: dict, platforms: list[str],
            when: datetime | None = None) -> dict[str, Post]:
    """Post ``video`` to each platform (YouTube is handled elsewhere). ``when``: the publish slot, used
    where the route can schedule (Upload-Post); Instagram's own API can only post right away."""
    platforms = [p for p in dict.fromkeys(platforms) if p in RELAYED]
    out: dict[str, Post] = {}
    direct, relay = routes(settings, platforms)
    if direct:
        if when is not None:
            log.info("Instagram's own API can't schedule: posting the Reel now")
        out["instagram"] = _guard("instagram", lambda: instagram_direct(settings, video, caption(meta, "instagram"),
                                                                         meta.get("cover_at")))
    if relay:
        if not (settings.upload_post_api_key and settings.upload_post_user):
            for p in relay:
                out[p] = Post(p, "skipped", error="set UPLOAD_POST_API_KEY and UPLOAD_POST_USER to post here",
                              at=_now())
        else:
            try:
                out.update(upload_post(settings, video, meta, relay, when))
            except Cancelled:
                raise
            except Exception as e:  # one failure for the whole request: every platform in it failed
                msg = redact(e)
                out.update({p: Post(p, "failed", error=msg, at=_now()) for p in relay})
    for p in out.values():
        level = logging.INFO if p.status in DONE else logging.WARNING
        log.log(level, "%s: %s%s", NAMES.get(p.platform, p.platform), p.status,
                f" {p.url}" if p.url else (f" ({p.error})" if p.error else ""))
    return out


def _guard(platform: str, fn) -> Post:
    try:
        return fn()
    except Cancelled:
        raise
    except Exception as e:
        return Post(platform, "failed", error=redact(e), at=_now())


# ------------------------------------------------------------------------------------------ Upload-Post
def _error_text(r) -> str:
    try:
        data = r.json()
        msg = data.get("message") or data.get("error") or json.dumps(data)[:200]
    except ValueError:
        msg = r.text[:200]
    hint = {401: "check UPLOAD_POST_API_KEY", 403: "your Upload-Post plan doesn't allow this (TikTok needs a paid "
            "plan)", 404: "no Upload-Post profile called UPLOAD_POST_USER", 429: "Upload-Post's monthly limit "
            "is used up"}.get(r.status_code, "")
    return f"Upload-Post HTTP {r.status_code}: {msg}" + (f" — {hint}" if hint else "")


def upload_post(settings: Settings, video: Path, meta: dict, platforms: list[str], when: datetime | None = None,
                *, poll_seconds: float = 180, poll_every: float = 10) -> dict[str, Post]:
    title = re.sub(r"\s*#shorts\b", "", str(meta.get("title") or ""), flags=re.I).strip()
    data: list[tuple[str, str]] = [("user", settings.upload_post_user), ("title", title), ("async_upload", "true")]
    data += [("platform[]", p) for p in platforms]
    data += [(f"{p}_title", caption(meta, p)) for p in platforms]
    if "tiktok" in platforms and settings.tiktok_privacy:
        data.append(("privacy_level", settings.tiktok_privacy))
    if "instagram" in platforms and meta.get("cover_at") is not None:
        data.append(("thumb_offset", str(int(float(meta["cover_at"]) * 1000))))
    if when is not None:
        data.append(("scheduled_date", when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
    # the same video to the same networks is only ever accepted once, even if this request is retried
    key = f"purffle-{meta.get('created_at', '')}-{video.parent.name}-{'-'.join(platforms)}"[:200]
    headers = {"Authorization": f"Apikey {settings.upload_post_api_key}", "Idempotency-Key": key}
    with open(video, "rb") as f:
        r = http().post(f"{UPLOAD_POST}/upload", data=data, files={"video": (video.name, f, "video/mp4")},
                        headers=headers, timeout=900)
    if r.status_code >= 400:
        raise RuntimeError(_error_text(r))
    body = r.json()
    if r.status_code == 202 or body.get("job_id"):
        return {p: Post(p, "scheduled", id=str(body.get("job_id") or ""), at=_now()) for p in platforms}
    if isinstance(body.get("results"), dict):
        return _results(body["results"], platforms)
    rid = body.get("request_id")
    if not rid:
        raise RuntimeError(f"Upload-Post answered without results: {json.dumps(body)[:200]}")
    deadline = time.monotonic() + poll_seconds
    last: dict = {}
    while time.monotonic() < deadline:
        check_cancel()
        time.sleep(poll_every)
        s = http().get(f"{UPLOAD_POST}/uploadposts/status", params={"request_id": rid},
                       headers={"Authorization": headers["Authorization"]}, timeout=30)
        if s.status_code >= 400:
            continue
        last = s.json()
        if last.get("status") in ("completed", "failed"):
            break
    results = {str(x.get("platform")): x for x in last.get("results") or [] if isinstance(x, dict)}
    out = _results(results, platforms, pending_id=str(rid))
    if last.get("status") == "failed":
        for p in platforms:
            if out[p].status == "submitted":
                out[p] = Post(p, "failed", error=str(last.get("message") or "Upload-Post reported a failure"),
                              at=_now())
    return out


def _results(results: dict, platforms: list[str], pending_id: str = "") -> dict[str, Post]:
    out = {}
    for p in platforms:
        x = results.get(p)
        if not isinstance(x, dict):
            # still on its way at Upload-Post: it goes out without us
            out[p] = Post(p, "submitted", id=pending_id, at=_now())
        elif x.get("skipped"):
            out[p] = Post(p, "skipped", error=str(x.get("skip_reason") or "not connected in Upload-Post"),
                          at=_now())
        elif x.get("success"):
            status = "draft" if x.get("fallback_to_inbox") else "posted"
            out[p] = Post(p, status, url=str(x.get("url") or ""),
                          id=str(x.get("post_id") or x.get("publish_id") or x.get("container_id") or ""),
                          error="sent to the TikTok inbox: open TikTok to publish it" if status == "draft" else "",
                          at=_now())
        else:
            out[p] = Post(p, "failed", error=str(x.get("error") or x.get("message") or "failed"), at=_now())
    return out


# ------------------------------------------------------------------------------------------ Instagram API
def instagram_direct(settings: Settings, video: Path, text: str, cover_at: float | None = None, *,
                     poll_seconds: float = 300, poll_every: float = 5) -> Post:
    """A Reel through the official Instagram API: make a container, send the file to it (resumable
    upload, no public URL needed), wait until Instagram has processed it, then publish it."""
    api = f"https://graph.facebook.com/{settings.instagram_api_version}"
    auth = {"Authorization": f"OAuth {settings.instagram_access_token}"}
    params = {"media_type": "REELS", "upload_type": "resumable", "caption": text}
    if cover_at is not None:
        params["thumb_offset"] = str(int(float(cover_at) * 1000))
    r = http().post(f"{api}/{settings.instagram_user_id}/media", params=params, headers=auth, timeout=60)
    _ig_check(r, "create the Reel")
    container = r.json()
    cid, uri = str(container["id"]), container.get("uri") or f"https://rupload.facebook.com/ig-api-upload/" \
        f"{settings.instagram_api_version}/{container['id']}"
    size = video.stat().st_size
    with open(video, "rb") as f:
        r = http().post(uri, headers={**auth, "offset": "0", "file_size": str(size)}, data=f, timeout=900)
    _ig_check(r, "upload the video")
    deadline = time.monotonic() + poll_seconds
    status = ""
    while time.monotonic() < deadline:
        check_cancel()
        s = http().get(f"{api}/{cid}", params={"fields": "status_code,status"}, headers=auth, timeout=30)
        _ig_check(s, "check the Reel")
        status = str(s.json().get("status_code") or "")
        if status in ("FINISHED", "PUBLISHED"):
            break
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram couldn't process the video ({status}: {s.json().get('status', '')})")
        time.sleep(poll_every)
    else:
        return Post("instagram", "submitted", id=cid, error="still processing at Instagram; it was not published",
                    at=_now())
    r = http().post(f"{api}/{settings.instagram_user_id}/media_publish", params={"creation_id": cid},
                    headers=auth, timeout=60)
    _ig_check(r, "publish the Reel")
    media_id = str(r.json().get("id") or "")
    url = ""
    try:
        p = http().get(f"{api}/{media_id}", params={"fields": "permalink"}, headers=auth, timeout=30)
        url = str(p.json().get("permalink") or "") if p.status_code < 400 else ""
    except Exception:  # the post is out; a missing link is not worth failing over
        pass
    return Post("instagram", "posted", url=url, id=media_id, at=_now())


def _ig_check(r, what: str) -> None:
    if r.status_code < 400:
        return
    try:
        err = r.json().get("error") or {}
        msg = err.get("error_user_msg") or err.get("message") or r.text[:200]
    except ValueError:
        msg = r.text[:200]
    hint = " — check INSTAGRAM_ACCESS_TOKEN (it may have expired)" if r.status_code in (401, 403) or \
        "token" in str(msg).lower() else ""
    raise RuntimeError(f"Instagram couldn't {what}: HTTP {r.status_code} {msg}{hint}")
