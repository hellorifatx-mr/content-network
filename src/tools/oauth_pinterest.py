"""One-time Pinterest OAuth. Run:  python -m src.tools.oauth_pinterest
Needs PINTEREST_APP_ID and PINTEREST_APP_SECRET in your environment."""
import base64, http.server, os, urllib.parse, webbrowser, requests

APP_ID = os.environ["PINTEREST_APP_ID"]
APP_SECRET = os.environ["PINTEREST_APP_SECRET"]
REDIRECT = "http://localhost:8085/callback"
SCOPES = "boards:read,boards:write,pins:read,pins:write,user_accounts:read"
code_holder = {}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.urlparse(self.path).query
        code_holder.update(urllib.parse.parse_qs(q))
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Done. You can close this tab and return to the terminal.")

    def log_message(self, *a):
        pass


url = ("https://www.pinterest.com/oauth/?" + urllib.parse.urlencode({
    "client_id": APP_ID, "redirect_uri": REDIRECT, "response_type": "code",
    "scope": SCOPES, "state": "setup"}))
print("Opening browser. Log in as the Pinterest business account and click Allow.")
webbrowser.open(url)
http.server.HTTPServer(("localhost", 8085), Handler).handle_request()
code = code_holder["code"][0]

basic = base64.b64encode(f"{APP_ID}:{APP_SECRET}".encode()).decode()
r = requests.post("https://api.pinterest.com/v5/oauth/token",
                  headers={"Authorization": f"Basic {basic}",
                           "Content-Type": "application/x-www-form-urlencoded"},
                  data={"grant_type": "authorization_code", "code": code,
                        "redirect_uri": REDIRECT, "continuous_refresh": "true"},
                  timeout=60)
r.raise_for_status()
j = r.json()
print("\n--- paste these into GitHub Secrets ---")
print("PINTEREST_ACCESS_TOKEN =", j["access_token"])
print("PINTEREST_REFRESH_TOKEN =", j["refresh_token"])
print("\nexpires_in:", j.get("expires_in"),
      "refresh_token_expires_in:", j.get("refresh_token_expires_in"))

boards = requests.get("https://api.pinterest.com/v5/boards",
                      headers={"Authorization": f"Bearer {j['access_token']}"},
                      timeout=60).json()
print("\n--- your board IDs (put these in the accounts tab) ---")
for b in boards.get("items", []):
    print(f"{b['id']}  {b['name']}")
