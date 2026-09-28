"""TikTok: draft-to-inbox (no audit needed) or direct post (audit required).
Mode comes from platform_specs.mode in the Cockpit: draft | direct."""
import json, pathlib
from ..lib.util import LOG, ApiError, http, env
from .base import PublishResult

API = "https://open.tiktokapis.com/v2"
CHUNK = 10 * 1024 * 1024


def _tokens() -> dict:
    return json.loads(env("TIKTOK_TOKENS_JSON"))


def _access_token(account) -> str:
    """Refresh on every run: TikTok access tokens live ~24h."""
    key = (account.get("token_ref") or "").split(":")[-1] or account["account_key"]
    entry = _tokens().get(key)
    if not entry:
        raise ApiError(401, f"no TikTok token stored for '{key}'", "tt.token")
    r = http("POST", f"{API}/oauth/token/",
             data={"client_key": env("TIKTOK_CLIENT_KEY"),
                   "client_secret": env("TIKTOK_CLIENT_SECRET"),
                   "grant_type": "refresh_token",
                   "refresh_token": entry["refresh_token"]},
             headers={"Content-Type": "application/x-www-form-urlencoded"},
             where="tt.refresh")
    return r.json()["access_token"]


def publish(job, content, account, text, media: pathlib.Path, spec, publish_at=None):
    if content["content_type"] != "video":
        raise ApiError(400, "tiktok photo posting is not enabled in this system",
                       "tt.unsupported")
    token = _access_token(account)
    hdr = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    size = media.stat().st_size
    chunk = min(CHUNK, size)
    total_chunks = max(1, -(-size // chunk))
    source = {"source": "FILE_UPLOAD", "video_size": size,
              "chunk_size": chunk, "total_chunk_count": total_chunks}
    mode = (spec.get("mode") or "draft").lower()

    if mode == "direct":
        info = http("POST", f"{API}/post/publish/creator_info/query/", headers=hdr,
                    where="tt.creator_info").json().get("data", {})
        allowed = info.get("privacy_level_options", [])
        level = "PUBLIC_TO_EVERYONE" if "PUBLIC_TO_EVERYONE" in allowed else \
                (allowed[0] if allowed else "SELF_ONLY")
        body = {"post_info": {"title": text.get("caption", "")[:2200],
                              "privacy_level": level,
                              "disable_comment": False,
                              "video_cover_timestamp_ms": 1000},
                "source_info": source}
        init = http("POST", f"{API}/post/publish/video/init/", json=body, headers=hdr,
                    where="tt.direct.init").json()["data"]
    else:
        body = {"source_info": source,
                "post_info": {"title": text.get("caption", "")[:2200]}}
        init = http("POST", f"{API}/post/publish/inbox/video/init/", json=body,
                    headers=hdr, where="tt.inbox.init").json()["data"]

    publish_id, upload_url = init["publish_id"], init["upload_url"]
    job["_external_ref"] = publish_id

    with open(media, "rb") as fh:
        for i in range(total_chunks):
            start = i * chunk
            data = fh.read(chunk)
            end = start + len(data) - 1
            http("PUT", upload_url, data=data, where=f"tt.upload[{i}]", tries=2,
                 headers={"Content-Range": f"bytes {start}-{end}/{size}",
                          "Content-Length": str(len(data)),
                          "Content-Type": "video/mp4"})

    note = ("posted directly" if mode == "direct"
            else "sent to TikTok inbox - open the app to finish posting")
    return PublishResult(publish_id, note, scheduled=(mode != "direct"))


def verify(job, account):
    ref = job.get("external_ref")
    if not ref:
        return None
    try:
        token = _access_token(account)
        r = http("POST", f"{API}/post/publish/status/fetch/",
                 json={"publish_id": ref},
                 headers={"Authorization": f"Bearer {token}",
                          "Content-Type": "application/json"},
                 where="tt.verify").json().get("data", {})
        if r.get("status") in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"):
            return ref
    except ApiError:
        pass
    return None
