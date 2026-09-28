# content-network

A configuration-driven, multi-platform publishing system for one operator running
their own Facebook Pages, Instagram accounts, Pinterest boards, TikTok accounts and
YouTube channels.

**Full documentation lives in the ClickUp playbook.** This README is the short version.

## How it works

```
Google Drive (media, one folder per category)
Google Sheet "Cockpit" (categories, accounts, routing, frequency, on/off)
        |
        v
GitHub Actions  ->  scan (find content)  ->  plan (build tomorrow's jobs)
                ->  publish (hourly)     ->  report (daily summary)
        |
        v
data/state.db  (SQLite ledger, committed every run = free versioned backup)
        |
        +--> Facebook / YouTube  : handed a future timestamp, platform publishes exactly on time
        +--> Instagram / Pinterest / TikTok : published live by the hourly run
```

Facebook and YouTube use **native API scheduling**, so GitHub's cron delays never
affect them. Instagram needs a public media URL, so a file is briefly staged in a
Cloudflare R2 bucket and deleted immediately after publishing.

## Repository map

| Path | What it is |
|---|---|
| `.github/workflows/` | The five schedules: scan, plan, publish, report, tokens |
| `src/lib/` | Shared plumbing: config, ledger, Drive, staging, media, captions |
| `src/publishers/` | One file per platform, identical interface. Add a platform = add a file |
| `src/tools/` | Run on your own PC: the one-time OAuth flows and `doctor` preflight |
| `src/scan.py` | Reads Drive into the `content` table. Creates no jobs |
| `src/plan.py` | Picks content, creates jobs, hands FB/YT their scheduled times |
| `src/publish.py` | Hourly worker: claims due jobs, publishes, retries, verifies |
| `src/report.py` | Daily summary into the Sheet dashboard + run summary |
| `data/state.db` | The ledger. Committed by workflows. Never contains media |
| `config/snapshot.json` | Last known-good copy of the Cockpit Sheet |
| `local-tools/` | `normalize.bat` (ffmpeg preset) and a `_meta.csv` example |

## First run, in order

1. Make this repo **Public** (free unlimited Actions minutes).
2. Add the secrets and variables listed in `SETUP.md`.
3. Actions -> **scan** -> Run workflow.
4. Actions -> **plan** -> Run workflow with `dry_run = true`. Read the log.
5. Actions -> **publish** -> Run workflow with `dry_run = true`.
6. Only then turn `dry_run` off, on one category.

## Safety properties (do not remove these)

- `UNIQUE(content_id, account_key)` in the ledger makes a duplicate post impossible.
- `concurrency: group: ledger` means exactly one writer at a time.
- `external_ref` is saved **before** the irreversible publish call, so a crash is
  resolved by asking the platform instead of guessing.
- Drive credentials are **read-only** — the automation cannot delete your library.
- Errors classed `POLICY` or `MEDIA` are **never retried**.

## Emergency stop

Actions -> `publish` -> ... -> **Disable workflow**. Also cancel any already-scheduled
Facebook posts in Meta Business Suite -> Planner.
