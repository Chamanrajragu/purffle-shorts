"""YouTube Data API v3: OAuth (token.json), resumable uploads with retries, scheduled publishing,
AI-content disclosure, playlists and quota awareness."""

from __future__ import annotations

import logging
import os
import pickle
import random
import threading
import time
from datetime import datetime, timedelta, timezone
from datetime import time as dtime
from pathlib import Path

from .config import Settings

log = logging.getLogger("purffle")

SCOPE_UPLOAD = "https://www.googleapis.com/auth/youtube.upload"
SCOPE_MANAGE = "https://www.googleapis.com/auth/youtube"
SCOPE_READONLY = "https://www.googleapis.com/auth/youtube.readonly"
SCOPE_CAPTIONS = "https://www.googleapis.com/auth/youtube.force-ssl"  # captions.insert needs this one
RETRY_STATUS = {500, 502, 503, 504}

_lock = threading.Lock()


class QuotaExceeded(RuntimeError):
    pass


class NotAuthorized(RuntimeError):
    pass


def scopes_for(settings: Settings) -> list[str]:
    return [SCOPE_UPLOAD] + ([SCOPE_MANAGE] if settings.playlist_id else [])


def auth_scopes(settings: Settings) -> list[str]:
    """Everything the current settings will need; asked for once by the `auth` command."""
    extra = [SCOPE_READONLY] if settings.learn_from_stats and not settings.youtube_api_key else []
    if settings.upload_captions:
        extra.append(SCOPE_CAPTIONS)
    return scopes_for(settings) + extra


def _load_legacy_pickle():
    """PurffleShorts 1.x stored credentials in token.pickle; migrate them once to token.json."""
    p = Path("token.pickle")
    if not p.exists():
        return None
    try:
        with open(p, "rb") as f:
            return pickle.load(f)  # file written by this app on this machine
    except Exception as e:
        log.warning("Could not read legacy token.pickle: %s", e)
        return None


def get_credentials(settings: Settings, interactive: bool = True, extra_scopes: list[str] | None = None):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    scopes = list(dict.fromkeys(scopes_for(settings) + list(extra_scopes or [])))
    token = Path(settings.token_file)
    creds = None
    if token.exists():
        creds = Credentials.from_authorized_user_file(str(token))
    else:
        creds = _load_legacy_pickle()
    if creds is not None and not creds.has_scopes(scopes):
        log.info("Saved YouTube authorization lacks required scopes; asking again")
        creds = None
    if creds is not None and not creds.valid and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as e:
            log.warning("Refreshing YouTube token failed (%s); re-authorization needed", e)
            creds = None
    if creds is None or not creds.valid:
        if not interactive:
            raise NotAuthorized("YouTube is not authorized (or needs a new permission). Run:  purffle-shorts auth")
        secrets = Path(settings.client_secrets)
        if not secrets.exists():
            raise NotAuthorized(
                f"{secrets} not found. Create an OAuth client (Desktop app) in Google Cloud Console with the "
                "YouTube Data API v3 enabled, download its JSON as credentials.json, then run the auth command.")
        flow = InstalledAppFlow.from_client_secrets_file(str(secrets), scopes)
        creds = flow.run_local_server(port=0, prompt="consent")
    token.write_text(creds.to_json())
    try:
        os.chmod(token, 0o600)
    except OSError:
        pass
    return creds


def service(settings: Settings, interactive: bool = True, extra_scopes: list[str] | None = None):
    from googleapiclient.discovery import build
    creds = get_credentials(settings, interactive, extra_scopes)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _tz(settings: Settings):
    if settings.timezone:
        from zoneinfo import ZoneInfo
        return ZoneInfo(settings.timezone)
    return datetime.now().astimezone().tzinfo


def next_publish_slot(settings: Settings, taken: list[str], now: datetime | None = None) -> datetime | None:
    """Next free PUBLISH_TIMES slot (local time) at least 15 minutes from now, skipping taken ones."""
    if not settings.publish_times:
        return None
    tz = _tz(settings)
    now = (now or datetime.now(timezone.utc)).astimezone(tz)
    slots = []
    for t in settings.publish_times:
        try:
            hh, mm = (int(x) for x in t.split(":"))
            slots.append(dtime(hh, mm))
        except ValueError:
            log.warning("Ignoring bad PUBLISH_TIMES entry %r (use HH:MM)", t)
    taken_set = {x for x in taken if x}
    for day in range(0, 60):
        date = (now + timedelta(days=day)).date()
        for slot in sorted(slots):
            cand = datetime.combine(date, slot, tzinfo=tz)
            if cand < now + timedelta(minutes=15):
                continue
            iso = to_rfc3339(cand)
            if iso not in taken_set:
                return cand
    return None


def to_rfc3339(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_body(settings: Settings, title: str, description: str, tags: list[str], category_id: str,
               language: str, publish_at: datetime | None = None,
               localizations: dict[str, dict] | None = None) -> dict:
    status = {
        "privacyStatus": "private" if publish_at else settings.privacy,
        "selfDeclaredMadeForKids": settings.made_for_kids,
        "embeddable": True,
    }
    if settings.synthetic_media:
        status["containsSyntheticMedia"] = True
    if publish_at:
        status["publishAt"] = to_rfc3339(publish_at)
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:4900],
            "tags": tags,
            "categoryId": category_id,
            "defaultLanguage": language,
            "defaultAudioLanguage": language,
        },
        "status": status,
    }
    loc = {k: {"title": v["title"][:100], "description": v.get("description", "")[:4900]}
           for k, v in (localizations or {}).items() if k != language and v.get("title")}
    if loc:  # viewers whose YouTube is in one of these languages see the title and description in it
        body["localizations"] = loc
    return body


def upload(settings: Settings, video: Path, body: dict) -> dict:
    """Resumable upload with exponential backoff. Returns the API video resource."""
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    with _lock:  # one upload at a time; the API client is not thread-safe
        yt = service(settings, interactive=False)
        media = MediaFileUpload(str(video), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
        parts = "snippet,status" + (",localizations" if body.get("localizations") else "")
        request = yt.videos().insert(part=parts, body=body, media_body=media)
        response, retry, last_pct = None, 0, -1
        while response is None:
            try:
                status, response = request.next_chunk()
                if status:
                    pct = int(status.progress() * 100)
                    if pct >= last_pct + 25:
                        log.info("Upload %d%%", pct)
                        last_pct = pct
            except HttpError as e:
                text = str(e)
                # quotaExceeded comes as a 403 and uploadLimitExceeded as a 400; both clear at midnight Pacific
                if "quotaExceeded" in text or "uploadLimitExceeded" in text:
                    raise QuotaExceeded(text) from e
                if e.resp.status not in RETRY_STATUS:
                    raise
                retry += 1
            except (ConnectionError, TimeoutError, OSError) as e:
                log.warning("Upload connection error: %s", e)
                retry += 1
            else:
                continue
            if retry > 8:
                raise RuntimeError("Upload failed after 8 retries")
            wait = min(64, 2 ** retry) + random.random()
            log.warning("Upload retry %d in %.0fs", retry, wait)
            time.sleep(wait)

        if settings.playlist_id and response.get("id"):
            try:
                yt.playlistItems().insert(part="snippet", body={"snippet": {
                    "playlistId": settings.playlist_id,
                    "resourceId": {"kind": "youtube#video", "videoId": response["id"]}}}).execute()
            except Exception as e:
                log.warning("Could not add video to playlist %s: %s", settings.playlist_id, e)
        return response


def upload_captions(settings: Settings, video_id: str, srt: Path, language: str, name: str = "") -> bool:
    """Add the video's own subtitles as a caption track (400 quota units). Exact captions help YouTube
    search and viewers who watch with the sound off. Skipped, with a hint, when the saved authorization
    predates UPLOAD_CAPTIONS."""
    from googleapiclient.http import MediaFileUpload
    if not srt.exists() or not srt.read_text(encoding="utf-8").strip():
        return False
    try:
        with _lock:
            yt = service(settings, interactive=False, extra_scopes=[SCOPE_CAPTIONS])
            yt.captions().insert(
                part="snippet",
                body={"snippet": {"videoId": video_id, "language": language, "name": name or language,
                                  "isDraft": False}},
                media_body=MediaFileUpload(str(srt), mimetype="application/octet-stream", resumable=False),
            ).execute()
    except NotAuthorized:
        log.warning("Caption upload skipped: run `purffle-shorts auth` once more to allow it")
        return False
    except Exception as e:
        log.warning("Caption upload failed: %s", e)
        return False
    log.info("Captions uploaded (%s)", language)
    return True
