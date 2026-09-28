"""Read the Cockpit into plain dicts; write the dashboard + log tabs."""
import json, os, pathlib
from .gauth import sheets
from .util import LOG, iso, now_utc

SHEET_ID = os.environ.get("SHEET_ID", "")
SNAPSHOT = pathlib.Path("config/snapshot.json")
TABS = ("categories", "accounts", "platform_specs")
TRUE = {"true", "yes", "y", "1", "on"}


def _rows(values):
    """First row = headers -> list of dicts with lowercase stripped keys."""
    if not values:
        return []
    hdr = [h.strip().lower() for h in values[0]]
    out = []
    for row in values[1:]:
        row = list(row) + [""] * (len(hdr) - len(row))
        d = {hdr[i]: str(row[i]).strip() for i in range(len(hdr))}
        if any(d.values()):
            out.append(d)
    return out


def load_config(use_cache_on_error=True) -> dict:
    try:
        api = sheets().spreadsheets().values()
        res = api.batchGet(spreadsheetId=SHEET_ID,
                           ranges=[f"{t}!A1:Z1000" for t in TABS]).execute()
        cfg = {t: _rows(vr.get("values", []))
               for t, vr in zip(TABS, res.get("valueRanges", []))}
        cfg["loaded_at"] = iso(now_utc())
        validate(cfg)
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(cfg, indent=2))
        LOG.info("config: %s categories, %s accounts",
                 len(cfg["categories"]), len(cfg["accounts"]))
        return cfg
    except Exception as e:
        if use_cache_on_error and SNAPSHOT.exists():
            LOG.warning("Sheet unreachable (%s) - using cached snapshot", e)
            return json.loads(SNAPSHOT.read_text())
        raise


class ConfigError(SystemExit):
    pass


def validate(cfg: dict):
    known = {"facebook", "instagram", "pinterest", "tiktok", "youtube"}
    seen_cat, seen_acct, warns = set(), set(), []
    for c in cfg["categories"]:
        code = c.get("category_code", "")
        if not code:
            raise ConfigError("categories: a row has no category_code")
        if code in seen_cat:
            raise ConfigError(f"categories: duplicate category_code '{code}'")
        seen_cat.add(code)
        for p in [x for x in c.get("platforms", "").split(",") if x.strip()]:
            if p.strip().lower() not in known:
                raise ConfigError(
                    f"categories/{code}: unknown platform '{p}'. "
                    f"Allowed: {sorted(known)}. Fix the 'platforms' cell.")
        try:
            int(c.get("posts_per_day") or 0)
        except ValueError:
            raise ConfigError(f"categories/{code}: posts_per_day must be a number")
    for a in cfg["accounts"]:
        k = a.get("account_key", "")
        if not k:
            raise ConfigError("accounts: a row has no account_key")
        if k in seen_acct:
            raise ConfigError(f"accounts: duplicate account_key '{k}'")
        seen_acct.add(k)
        if a.get("status") == "active" and not a.get("platform_id"):
            warns.append(f"accounts/{k}: active but platform_id is empty - skipped")
    for w in warns:
        LOG.warning(w)
    cfg["warnings"] = warns


def truthy(v) -> bool:
    return str(v).strip().lower() in TRUE


def spec(cfg, platform) -> dict:
    for s in cfg["platform_specs"]:
        if s.get("platform") == platform:
            return s
    return {}


def write_range(tab_range: str, values):
    sheets().spreadsheets().values().update(
        spreadsheetId=SHEET_ID, range=tab_range,
        valueInputOption="RAW", body={"values": values}).execute()


def append_log(rows):
    if not rows:
        return
    sheets().spreadsheets().values().append(
        spreadsheetId=SHEET_ID, range="log!A1",
        valueInputOption="RAW", insertDataOption="INSERT_ROWS",
        body={"values": rows}).execute()
