"""Shared helpers: time, IDs, logging, error classification, HTTP with retries."""
import hashlib, json, logging, os, random, sys, time
from datetime import datetime, timezone
import requests

LOG = logging.getLogger("cn")


def setup_logging():
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        stream=sys.stdout, level=level,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S",
    )
    return LOG


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def run_id() -> str:
    """Unique id for this workflow run (falls back to a timestamp locally)."""
    gh = os.environ.get("GITHUB_RUN_ID")
    at = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    return f"gh-{gh}-{at}" if gh else "local-" + now_utc().strftime("%Y%m%d%H%M%S")


def idem_key(content_id: str, account_key: str, slot_date: str) -> str:
    raw = f"{content_id}|{account_key}|{slot_date}"
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


def env(name: str, required: bool = True, default: str = "") -> str:
    v = os.environ.get(name, default)
    if required and not v:
        raise SystemExit(f"FATAL: missing required secret/env var {name}")
    return v


def dry_run() -> bool:
    return os.environ.get("DRY_RUN", "false").lower() == "true"


# ---------------------------------------------------------------- errors
TRANSIENT, RATE_LIMIT, AUTH, POLICY, MEDIA, CONFIG, UNKNOWN = (
    "TRANSIENT", "RATE_LIMIT", "AUTH", "POLICY", "MEDIA", "CONFIG", "UNKNOWN")

MAX_ATTEMPTS = {TRANSIENT: 5, RATE_LIMIT: 3, UNKNOWN: 2,
                AUTH: 1, POLICY: 0, MEDIA: 0, CONFIG: 0}

_AUTH_CODES   = {190, 102, 200, 10, 458, 463, 467}
_RATE_CODES   = {4, 17, 32, 613, 80001, 2207042}
_MEDIA_CODES  = {6000, 2207003, 2207004, 2207020, 2207026, 2207057}
_POLICY_CODES = {368, 2207050, 2207053}


def classify(status, body: str) -> str:
    """Map an HTTP status + response body to a retry class. Never guesses upward."""
    b = (body or "").lower()
    code = None
    try:
        j = json.loads(body)
        err = j.get("error", j)
        code = err.get("code") or err.get("error_subcode")
        if isinstance(code, str) and code.isdigit():
            code = int(code)
    except Exception:
        pass

    if status is None:
        return TRANSIENT                      # network layer never answered
    if status == 429 or code in _RATE_CODES or "rate_limit" in b or "too many" in b:
        return RATE_LIMIT
    if status in (401, 403) or code in _AUTH_CODES or "access_token" in b or "oauth" in b:
        if "spam_risk" in b or "banned" in b or "unaudited_client" in b:
            return POLICY
        return AUTH
    if status >= 500:
        return TRANSIENT
    if code in _MEDIA_CODES or any(k in b for k in
            ("unsupported", "aspect ratio", "file size", "duration", "corrupt", "invalid_file")):
        return MEDIA
    if code in _POLICY_CODES or any(k in b for k in
            ("restricted", "abusive", "violat", "banned_from_posting")):
        return POLICY
    if status == 400 and any(k in b for k in
            ("board_id", "privacy_level_option_mismatch", "does not exist", "invalid_param")):
        return CONFIG
    if status == 404:
        return CONFIG
    return UNKNOWN


def backoff_seconds(attempts: int, klass: str) -> int:
    if klass == RATE_LIMIT:
        return 3600                                   # wait a full hour, do not hammer
    base = 120
    delay = base * (2 ** max(0, attempts - 1))
    delay = min(delay, 6 * 3600)
    return int(delay * (0.75 + random.random() * 0.5))


class ApiError(Exception):
    def __init__(self, status, body, where=""):
        self.status, self.body, self.where = status, body, where
        self.klass = classify(status, body)
        super().__init__(f"[{where}] HTTP {status} ({self.klass}): {str(body)[:400]}")


def http(method: str, url: str, where: str = "", tries: int = 3, **kw):
    """HTTP with retries for network/5xx only. Never retries a 4xx."""
    kw.setdefault("timeout", 180)
    last = None
    for i in range(1, tries + 1):
        try:
            r = requests.request(method, url, **kw)
        except requests.RequestException as e:
            last = ApiError(None, str(e), where)
            LOG.warning("network error %s (try %s/%s)", e, i, tries)
            time.sleep(min(5 * 2 ** i, 60)); continue
        if r.status_code < 400:
            return r
        if r.status_code >= 500 and i < tries:
            LOG.warning("%s -> %s, retrying", where, r.status_code)
            time.sleep(min(5 * 2 ** i, 60)); continue
        raise ApiError(r.status_code, r.text, where)
    raise last
