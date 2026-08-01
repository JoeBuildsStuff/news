# news

Local fetcher that pulls AI-lab RSS feeds and X (Twitter) brand posts into one SQLite database.

Designed for scheduled polling on a laptop or homelab: small scripts, YAML config, no server.

For AI coding assistants, see [AGENTS.md](./AGENTS.md).

## What it stores

Everything lands in `data/feeds.db` (gitignored):

| Source | Script | How items are keyed |
|--------|--------|---------------------|
| RSS | `fetch_feeds.py` | `(feed_id, guid)` from the feed entry |
| X posts | `fetch_x.py` | `(feed_id, post_id)` — post id as `guid` |
| Anthropic site | `backfill.py` | `(feed_id, article_url)` when RSS mirrors miss posts |

Re-runs upsert; duplicates are skipped/updated, not doubled.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy env template and add an X bearer token (only needed for the X poller):

```bash
cp .env.example .env.local
```

```bash
X_BEARER_TOKEN=...
X_CONSUMER_KEY=...   # optional for this poller
X_SECRET_KEY=...     # optional for this poller
```

`fetch_x.py` uses app-only auth (`X_BEARER_TOKEN` only).

The developer App must be attached to a **Project** with API access (pay-per-use) at [console.x.com](https://console.x.com). If you see `client-not-enrolled` / 403, enroll there, then regenerate the bearer token.

## Usage

### Fetch RSS

```bash
python fetch_feeds.py
```

### Fetch X posts

Polls accounts in `x_accounts.yaml` (OpenAI / Anthropic brand handles):

```bash
python fetch_x.py
```

After the first run, polls use `since_id` so you mostly pay for new posts. User IDs are resolved once and cached in `x_accounts`.

Backfill recent posts (paginates; ignores `since_id`):

```bash
python fetch_x.py --days 7
```

Useful flags: `--max-results` (5–100), `--include-replies`, `--exclude-retweets`.

### Backfill Anthropic blog

Anthropic has no official RSS, and community mirrors miss posts. This scrapes their sitemap + article pages and keeps anything published in the last N days:

```bash
python backfill.py --days 7
```

Sections default to `news,engineering,research`. OpenAI blog history already comes from RSS (`python fetch_feeds.py`).

### Browse recent items

```bash
python fetch_feeds.py --list
python fetch_x.py --list --limit 50
```

Or query SQLite:

```bash
sqlite3 data/feeds.db "SELECT title, link, published_at FROM items ORDER BY published_at DESC LIMIT 20;"
```

## Configure

| File | Purpose |
|------|---------|
| `feeds.yaml` | RSS feeds (`id`, `name`, `url`) |
| `x_accounts.yaml` | X accounts (`id`, `name`, `username`) |
| `.env.local` | `X_BEARER_TOKEN` (and optional OAuth1 keys) |

Feed/account `id` values are stable primary keys in SQLite — renaming one orphans old rows.

## Schema (overview)

```
feeds        — one row per configured source (RSS or X account)
items        — articles/posts; UNIQUE(feed_id, guid)
x_accounts   — username → user_id cache for the X API
```

Shared helpers and schema live in `fetch_feeds.connect()`. X and backfill reuse that connection/schema.

## Schedule (optional)

Hourly via cron:

```bash
crontab -e
```

```cron
0 * * * * cd /path/to/news && .venv/bin/python fetch_feeds.py >> data/fetch.log 2>&1
5 * * * * cd /path/to/news && .venv/bin/python fetch_x.py >> data/fetch_x.log 2>&1
```

Replace `/path/to/news` with your clone path. Ensure `data/` exists (scripts create the DB parent dir on first run).

## Project layout

```
fetch_feeds.py     RSS ingest + shared DB schema
fetch_x.py         X API poller
backfill.py        Anthropic sitemap scrape
feeds.yaml         RSS config
x_accounts.yaml    X accounts
requirements.txt
.env.example
AGENTS.md          guidance for coding agents
data/              local DB + logs (gitignored)
```
