"""Caption resolution: _meta.csv wins, then the filename rule, then the default."""
import csv, io, pathlib, re
from .util import LOG

_TRAILING_JUNK = re.compile(
    r"[\s._-]*(\(\d+\)|\[[^\]]{1,20}\]|\((?:4k|hd|1080p|720p|final|copy|v\d)\)"
    r"|copy|final|edited|export)\s*$", re.I)
_CODEY = re.compile(r"^(img|vid|video|mov|dsc|dji|gopro|screenshot|photo|clip|q|c)?"
                    r"[\W_]*\d{3,}[\W_]*\d*$", re.I)


def from_filename(filename: str):
    stem = pathlib.Path(filename).stem
    prev = None
    while prev != stem:
        prev = stem
        stem = _TRAILING_JUNK.sub("", stem).strip()
    if _CODEY.match(stem.replace(" ", "")):
        return None                                  # IMG_4821 -> no caption
    text = re.sub(r"[_]+", " ", stem)
    text = re.sub(r"(?<=\w)-(?=\w)", " ", text)      # hyphen between words -> space
    text = re.sub(r"\s{2,}", " ", text).strip()
    if not text or len(text) < 3:
        return None
    if text.islower():                               # only title-case if all-lower
        text = " ".join(w if w in {"a", "an", "the", "of", "in", "on", "and", "to",
                                   "at", "for", "is"} else w.capitalize()
                        for w in text.split())
        text = text[0].upper() + text[1:]
    return text


def parse_meta_csv(text: str) -> dict:
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        keys = {(k or "").strip().lower(): (v or "").strip()
                for k, v in row.items() if k}
        fn = keys.get("filename", "")
        if not fn:
            continue
        if fn in out:
            LOG.warning("_meta.csv: duplicate row for %s (first wins)", fn)
            continue
        out[fn] = {"caption": keys.get("caption", ""), "title": keys.get("title", ""),
                   "hashtags": keys.get("hashtags", ""), "link": keys.get("link", "")}
    return out


def resolve(filename, meta_row, cat) -> dict:
    """Returns caption/title/hashtags/link/source, or source='none' if unusable."""
    meta_row = meta_row or {}
    caption, source = meta_row.get("caption", ""), "csv"
    if not caption:
        caption, source = from_filename(filename) or "", "filename"
    if not caption:
        caption, source = cat.get("default_caption", ""), "default"
    if not caption:
        source = "none"
    title = meta_row.get("title") or caption[:100]
    tags = meta_row.get("hashtags") or cat.get("default_hashtags", "")
    link = meta_row.get("link") or cat.get("default_link", "")
    return {"caption": caption, "title": title, "hashtags": tags,
            "link": link, "caption_source": source}


def truncate(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    cut = text[:limit]
    return (cut.rsplit(" ", 1)[0] if " " in cut[-20:] else cut).rstrip()


def for_platform(platform, c, spec) -> dict:
    """Compose the exact text each platform wants. This is where per-platform
    formatting lives - change it here, not in the publishers."""
    cap_max = int(spec.get("caption_max") or 2200)
    ttl_max = int(spec.get("title_max") or 100)
    caption, tags = c.get("caption", ""), (c.get("hashtags") or "").strip()
    if platform in ("facebook", "instagram", "tiktok"):
        body = (caption + "\n\n" + tags).strip() if tags else caption
        return {"caption": truncate(body, cap_max),
                "title": truncate(c.get("title", ""), ttl_max)}
    if platform == "pinterest":
        # descriptions are a SEARCH field: keywords, not hashtag walls
        return {"title": truncate(c.get("title") or caption, ttl_max),
                "description": truncate(caption, cap_max),
                "link": c.get("link", "")}
    if platform == "youtube":
        desc = (caption + "\n\n" + tags).strip()
        return {"title": truncate(c.get("title") or caption, ttl_max),
                "description": truncate(desc, cap_max)}
    return {"caption": truncate(caption, cap_max)}
