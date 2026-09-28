"""One-time TikTok OAuth per account.
Run:  python -m src.tools.oauth_tiktok nature
Then merge the printed refresh_token into the TIKTOK_TOKENS_JSON secret."""
import http.server, os, secrets, sys, urllib.parse, webbrowser, requests

KEY = os.environ["TIKTOK_CLIENT_KEY"]
SECRET = os.environ["TIKTOK_CLIENT_SECRET"]
REDIRECT = "http://localhost:8086/callback"
SCOPES = "user.info.basic,video.upload,video.list"      # add video.publish AFTER audit
label = sys.argv[1] if len(sys.argv) > 1 else "default"
state = secrets.token_urlsafe(16)
hold = {}


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        hold.update(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query))
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Done - return to the terminal.")

    def log_message(self, *a):
        pass


auth = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
    "client_key": KEY, "scope": SCOPES, "response_type": "code",
    "redirect_uri": REDIRECT, "state": state})
print(f"Log in as the TikTok account for '{label}' and tap Authorize.")
webbrowser.open(auth)
http.server.HTTPServer(("localhost", 8086), H).handle_request()
assert hold.get("state", [""])[0] == state, "state mismatch - start over"

r = requests.post("https://open.tiktokapis.com/v2/oauth/token/",
                  headers={"Content-Type": "application/x-www-form-urlencoded"},
                  data={"client_key": KEY, "client_secret": SECRET,
                        "code": hold["code"][0], "grant_type": "authorization_code",
                        "redirect_uri": REDIRECT}, timeout=60)
r.raise_for_status()
j = r.json()
print("\nopen_id (put in accounts.platform_id):", j.get("open_id"))
print("scopes granted:", j.get("scope"))
print('\nAdd to TIKTOK_TOKENS_JSON:')
print('  "%s": {"refresh_token": "%s"}' % (label, j["refresh_token"]))
