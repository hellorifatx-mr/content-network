"""Weekly: rotate Pinterest tokens (60-day continuous refresh) and prove the
Meta token is still alive."""
import base64, json, sys
from .lib.util import LOG, ApiError, env, http, setup_logging


def pinterest():
    basic = base64.b64encode(
        f"{env('PINTEREST_APP_ID')}:{env('PINTEREST_APP_SECRET')}".encode()).decode()
    r = http("POST", "https://api.pinterest.com/v5/oauth/token",
             headers={"Authorization": f"Basic {basic}",
                      "Content-Type": "application/x-www-form-urlencoded"},
             data={"grant_type": "refresh_token",
                   "refresh_token": env("PINTEREST_REFRESH_TOKEN")},
             where="pin.refresh")
    j = r.json()
    LOG.info("pinterest access token refreshed, expires_in=%s", j.get("expires_in"))
    return j.get("access_token"), j.get("refresh_token")


def meta_check():
    tok = env("META_SYSTEM_TOKEN")
    j = http("GET", "https://graph.facebook.com/v21.0/debug_token",
             params={"input_token": tok, "access_token": tok},
             where="meta.debug").json().get("data", {})
    LOG.info("meta token valid=%s expires_at=%s scopes=%s",
             j.get("is_valid"), j.get("expires_at"), ",".join(j.get("scopes", [])))
    if not j.get("is_valid"):
        raise ApiError(401, json.dumps(j), "meta.debug")


def main():
    setup_logging()
    meta_check()
    try:
        acc, ref = pinterest()
        with open("new_tokens.txt", "w") as fh:
            fh.write(f"PINTEREST_ACCESS_TOKEN={acc}\nPINTEREST_REFRESH_TOKEN={ref}\n")
    except ApiError as e:
        LOG.error("pinterest refresh failed: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
