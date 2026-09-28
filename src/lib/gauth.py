"""Google credentials from the GOOGLE_SA_JSON secret (never from a file on disk)."""
import json, os
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]


def _creds():
    raw = os.environ.get("GOOGLE_SA_JSON")
    if not raw:
        raise SystemExit("FATAL: GOOGLE_SA_JSON secret is not set")
    info = json.loads(raw)
    return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)


def drive():
    return build("drive", "v3", credentials=_creds(), cache_discovery=False)


def sheets():
    return build("sheets", "v4", credentials=_creds(), cache_discovery=False)
