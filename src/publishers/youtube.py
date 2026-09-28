"""YouTube Shorts: resumable upload with native scheduling via publishAt.
Remember: until your Cloud project passes the API audit, uploads are locked private."""
import json, pathlib
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from ..lib.util import LOG, ApiError, env, iso
from .base import PublishResult

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _service(account):
    key = (account.get("token_ref") or "").split(":")[-1] or account["account_key"]
    store = json.loads(env("YOUTUBE_TOKENS_JSON"))
    entry = store.get(key)
    if not entry:
        raise ApiError(401, f"no YouTube token stored for '{key}'", "yt.token")
    creds = Credentials(
        None, refresh_token=entry["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=env("GOOGLE_OAUTH_CLIENT_ID"),
        client_secret=env("GOOGLE_OAUTH_CLIENT_SECRET"), scopes=SCOPES)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def publish(job, content, account, text, media: pathlib.Path, spec, publish_at=None):
    if content["content_type"] != "video":
        raise ApiError(400, "youtube accepts video only in this system", "yt.unsupported")
    yt = _service(account)
    status = {"selfDeclaredMadeForKids": False}
    if publish_at:
        status.update({"privacyStatus": "private", "publishAt": iso(publish_at)})
    else:
        status["privacyStatus"] = "public"
    body = {"snippet": {"title": (text.get("title") or "Short")[:100],
                        "description": text.get("description", "")[:5000],
                        "categoryId": "22"},
            "status": status}
    try:
        req = yt.videos().insert(
            part="snippet,status", body=body,
            media_body=MediaFileUpload(str(media), chunksize=8 * 1024 * 1024,
                                       resumable=True))
        resp = None
        while resp is None:
            _, resp = req.next_chunk()
    except Exception as e:
        raise ApiError(getattr(e, "status_code", 400), str(e), "yt.insert")
    vid = resp["id"]
    return PublishResult(vid, "scheduled" if publish_at else "public", bool(publish_at))


def verify(job, account):
    ref = job.get("external_ref")
    if not ref:
        return None
    try:
        r = _service(account).videos().list(part="status", id=ref).execute()
        return ref if r.get("items") else None
    except Exception:
        return None
