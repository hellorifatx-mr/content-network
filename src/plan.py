"""Once a day: choose content, create jobs, and hand scheduled platforms their
future timestamps. This is the only place that decides WHAT and WHEN."""
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from .lib import db, drive, media as mediautil, sheets
from .lib.captions import for_platform
from .lib.util import (LOG, ApiError, idem_key, iso, now_utc, run_id,
                       setup_logging, dry_run)
from .publishers import get as get_publisher


def slots_for(cat, target_date, tz) -> list:
    n = int(cat.get("posts_per_day") or 0)
    if n <= 0:
        return []
    hours = [int(h) for h in str(cat.get("post_hours", "")).split(",") if h.strip()]
    if not hours:
        a = int(cat.get("window_start") or 8)
        b = int(cat.get("window_end") or 21)
        step = max(1, (b - a) // max(1, n))
        hours = [a + i * step for i in range(n)]
    hours = sorted(hours)[:n]
    out = []
    for h in hours:
        local = datetime.combine(target_date, datetime.min.time(),
                                 tzinfo=ZoneInfo(tz)).replace(hour=h % 24)
        out.append(local.astimezone(timezone.utc))
    return out


def main() -> int:
    setup_logging()
    rid = run_id()
    cfg = sheets.load_config()
    con = db.connect()
    db.start_run(con, "plan", rid)
    accounts = list(cfg["accounts"])
    created = scheduled_now = skipped = 0

    for cat in cfg["categories"]:
        code = cat["category_code"]
        if not sheets.truthy(cat.get("enabled")):
            LOG.info("%s: disabled, skipping", code)
            continue
        tz = cat.get("timezone") or "UTC"
        target = (now_utc().astimezone(ZoneInfo(tz)) + timedelta(days=1)).date()
        slots = slots_for(cat, target, tz)
        if not slots:
            continue

        wanted = [p.strip().lower() for p in cat.get("platforms", "").split(",")
                  if p.strip()]
        lanes = []
        for p in wanted:
            spec = sheets.spec(cfg, p)
            if (spec.get("mode") or "live").lower() == "off":
                LOG.info("%s/%s: platform mode=off, skipped", code, p)
                continue
            for a in accounts:
                if (a.get("category_code") == code and a.get("platform") == p
                        and a.get("status") == "active"
                        and a.get("api_status") == "connected"
                        and a.get("platform_id")):
                    lanes.append((a, spec))
        if not lanes:
            LOG.warning("%s: no active accounts for %s", code, wanted)
            continue

        types = [t.strip() for t in (cat.get("content_types") or "video,image").split(",")]
        items = db.pick_content(con, code, cat.get("pick_order", "oldest"),
                                len(slots), types, cat.get("recycle_after_days", 0))
        if not items:
            LOG.warning("%s: NO CONTENT READY - nothing planned", code)
            continue
        if len(items) < len(slots):
            LOG.warning("%s: only %s items for %s slots", code, len(items), len(slots))

        for item, slot in zip(items, slots):
            for account, spec in lanes:
                key = idem_key(item["content_id"], account["account_key"],
                               slot.strftime("%Y-%m-%d"))
                jid = db.create_job(con, key, item["content_id"],
                                    account["account_key"], account["platform"],
                                    iso(slot), rid)
                if not jid:
                    skipped += 1
                    continue
                created += 1
                # scheduled-mode platforms are handed off immediately
                if (spec.get("mode") or "live").lower() == "scheduled":
                    if _handoff(con, jid, item, account, spec, cfg, slot, rid):
                        scheduled_now += 1

    summary = (f"plan: {created} jobs created, {scheduled_now} handed to platform "
               f"schedulers, {skipped} duplicates blocked")
    LOG.info(summary)
    db.end_run(con, rid, "ok", summary)
    con.close()
    return 0


def _handoff(con, job_id, item, account, spec, cfg, slot, rid) -> bool:
    """Upload now, tell the platform to publish at `slot`."""
    job = {"job_id": job_id, "attempts": 1}
    if dry_run():
        LOG.info("[DRY] would schedule %s -> %s at %s",
                 item["filename"], account["account_key"], iso(slot))
        return False
    if not db.claim(con, job_id, rid):
        return False
    path = None
    try:
        path = drive.download(item["content_id"], item["filename"])
        meta = mediautil.probe(path) if item["content_type"] == "video" else {}
        why = mediautil.fits(spec, meta, path.stat().st_size, item["content_type"])
        if why:
            db.skip(con, job_id, rid, f"media unsuitable: {why}")
            return False
        text = for_platform(account["platform"], item, spec)
        pub = get_publisher(account["platform"])
        res = pub.publish(job, item, account, text, path, spec, publish_at=slot)
        if job.get("_external_ref"):
            db.set_external_ref(con, job_id, job["_external_ref"])
        db.mark_published(con, job_id, res.post_id, rid)
        LOG.info("scheduled %s on %s (%s)", item["filename"],
                 account["account_key"], res.detail)
        return True
    except ApiError as e:
        if job.get("_external_ref"):
            db.set_external_ref(con, job_id, job["_external_ref"])
        db.mark_failed(con, {"job_id": job_id, "attempts": 1}, e.klass, str(e), rid)
        LOG.error("handoff failed %s: %s", account["account_key"], e)
        return False
    finally:
        if path and path.exists():
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
