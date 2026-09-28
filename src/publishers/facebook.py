"""Facebook Pages: Reels (3-phase upload) + photos. Supports native scheduling."""
import pathlib, time
from ..lib.util import LOG, ApiError, http, env
from .base import PublishResult

GRAPH = "https://graph.facebook.com/v21.0"


def _page_token(page_id: str) -> str:
    """Derive a Page token from the system-user token. Never stored anywhere."""
    sys_token = env("META_SYSTEM_TOKEN")
    r = http("GET", f"{GRAPH}/{page_id}",
             params={"fields": "access_token", "access_token": sys_token},
             where="fb.page_token")
    tok = r.json().get("access_token")
    if not tok:
        raise ApiError(403, r.text, "fb.page_token(empty)")
    return tok


def publish(job, content, account, text, media: pathlib.Path, spec, publish_at=None):
    page_id = account["platform_id"]
    token = _page_token(page_id)
    if content["content_type"] == "image":
        return _photo(page_id, token, text, media, publish_at)
    return _reel(page_id, token, text, media, publish_at, job)


def _reel(page_id, token, text, media, publish_at, job):
    # Phase 1: open an upload session
    r = http("POST", f"{GRAPH}/{page_id}/video_reels",
             data={"upload_phase": "start", "access_token": token},
             where="fb.reel.start")
    j = r.json()
    video_id, upload_url = j["video_id"], j["upload_url"]
    job["_external_ref"] = video_id          # caller persists this BEFORE finishing

    # Phase 2: send the bytes
    size = media.stat().st_size
    with open(media, "rb") as fh:
        http("POST", upload_url,
             headers={"Authorization": f"OAuth {token}",
                      "offset": "0",
                      "file_size": str(size)},
             data=fh, where="fb.reel.upload", tries=2)

    # Phase 3: finish - published now, or handed to Facebook's scheduler
    payload = {"upload_phase": "finish", "video_id": video_id,
               "description": text.get("caption", ""), "access_token": token}
    if text.get("title"):
        payload["title"] = text["title"]
    if publish_at:
        payload["video_state"] = "SCHEDULED"
        payload["scheduled_publish_time"] = str(int(publish_at.timestamp()))
    else:
        payload["video_state"] = "PUBLISHED"
    http("POST", f"{GRAPH}/{page_id}/video_reels", data=payload, where="fb.reel.finish")

    if publish_at:
        return PublishResult(video_id, f"scheduled {publish_at:%Y-%m-%d %H:%M} UTC", True)

    # Poll processing so a broken file is reported now, not silently
    for _ in range(10):
        time.sleep(6)
        st = http("GET", f"{GRAPH}/{video_id}",
                  params={"fields": "status", "access_token": token},
                  where="fb.reel.status").json().get("status", {})
        if st.get("video_status") in ("ready", "published"):
            return PublishResult(video_id, "published")
        if st.get("video_status") == "error":
            raise ApiError(400, str(st), "fb.reel.processing")
    return PublishResult(video_id, "accepted, still processing")


def _photo(page_id, token, text, media, publish_at):
    data = {"caption": text.get("caption", ""), "access_token": token}
    if publish_at:
        data["published"] = "false"
        data["scheduled_publish_time"] = str(int(publish_at.timestamp()))
    with open(media, "rb") as fh:
        r = http("POST", f"{GRAPH}/{page_id}/photos", data=data,
                 files={"source": fh}, where="fb.photo")
    pid = r.json().get("post_id") or r.json().get("id")
    return PublishResult(pid, "scheduled" if publish_at else "published", bool(publish_at))


def verify(job, account):
    """IN_DOUBT recovery: does the video exist on the Page?"""
    ref = job.get("external_ref")
    if not ref:
        return None
    try:
        token = _page_token(account["platform_id"])
        j = http("GET", f"{GRAPH}/{ref}",
                 params={"fields": "id,status,permalink_url", "access_token": token},
                 where="fb.verify").json()
        return j.get("id")
    except ApiError:
        return None
