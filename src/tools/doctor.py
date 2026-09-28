"""Preflight: checks every credential and every ID in the Cockpit, and posts
nothing. Run it locally or as a manual workflow whenever something feels wrong."""
import sys
from ..lib import db, drive, sheets
from ..lib.util import LOG, http, setup_logging, env

GRAPH = "https://graph.facebook.com/v21.0"


def main():
    setup_logging()
    problems = []
    try:
        cfg = sheets.load_config(use_cache_on_error=False)
        LOG.info("OK Cockpit readable: %s categories, %s accounts",
                 len(cfg["categories"]), len(cfg["accounts"]))
    except Exception as e:
        print("FAIL cannot read the Cockpit:", e); return 1

    folders = drive.category_folders()
    LOG.info("OK Drive folders: %s", sorted(folders))
    for c in cfg["categories"]:
        if c["category_code"] not in folders:
            problems.append(f"category '{c['category_code']}' has no Drive folder")

    for a in cfg["accounts"]:
        if a.get("status") != "active":
            continue
        p, pid, key = a["platform"], a.get("platform_id"), a["account_key"]
        try:
            if p == "facebook":
                r = http("GET", f"{GRAPH}/{pid}",
                         params={"fields": "name,access_token",
                                 "access_token": env("META_SYSTEM_TOKEN")},
                         where="doctor.fb").json()
                LOG.info("OK %s -> Page '%s'", key, r.get("name"))
            elif p == "instagram":
                r = http("GET", f"{GRAPH}/{pid}",
                         params={"fields": "username,followers_count",
                                 "access_token": env("META_SYSTEM_TOKEN")},
                         where="doctor.ig").json()
                LOG.info("OK %s -> @%s", key, r.get("username"))
            elif p == "pinterest":
                from ..publishers.pinterest import _base, _headers
                r = http("GET", f"{_base()}/boards/{pid}", headers=_headers(),
                         where="doctor.pin").json()
                LOG.info("OK %s -> board '%s'", key, r.get("name"))
            elif p == "tiktok":
                from ..publishers.tiktok import _access_token
                _access_token(a); LOG.info("OK %s -> token refreshes", key)
            elif p == "youtube":
                from ..publishers.youtube import _service
                _service(a); LOG.info("OK %s -> credentials load", key)
        except Exception as e:
            problems.append(f"{key}: {e}")

    con = db.connect()
    ready = con.execute("SELECT COUNT(*) FROM content WHERE state='READY'").fetchone()[0]
    LOG.info("OK ledger, %s items READY", ready)

    if problems:
        print("\nPROBLEMS FOUND:")
        for p in problems:
            print("  -", p)
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
