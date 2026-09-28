"""Instagram: container -> poll -> publish. Requires a public media URL (R2)."""
import time
from ..lib.util import LOG, ApiError, http, env
from .base import PublishResult

GRAPH = "https://graph.facebook.com/v21.0"


def publish(job, content, account, text, media, spec, publish_at=None, staged_url=None):
    if not staged_url:
        raise ApiError(400, "instagram requires a staged public URL", "ig.setup")
    ig_id = account["platform_id"]
    token = env("META_SYSTEM_TOKEN")

    # 0) respect the platform's own daily counter before spending an upload
    try:
        q = http("GET", f"{GRAPH}/{ig_id}/content_publishing_limit",
                 params={"fields": "quota_usage,config", "access_token": token},
                 where="ig.quota").json()
        d = (q.get("data") or [{}])[0]
        used, total = d.get("quota_usage", 0), (d.get("config") or {}).get("quota_total", 50)
        LOG.info("IG %s quota %s/%s", ig_id, used, total)
        if used >= total:
            raise ApiError(429, '{"error":{"code":2207042}}', "ig.quota")
    except ApiError as e:
        if e.klass == "RATE_LIMIT":
            raise

    # 1) create the container
    data = {"access_token": token, "caption": text.get("caption", "")}
    if content["content_type"] == "video":
        data.update({"media_type": "REELS", "video_url": staged_url,
                     "share_to_feed": "true"})
    else:
        data["image_url"] = staged_url
    cid = http("POST", f"{GRAPH}/{ig_id}/media", data=data,
               where="ig.container").json()["id"]
    job["_external_ref"] = cid

    # 2) wait for Instagram to finish downloading + transcoding
    for _ in range(40):                              # up to ~5 minutes
        time.sleep(8)
        st = http("GET", f"{GRAPH}/{cid}",
                  params={"fields": "status_code,status", "access_token": token},
                  where="ig.container.status").json()
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise ApiError(400, str(st), "ig.container.error")
    else:
        raise ApiError(None, "container never finished", "ig.container.timeout")

    # 3) publish
    pid = http("POST", f"{GRAPH}/{ig_id}/media_publish",
               data={"creation_id": cid, "access_token": token},
               where="ig.publish").json()["id"]
    return PublishResult(pid, "published")


def verify(job, account):
    token = env("META_SYSTEM_TOKEN")
    ig_id = account["platform_id"]
    try:
        media = http("GET", f"{GRAPH}/{ig_id}/media",
                     params={"fields": "id,caption,timestamp", "limit": 10,
                             "access_token": token}, where="ig.verify").json()
        want = (job.get("_caption") or "")[:60]
        for m in media.get("data", []):
            if want and want in (m.get("caption") or ""):
                return m["id"]
    except ApiError:
        pass
    return None
