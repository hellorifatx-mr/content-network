"""One-time YouTube OAuth per channel.
Run:  python -m src.tools.oauth_youtube nature
Pick the correct Brand Account on the Google chooser screen."""
import os, sys
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly"]
label = sys.argv[1] if len(sys.argv) > 1 else "default"

cfg = {"installed": {
    "client_id": os.environ["GOOGLE_OAUTH_CLIENT_ID"],
    "client_secret": os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "redirect_uris": ["http://localhost"]}}

flow = InstalledAppFlow.from_client_config(cfg, SCOPES)
creds = flow.run_local_server(port=8087, prompt="consent", access_type="offline")
yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
me = yt.channels().list(part="snippet", mine=True).execute()
ch = me["items"][0]
print("\nchannel:", ch["snippet"]["title"])
print("channel_id (put in accounts.platform_id):", ch["id"])
print('\nAdd to YOUTUBE_TOKENS_JSON:')
print('  "%s": {"refresh_token": "%s"}' % (label, creds.refresh_token))
