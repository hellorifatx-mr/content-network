"""Daily: write the dashboard + log tabs and print the summary (which the
workflow turns into a notification)."""
import sys
from datetime import timedelta
from .lib import db, sheets
from .lib.util import LOG, iso, now_utc, run_id, setup_logging


def main() -> int:
    setup_logging()
    rid = run_id()
    con = db.connect()
    since = iso(now_utc() - timedelta(hours=24))

    per = con.execute("""SELECT platform,
           SUM(state='PUBLISHED') pub, SUM(state='RETRY_WAIT') retry,
           SUM(state='MANUAL_REVIEW') review, SUM(state='SCHEDULED') sched,
           SUM(state='SKIPPED') skipped
        FROM jobs WHERE updated_at_utc>=? GROUP BY platform ORDER BY platform""",
        (since,)).fetchall()
    runway = con.execute("""SELECT category_code, COUNT(*) ready FROM content
        WHERE state='READY' AND times_used=0 GROUP BY category_code""").fetchall()
    attention = con.execute("""SELECT j.job_id, j.account_key, j.last_error_class,
           substr(COALESCE(j.last_error,''),1,120) err, c.filename
        FROM jobs j JOIN content c USING(content_id)
        WHERE j.state='MANUAL_REVIEW' ORDER BY j.job_id DESC LIMIT 25""").fetchall()
    lastrun = con.execute("""SELECT kind,started_utc,status,summary FROM runs
        WHERE ended_utc IS NOT NULL ORDER BY started_utc DESC LIMIT 6""").fetchall()

    lines = ["SOCIAL PUBLISHING REPORT  " + now_utc().strftime("%Y-%m-%d %H:%M UTC"), ""]
    for r in per:
        lines.append(f"{r['platform'].upper():<10} published {r['pub'] or 0:>3} "
                     f"| retrying {r['retry'] or 0:>2} | needs review {r['review'] or 0:>2} "
                     f"| scheduled {r['sched'] or 0:>3} | skipped {r['skipped'] or 0:>2}")
    lines += ["", "CONTENT RUNWAY"]
    for r in runway:
        lines.append(f"  {r['category_code']:<16} {r['ready']} items ready")
    if attention:
        lines += ["", "NEEDS YOUR ATTENTION"]
        for a in attention:
            lines.append(f"  #{a['job_id']} {a['account_key']} [{a['last_error_class']}] "
                         f"{a['filename']}: {a['err']}")
    else:
        lines += ["", "NEEDS YOUR ATTENTION: none (ok)"]
    report = "\n".join(lines)
    print(report)

    try:
        sheets.write_range("dashboard!A1:B6", [
            ["metric", "value"],
            ["last_report_utc", iso(now_utc())],
            *[[f"last_{r['kind']}", f"{r['started_utc']} {r['status']}"] for r in lastrun[:4]],
        ])
        rows = [["platform", "published", "retrying", "review", "scheduled", "skipped"]]
        rows += [[r["platform"], r["pub"] or 0, r["retry"] or 0, r["review"] or 0,
                  r["sched"] or 0, r["skipped"] or 0] for r in per]
        blanks = [[""] * 6 for _ in range(max(0, 13 - len(rows)))]
        sheets.write_range("dashboard!A8:F20", rows + blanks)
        sheets.append_log([[iso(now_utc()), rid, "INFO", "", "", "",
                            report.replace("\n", " | ")[:4000]]])
    except Exception as e:
        LOG.warning("could not write dashboard: %s", e)

    with open("report.txt", "w", encoding="utf-8") as fh:
        fh.write(report)
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
