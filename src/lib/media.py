"""Local media inspection + cover-frame extraction (ffmpeg is preinstalled on
GitHub's ubuntu runners, so there is nothing to install)."""
import json, pathlib, subprocess
from .util import LOG


def probe(path: pathlib.Path) -> dict:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, check=True).stdout
        j = json.loads(out)
        v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), {})
        return {"duration_s": float(j.get("format", {}).get("duration", 0) or 0),
                "width": int(v.get("width", 0) or 0),
                "height": int(v.get("height", 0) or 0),
                "codec": v.get("codec_name", "")}
    except Exception as e:
        LOG.warning("ffprobe failed on %s: %s", path.name, e)
        return {"duration_s": 0, "width": 0, "height": 0, "codec": ""}


def cover_frame(video: pathlib.Path, at_s: float = 1.0):
    """Pinterest video Pins REQUIRE a cover image. Generate one."""
    out = video.with_suffix(".cover.jpg")
    subprocess.run(["ffmpeg", "-y", "-ss", str(at_s), "-i", str(video),
                    "-frames:v", "1", "-q:v", "3", str(out)],
                   capture_output=True, check=False)
    return out if out.exists() else None


def fits(spec: dict, meta: dict, size_bytes: int, content_type: str):
    """Return None if OK, else a human reason why this platform will reject it."""
    def num(k, d=0):
        try:
            return float(spec.get(k) or d)
        except ValueError:
            return d
    if content_type == "video":
        if str(spec.get("videos_ok", "TRUE")).upper() == "FALSE":
            return "platform does not accept video via API"
        if size_bytes > num("video_max_mb", 1e9) * 1e6:
            return f"file {size_bytes/1e6:.0f}MB over limit {spec.get('video_max_mb')}MB"
        d = meta.get("duration_s", 0)
        if d and d > num("video_max_s", 1e9):
            return f"duration {d:.0f}s over limit {spec.get('video_max_s')}s"
        if d and d < num("video_min_s", 0):
            return f"duration {d:.0f}s under minimum {spec.get('video_min_s')}s"
    else:
        if str(spec.get("images_ok", "TRUE")).upper() == "FALSE":
            return "platform does not accept images via API"
    return None
