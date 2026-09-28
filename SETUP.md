# SETUP — get this running

## 1. Create the repo and push these files

**Easiest (no terminal):**
1. Go to https://github.com/new — name it `content-network`, set **Public**, create it.
2. Install https://desktop.github.com/ , sign in, **File -> Clone repository** -> pick it.
3. Copy **everything** from this extracted folder into the cloned folder, including the
   hidden `.github` folder.
4. In GitHub Desktop: type a summary ("initial commit") -> **Commit to main** -> **Push origin**.

> Why GitHub Desktop and not the browser upload: the browser sometimes drops folders whose
> name starts with a dot, and `.github/workflows/` is the folder that makes everything run.
> If you do use the browser, upload `.github/workflows/*.yml` separately and confirm all five
> files are there.

**If you have git installed:**
```
cd content-network
git init
git add .
git commit -m "initial commit"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/content-network.git
git push -u origin main
```

## 2. Secrets — Settings -> Secrets and variables -> Actions -> Secrets

| Secret | Value |
|---|---|
| `GOOGLE_SA_JSON` | The entire contents of the service-account JSON file |
| `SHEET_ID` | The long id in the Cockpit Sheet's URL |
| `DRIVE_ROOT_ID` | Folder id of `Social Content` |
| `META_SYSTEM_TOKEN` | System-user token with the pages_* + instagram_* scopes |
| `PINTEREST_APP_ID` / `PINTEREST_APP_SECRET` | From the Pinterest app dashboard |
| `PINTEREST_ACCESS_TOKEN` / `PINTEREST_REFRESH_TOKEN` | Output of `oauth_pinterest.py` |
| `TIKTOK_CLIENT_KEY` / `TIKTOK_CLIENT_SECRET` | From the TikTok app |
| `TIKTOK_TOKENS_JSON` | `{"nature":{"refresh_token":"..."}}` — one object, all accounts |
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | Desktop OAuth client (YouTube) |
| `YOUTUBE_TOKENS_JSON` | `{"nature":{"refresh_token":"..."}}` per channel |
| `R2_ACCOUNT_ID` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` | Cloudflare R2, bucket-scoped |
| `REPO_PAT` | Optional: fine-grained PAT with Secrets read+write on this repo |
| `GMAIL_USER` / `GMAIL_APP_PASSWORD` | Optional: emailed daily report |

Only `GOOGLE_SA_JSON`, `SHEET_ID`, `DRIVE_ROOT_ID` and `META_SYSTEM_TOKEN` are needed
for the Facebook + Instagram V1. Add the rest as each platform gets approved.

## 3. Variables — same page, the **Variables** tab

| Variable | Value |
|---|---|
| `R2_BUCKET` | `content-staging` |
| `R2_PUBLIC_BASE` | `https://pub-xxxx.r2.dev` (your bucket's public dev URL) |
| `PINTEREST_TIER` | `trial` until Standard access is granted, then `standard` |

Variables are visible in logs. Never put a token in one.

## 4. Enable GitHub Pages for the privacy policy

Settings -> Pages -> Source: *Deploy from a branch* -> branch `main`, folder `/docs` -> Save.
Edit `docs/privacy.md` first and replace the contact email.
Your URL becomes `https://YOUR-USERNAME.github.io/content-network/privacy`.

## 5. Run the preflight

Actions -> **scan** -> Run workflow. Then check `data/export/content.csv` in the repo.

To run `doctor` locally on Windows:
```
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
set GOOGLE_SA_JSON={"type":"service_account",...}
set SHEET_ID=...
set DRIVE_ROOT_ID=...
set META_SYSTEM_TOKEN=...
py -m src.tools.doctor
```

## 6. Never commit

Passwords, tokens, the service-account JSON, `client_secret*.json`, or any media file.
`.gitignore` blocks the obvious cases, but it is not a substitute for care. If you ever
paste a secret into a file here, **rotate that credential immediately** — public git
history is permanent.
