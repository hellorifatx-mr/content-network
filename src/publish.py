"""Hourly: publish everything that is due on live/draft platforms, verify anything
left IN_DOUBT, and retry what deserves retrying."""
import os, sys
from collections import defaultdict
from .lib import db, drive, media as mediautil, sheets, staging
from .lib.captions import for_platform
from .lib.util import LOG, ApiError, dry_run, run_id, setup_logging
from .publishers import get as get_publisher

MAX_PER_RUN = int(os.environ.get("MAX_PER_RUN", "40"))


def main() -> int:
    setup_logging()
    rid = run_id()
    cfg = sheets.load_config()
    con = db.connect()
    db.start_run(con, "publish", rid)
    accounts = {a["account_key"]: a for a in cfg["accounts"]}

    db.recover_stale(con, rid)
    _verify_in_doubt(con, accounts, rid)

    jobs = db.due_jobs(con, MAX_PER_RUN)
    LOG.info("%s job(s) due", len(jobs))
    ok = fail = skip = 0
    breaker = defaultdict(int)

    for job in jobs:
        acct = accounts.get(job["account_key"])
        if not acct:
            db.skip(con, job["job_id"], rid, "account row no longer in Cockpit")
            skip += 1; continue
        if acct.get("status") != "active" or acct.get("api_status") != "connected":
            db.skip(con, job["job_id"], rid,
                    f"account {acct.get('status')}/{acct.get('api_status')}")
            skip += 1; continue
        if breaker[job["account_key"]] >= 3:
            LOG.warning("circuit breaker open for %s - skipping rest this run",
                        job["account_key"])
            continue
        spec = sheets.spec(cfg, job["platform"])
        if (spec.get("mode") or "live").lower() == "off":
            db.skip(con, job["job_id"], rid, "platform disabled")
            skip += 1; continue
        cap = int(acct.get("daily_cap") or 999)
        if db.published_today(con, job["account_key"]) >= cap:
            LOG.warning("%s hit daily_cap %s - deferring", job["account_key"], cap)
            continue

        item = dict(con.execute("SELECT * FROM content WHERE content_id=?",
                                (job["content_id"],)).fetchone())
        if dry_run():
            LOG.info("[DRY] would publish %s -> %s", item["filename"], job["account_key"])
            continue
        if not db.claim(con, job["job_id"], rid):
            LOG.info("job %s already claimed elsewhere", job["job_id"]); continue

        path = stage_key = None
        try:
            path = drive.download(item["content_id"], item["filename"])
            meta = mediautil.probe(path) if item["content_type"] == "video" else {}
            why = mediautil.fits(spec, meta, path.stat().st_size, item["content_type"])
            if why:
                db.skip(con, job["job_id"], rid, f"media unsuitable: {why}")
                skip += 1; continue
            text = for_platform(job["platform"], item, spec)
            job["_caption"] = text.get("caption", "")
            job["_title"] = text.get("title", "")
            pub = get_publisher(job["platform"])
            kwargs = {}
            if job["platform"] == "instagram":          # the only platform needing a URL
                stage_key = staging.key_for(job["job_id"], item["content_id"],
                                            path.suffix)
                kwargs["staged_url"] = staging.put(path, stage_key)
            res = pub.publish(job, item, acct, text, path, spec, **kwargs)
            if job.get("_external_ref"):
                db.set_external_ref(con, job["job_id"], job["_external_ref"])
            db.mark_published(con, job["job_id"], res.post_id, rid)
            LOG.info("OK %s -> %s (%s)", item["filename"], job["account_key"], res.detail)
            ok += 1
        except ApiError as e:
            if job.get("_external_ref"):
                db.set_external_ref(con, job["job_id"], job["_external_ref"])
            if e.klass == "TRANSIENT" and e.status is None and job.get("_external_ref"):
                db.mark_in_doubt(con, job["job_id"], rid, str(e))
            else:
                db.mark_failed(con, job, e.klass, str(e), rid)
            breaker[job["account_key"]] += 1
            LOG.error("FAIL %s -> %s: %s", item["filename"], job["account_key"], e)
            fail += 1
        except Exception as e:                       # never let one job kill the run
            db.mark_failed(con, job, "UNKNOWN", repr(e), rid)
            fail += 1
            LOG.exception("unexpected error on job %s", job["job_id"])
        finally:
            if stage_key:
                staging.delete(stage_key)
            if path and path.exists():
                path.unlink(missing_ok=True)

    summary = f"publish: {ok} ok, {fail} failed, {skip} skipped"
    LOG.info(summary)
    db.end_run(con, rid, "ok" if fail == 0 else "partial", summary)
    con.close()
    return 0


def _verify_in_doubt(con, accounts, rid):
    for job in db.in_doubt_jobs(con):
        acct = accounts.get(job["account_key"])
        if not acct:
            db.skip(con, job["job_id"], rid, "account gone"); continue
        pub = get_publisher(job["platform"])
        found = None
        try:
            found = pub.verify(job, acct)
        except Exception as e:
            LOG.warning("verify failed for job %s: %s", job["job_id"], e)
        if found:
            LOG.info("IN_DOUBT job %s was actually published (%s)", job["job_id"], found)
            db.mark_published(con, job["job_id"], found, rid)
        else:
            LOG.info("IN_DOUBT job %s not found on platform - queueing retry",
                     job["job_id"])
            db.mark_failed(con, job, "TRANSIENT", "verified not published", rid)


if __name__ == "__main__":
    sys.exit(main())
