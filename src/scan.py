"""Read Drive -> upsert the content table. Creates no jobs, publishes nothing."""
import sys
from .lib import captions, db, drive, sheets
from .lib.util import LOG, run_id, setup_logging


def main() -> int:
    setup_logging()
    rid = run_id()
    cfg = sheets.load_config()
    con = db.connect()
    db.start_run(con, "scan", rid)
    cats = {c["category_code"]: c for c in cfg["categories"]}
    folders = drive.category_folders()
    stats = {"new": 0, "updated": 0, "dupe": 0, "unsupported": 0, "nocaption": 0}

    for code, cat in cats.items():
        fid = folders.get(code)
        if not fid:
            LOG.warning("category '%s' has no Drive folder - skipped", code)
            continue
        files = drive.files_in(fid)
        meta = {}
        for f in files:
            if f["name"] == "_meta.csv":
                meta = captions.parse_meta_csv(drive.download_text(f["id"]))
                LOG.info("%s: _meta.csv with %s rows", code, len(meta))

        seen_md5 = {r[0]: r[1] for r in con.execute(
            "SELECT md5, content_id FROM content WHERE category_code=? AND md5 IS NOT NULL",
            (code,)).fetchall()}

        for f in files:
            name = f["name"]
            if name == "_meta.csv":
                continue
            ctype = drive.content_type_of(name)
            if not ctype:
                LOG.info("%s: skipping unsupported file %s", code, name)
                stats["unsupported"] += 1
                continue
            md5 = f.get("md5Checksum")
            text = captions.resolve(name, meta.get(name), cat)
            state = "READY"
            dupe_of = None
            if md5 and md5 in seen_md5 and seen_md5[md5] != f["id"]:
                state, dupe_of = "DUPLICATE", seen_md5[md5]
                stats["dupe"] += 1
            elif text["caption_source"] == "none":
                state = "NEEDS_CAPTION"
                stats["nocaption"] += 1
            res = db.upsert_content(con, {
                "content_id": f["id"], "category_code": code, "filename": name,
                "content_type": ctype, "mime": f.get("mimeType"),
                "size_bytes": int(f.get("size", 0) or 0), "md5": md5,
                "state": state, "duplicate_of": dupe_of, **text})
            stats["new" if res == "inserted" else "updated"] += 1
            if md5:
                seen_md5.setdefault(md5, f["id"])

    summary = (f"scan: {stats['new']} new, {stats['updated']} updated, "
               f"{stats['dupe']} duplicates, {stats['nocaption']} need captions, "
               f"{stats['unsupported']} unsupported")
    LOG.info(summary)
    db.end_run(con, rid, "ok", summary)
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
