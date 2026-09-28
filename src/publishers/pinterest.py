"""Pinterest v5: image Pins via base64, video Pins via media upload + cover frame.
No staging needed - Pinterest accepts bytes and base64."""
import base64, mimetypes, os, pathlib, time
from ..lib.util import LOG, ApiError, http, env
from ..lib.media import cover_frame
from .base import PublishResult


def _base() -> str:
    # Trial access apps MUST use the sandbox host; Standard uses production.
    return ("https://api-sandbox.pinterest.com/v5"
            if os.environ.get("PINTEREST_TIER", "standard").lower() == "trial"
            else "https://api.pinterest.com/v5")


def _headers():
    return {"Authorization": f"Bearer {env('PINTEREST_ACCESS_TOKEN')}"}


def _b64(path: pathlib.Path):
    return (base64.b64encode(path.read_bytes()).decode(),
            mimetypes.guess_type(str(path))[0] or "image/jpeg")


def publish(job, content, account, text, media: pathlib.Path, spec, publish_at=None):
    board_id = account["platform_id"]
    body = {"board_id": board_id,
            "title": text.get("title", "")[:100],
            "description": text.get("description", "")[:800]}
    if text.get("link"):
        body["link"] = text["link"]

    if content["content_type"] == "image":
        data, ctype = _b64(media)
        body["media_source"] = {"source_type": "image_base64",
                                "content_type": ctype, "data": data}
    else:
        media_id = _upload_video(media)
        job["_external_ref"] = media_id
        cover = cover_frame(media, 1.0)
        if not cover:
            raise ApiError(400, "could not build cover image", "pin.cover")
        cdata, cctype = _b64(cover)
        body["media_source"] = {"source_type": "video_id", "media_id": media_id,
                                "cover_image_content_type": cctype,
                                "cover_image_data": cdata}

    r = http("POST", f"{_base()}/pins", json=body, headers=_headers(), where="pin.create")
    return PublishResult(r.json()["id"], "pin created")


def _upload_video(media: pathlib.Path) -> str:
    reg = http("POST", f"{_base()}/media", json={"media_type": "video"},
               headers=_headers(), where="pin.media.register").json()
    media_id, url, params = reg["media_id"], reg["upload_url"], reg["upload_parameters"]
    with open(media, "rb") as fh:
        http("POST", url, data={k: v for k, v in params.items()},
             files={"file": fh}, where="pin.media.upload", tries=2)
    for _ in range(40):
        time.sleep(6)
        st = http("GET", f"{_base()}/media/{media_id}", headers=_headers(),
                  where="pin.media.status").json().get("status")
        if st == "succeeded":
            return media_id
        if st == "failed":
            raise ApiError(400, f"media {media_id} failed processing", "pin.media")
    raise ApiError(None, "media processing timeout", "pin.media.timeout")


def verify(job, account):
    try:
        r = http("GET", f"{_base()}/boards/{account['platform_id']}/pins",
                 params={"page_size": 10}, headers=_headers(), where="pin.verify").json()
        want = (job.get("_title") or "")[:40]
        for p in r.get("items", []):
            if want and want in (p.get("title") or ""):
                return p["id"]
    except ApiError:
        pass
    return None
