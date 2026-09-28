"""The ledger. Every state transition in the system goes through this file."""
import pathlib, sqlite3
from datetime import timedelta
from .util import LOG, iso, now_utc, backoff_seconds, MAX_ATTEMPTS

DB_PATH = pathlib.Path("data/state.db")

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS content (
  content_id TEXT PRIMARY KEY, category_code TEXT NOT NULL, filename TEXT NOT NULL,
  content_type TEXT NOT NULL, mime TEXT, size_bytes INTEGER, duration_s REAL,
  width INTEGER, height INTEGER, md5 TEXT, caption TEXT, title TEXT, hashtags TEXT,
  link TEXT, caption_source TEXT, state TEXT NOT NULL, duplicate_of TEXT,
  times_used INTEGER NOT NULL DEFAULT 0, last_used_at TEXT,
  first_seen_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_content_pick ON content(category_code,state,first_seen_at);
CREATE INDEX IF NOT EXISTS ix_content_md5 ON content(category_code,md5);
CREATE TABLE IF NOT EXISTS jobs (
  job_id INTEGER PRIMARY KEY AUTOINCREMENT, idempotency_key TEXT NOT NULL UNIQUE,
  content_id TEXT NOT NULL REFERENCES content(content_id), account_key TEXT NOT NULL,
  platform TEXT NOT NULL, slot_at_utc TEXT NOT NULL, state TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0, next_attempt_utc TEXT, claimed_by_run TEXT,
  claimed_at_utc TEXT, external_ref TEXT, platform_post_id TEXT, published_at_utc TEXT,
  last_error TEXT, last_error_class TEXT, created_at_utc TEXT NOT NULL,
  updated_at_utc TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_jobs_due ON jobs(state,slot_at_utc);
CREATE INDEX IF NOT EXISTS ix_jobs_acct ON jobs(account_key,published_at_utc);
CREATE UNIQUE INDEX IF NOT EXISTS ux_jobs_content_account ON jobs(content_id,account_key);
CREATE TABLE IF NOT EXISTS job_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL, at_utc TEXT NOT NULL,
  from_state TEXT, to_state TEXT NOT NULL, run_id TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, kind TEXT NOT NULL, started_utc TEXT NOT NULL,
  ended_utc TEXT, status TEXT, summary TEXT);
"""

TERMINAL = ("PUBLISHED", "MANUAL_REVIEW", "SKIPPED", "CANCELLED")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=60, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=60000")
    con.executescript(SCHEMA)
    return con


def start_run(con, kind, rid):
    con.execute("INSERT OR REPLACE INTO runs(run_id,kind,started_utc) VALUES(?,?,?)",
                (rid, kind, iso(now_utc())))


def end_run(con, rid, status, summary=""):
    con.execute("UPDATE runs SET ended_utc=?,status=?,summary=? WHERE run_id=?",
                (iso(now_utc()), status, summary[:2000], rid))


def upsert_content(con, row: dict):
    now = iso(now_utc())
    cur = con.execute("SELECT content_id FROM content WHERE content_id=?",
                      (row["content_id"],))
    if cur.fetchone():
        con.execute("""UPDATE content SET filename=?,caption=?,title=?,hashtags=?,link=?,
            caption_source=?,state=?,duplicate_of=?,mime=?,size_bytes=?,md5=?,
            content_type=?,updated_at=? WHERE content_id=?""",
            (row["filename"], row["caption"], row["title"], row["hashtags"], row["link"],
             row["caption_source"], row["state"], row.get("duplicate_of"), row.get("mime"),
             row.get("size_bytes"), row.get("md5"), row["content_type"], now,
             row["content_id"]))
        return "updated"
    con.execute("""INSERT INTO content(content_id,category_code,filename,content_type,mime,
        size_bytes,md5,caption,title,hashtags,link,caption_source,state,duplicate_of,
        first_seen_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (row["content_id"], row["category_code"], row["filename"], row["content_type"],
         row.get("mime"), row.get("size_bytes"), row.get("md5"), row["caption"],
         row["title"], row["hashtags"], row["link"], row["caption_source"], row["state"],
         row.get("duplicate_of"), now, now))
    return "inserted"


def pick_content(con, category, order, limit, allow_types, recycle_days=0):
    order_sql = {"oldest": "first_seen_at ASC, filename ASC",
                 "newest": "first_seen_at DESC, filename ASC",
                 "random": "RANDOM()"}.get(order, "first_seen_at ASC")
    types = ",".join("?" * len(allow_types))
    used = "times_used = 0"
    params = [category, *allow_types]
    if recycle_days and int(recycle_days) > 0:
        cutoff = iso(now_utc() - timedelta(days=int(recycle_days)))
        used = "(times_used = 0 OR last_used_at < ?)"
        params.append(cutoff)
    q = (f"SELECT * FROM content WHERE category_code=? AND state='READY' "
         f"AND content_type IN ({types}) AND {used} ORDER BY {order_sql} LIMIT ?")
    params.append(int(limit))
    return [dict(r) for r in con.execute(q, params).fetchall()]


def create_job(con, key, content_id, account_key, platform, slot_at_utc, rid):
    """Returns job_id, or None if this job already exists (duplicate blocked)."""
    now = iso(now_utc())
    try:
        cur = con.execute("""INSERT INTO jobs(idempotency_key,content_id,account_key,
            platform,slot_at_utc,state,created_at_utc,updated_at_utc)
            VALUES(?,?,?,?,?,'SCHEDULED',?,?)""",
            (key, content_id, account_key, platform, slot_at_utc, now, now))
        jid = cur.lastrowid
        _event(con, jid, None, "SCHEDULED", rid, "created by planner")
        return jid
    except sqlite3.IntegrityError as e:
        LOG.debug("duplicate job blocked (%s/%s): %s", content_id, account_key, e)
        return None


def due_jobs(con, limit=200):
    now = iso(now_utc())
    return [dict(r) for r in con.execute(
        """SELECT j.*, c.category_code FROM jobs j JOIN content c USING(content_id)
           WHERE (j.state='SCHEDULED' AND j.slot_at_utc<=?)
              OR (j.state='RETRY_WAIT' AND COALESCE(j.next_attempt_utc,'')<=?)
           ORDER BY j.slot_at_utc ASC LIMIT ?""", (now, now, limit)).fetchall()]


def in_doubt_jobs(con, limit=50):
    return [dict(r) for r in con.execute(
        "SELECT * FROM jobs WHERE state='IN_DOUBT' ORDER BY job_id LIMIT ?",
        (limit,)).fetchall()]


def claim(con, job_id, rid) -> bool:
    """Atomic claim. False means somebody else already took it - do not publish."""
    now = iso(now_utc())
    cur = con.execute("""UPDATE jobs SET state='PUBLISHING',claimed_by_run=?,
        claimed_at_utc=?,attempts=attempts+1,updated_at_utc=?
        WHERE job_id=? AND state IN ('SCHEDULED','RETRY_WAIT')""",
        (rid, now, now, job_id))
    if cur.rowcount == 1:
        _event(con, job_id, None, "PUBLISHING", rid, "claimed")
        return True
    return False


def set_external_ref(con, job_id, ref):
    """Persisted BEFORE the irreversible publish call. This is what makes
    IN_DOUBT verification possible."""
    con.execute("UPDATE jobs SET external_ref=?,updated_at_utc=? WHERE job_id=?",
                (str(ref), iso(now_utc()), job_id))


def mark_published(con, job_id, post_id, rid):
    now = iso(now_utc())
    con.execute("""UPDATE jobs SET state='PUBLISHED',platform_post_id=?,published_at_utc=?,
        last_error=NULL,updated_at_utc=? WHERE job_id=?""", (str(post_id), now, now, job_id))
    con.execute("""UPDATE content SET times_used=times_used+1,last_used_at=?
        WHERE content_id=(SELECT content_id FROM jobs WHERE job_id=?)""", (now, job_id))
    _event(con, job_id, "PUBLISHING", "PUBLISHED", rid, str(post_id))


def mark_in_doubt(con, job_id, rid, detail=""):
    now = iso(now_utc())
    con.execute("UPDATE jobs SET state='IN_DOUBT',updated_at_utc=? WHERE job_id=?",
                (now, job_id))
    _event(con, job_id, "PUBLISHING", "IN_DOUBT", rid, detail[:500])


def mark_failed(con, job, klass, message, rid):
    """Decides retry vs manual review, based on the error class only."""
    now = iso(now_utc())
    attempts = job["attempts"]
    limit = MAX_ATTEMPTS.get(klass, 2)
    if attempts < limit:
        nxt = iso(now_utc() + timedelta(seconds=backoff_seconds(attempts, klass)))
        con.execute("""UPDATE jobs SET state='RETRY_WAIT',next_attempt_utc=?,last_error=?,
            last_error_class=?,updated_at_utc=? WHERE job_id=?""",
            (nxt, message[:900], klass, now, job["job_id"]))
        _event(con, job["job_id"], "PUBLISHING", "RETRY_WAIT", rid,
               f"{klass}: retry #{attempts + 1} at {nxt}")
        return "RETRY_WAIT"
    con.execute("""UPDATE jobs SET state='MANUAL_REVIEW',last_error=?,last_error_class=?,
        updated_at_utc=? WHERE job_id=?""", (message[:900], klass, now, job["job_id"]))
    _event(con, job["job_id"], "PUBLISHING", "MANUAL_REVIEW", rid, klass)
    return "MANUAL_REVIEW"


def skip(con, job_id, rid, why):
    con.execute("UPDATE jobs SET state='SKIPPED',last_error=?,updated_at_utc=? WHERE job_id=?",
                (why[:400], iso(now_utc()), job_id))
    _event(con, job_id, None, "SKIPPED", rid, why[:400])


def recover_stale(con, rid, minutes=30):
    """A killed runner leaves jobs in PUBLISHING. Never assume they failed."""
    cutoff = iso(now_utc() - timedelta(minutes=minutes))
    rows = con.execute("SELECT job_id FROM jobs WHERE state='PUBLISHING' AND claimed_at_utc<?",
                       (cutoff,)).fetchall()
    for r in rows:
        mark_in_doubt(con, r["job_id"], rid, "stale claim recovered")
    if rows:
        LOG.warning("recovered %s stale PUBLISHING jobs -> IN_DOUBT", len(rows))
    return len(rows)


def published_today(con, account_key) -> int:
    today = now_utc().strftime("%Y-%m-%d")
    return con.execute("""SELECT COUNT(*) FROM jobs WHERE account_key=?
        AND state='PUBLISHED' AND substr(published_at_utc,1,10)=?""",
        (account_key, today)).fetchone()[0]


def _event(con, job_id, frm, to, rid, detail=""):
    con.execute("""INSERT INTO job_events(job_id,at_utc,from_state,to_state,run_id,detail)
        VALUES(?,?,?,?,?,?)""", (job_id, iso(now_utc()), frm, to, rid, detail))
