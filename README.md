# news

Local fetcher that pulls AI-lab RSS feeds and X (Twitter) brand posts into one SQLite database, plus an optional local read UI.

Designed for scheduled polling on a laptop or homelab: small scripts, SQLite-backed subscriptions (YAML seed), thin FastAPI + Vite for browsing.

For AI coding assistants, see [AGENTS.md](./AGENTS.md). Feature ideas and design notes: [docs/](./docs/).

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

Copy env template and add tokens:

```bash
cp .env.example .env.local
```

```bash
X_BEARER_TOKEN=...
X_CONSUMER_KEY=...   # optional for this poller
X_SECRET_KEY=...     # optional for this poller
JINA_API_KEY=...     # enrich.py + chat live web tools (r.jina.ai / s.jina.ai)
NEWS_ADMIN_TOKEN=... # optional; required for Sources mutations when set
ANTHROPIC_API_KEY=... # optional; enables Anthropic chat
CEREBRAS_API_KEY=...  # optional; enables Cerebras chat/title generation
OPENAI_API_KEY=...    # optional; enables OpenAI chat
XAI_API_KEY=...       # optional; enables xAI chat
FIRECRAWL_API_KEY=... # optional; alternate live web backend if Jina unset
```

`fetch_x.py` uses app-only auth (`X_BEARER_TOKEN` only). `enrich.py` and chat `web_scrape` / `web_search` use `JINA_API_KEY` for [Jina Reader](https://r.jina.ai/docs) / [Search](https://s.jina.ai/). Set `FIRECRAWL_API_KEY` instead only if you want Firecrawl as the live-web backend.

The developer App must be attached to a **Project** with API access (pay-per-use) at [console.x.com](https://console.x.com). If you see `client-not-enrolled` / 403, enroll there, then regenerate the bearer token.

## Usage

### Fetch RSS

Polls enabled `kind=rss` rows in SQLite (seeded once from `feeds.yaml`):

```bash
python fetch_feeds.py
```

### Fetch X posts

Polls enabled `kind=x` rows in SQLite (seeded once from `x_accounts.yaml`):

```bash
python fetch_x.py
```

After the first run, polls use `since_id` so you mostly pay for new posts. User IDs are resolved once and cached in `x_accounts`. Per-account retweet/reply exclusions come from the DB; CLI flags override for that run.

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

### Enrich full article bodies (Jina)

Fetches markdown for each article `link` via Jina Reader and stores it on `items`. X posts are skipped by default (tweet text is already in `summary`). Safe to re-run; only pending rows are processed.

```bash
python enrich.py                 # backfill all pending articles
python enrich.py --days 30       # only recent items
python enrich.py --limit 10      # smoke test
python enrich.py --status        # counts by body_status
python enrich.py --retry-errors  # retry failed fetches
```

Useful flags: `--feed openai`, `--delay 0.4`, `--include-x`.

### Browse in the browser (local hub)

FastAPI over `data/feeds.db` + Vite timeline UI. Pollers stay separate CLIs. Use the gear icon → **Sources** to add/remove RSS or X subscriptions and toggle retweets.

Terminal 1 — API:

```bash
source .venv/bin/activate
python api.py
# http://127.0.0.1:8000/api/items
```

Terminal 2 — UI (proxies `/api` to the API):

```bash
cd web && pnpm install && pnpm run dev
# http://127.0.0.1:5173
```

Useful API routes: `GET /api/health`, `/api/feeds`, `/api/subscriptions`, `/api/items?feed_id=openai`, `/api/items/{id}`; mutations `POST|PATCH|DELETE /api/subscriptions`. Chat sessions and provider SSE endpoints live under `/api/chat/*`; attachments use `/api/files/*` and `/api/images/*`.

### Browse recent items (CLI)

```bash
python fetch_feeds.py --list
python fetch_x.py --list --limit 50
```

Or query SQLite:

```bash
sqlite3 data/feeds.db "SELECT title, link, published_at FROM items ORDER BY published_at DESC LIMIT 20;"
sqlite3 data/feeds.db "SELECT title, length(body_markdown), body_status FROM items WHERE body_status = 'ok' LIMIT 5;"
```

## Configure

Subscriptions live in SQLite (`feeds` rows with `kind`, `enabled`, X flags). Manage them from the **Sources** panel in the UI (gear icon), or seed once from YAML on a fresh DB.

| File / env | Purpose |
|------|---------|
| `feeds.yaml` | One-time RSS seed (`id`, `name`, `url`) |
| `x_accounts.yaml` | One-time X seed (`id`, `name`, `username`) |
| `.env.local` | feed tokens, optional `NEWS_ADMIN_TOKEN`, chat provider keys, `CHAT_STORAGE_DIR` |

Feed/account `id` values are stable primary keys in SQLite — renaming one orphans old rows. Unsubscribing soft-disables (`enabled=0`); history stays. Per-account “Include retweets” is stored as `exclude_retweets` on X rows (`python fetch_x.py --exclude-retweets` still forces exclude for that run).

When `NEWS_ADMIN_TOKEN` is set, Sources mutations need `Authorization: Bearer …` (the UI stores the token in sessionStorage).

## Schema (overview)

```
feeds        — subscriptions (RSS or X): kind, enabled, exclude_retweets,
               exclude_replies, username + fetch status columns
items        — articles/posts; UNIQUE(feed_id, guid)
             — optional body_markdown / body_status from enrich.py
x_accounts   — username → user_id cache for the X API
app_meta     — one-time seed flag (subscriptions_seeded)
chat_*       — local chat sessions, messages, attachments, tools, and branches
```

Shared helpers and schema live in `backend.db.connect()`. X, Anthropic backfill, and enrich reuse that connection/schema.

## Schedule (optional)

### Laptop cron

```bash
crontab -e
```

```cron
0 * * * * cd /path/to/news && .venv/bin/python fetch_feeds.py >> data/fetch.log 2>&1
5 * * * * cd /path/to/news && .venv/bin/python fetch_x.py >> data/fetch_x.log 2>&1
```

Replace `/path/to/news` with your clone path. Ensure `data/` exists (scripts create the DB parent dir on first run).

### Docker / homelab

Prebuilt image: `ghcr.io/joebuildsstuff/news:latest` (published on push to `main`).

```bash
cp docker-compose.example.yml docker-compose.yml
cp .env.example .env   # set X_BEARER_TOKEN, JINA_API_KEY
docker compose up -d
# http://127.0.0.1:3000
```

Includes optional ofelia sidecar (hourly refresh + daily Anthropic backfill). Wipe the volume anytime and re-poll to rebuild the DB. Details: [docs/self-hosting.md](./docs/self-hosting.md).

Site-specific Traefik / hostname overlays belong in a private `*-homelab` repo (same pattern as remotion-player-diy).

## Project layout

```
backend/                    FastAPI, chat, shared DB, ingest CLIs
api.py                      shim → backend.main (also: python -m backend)
fetch_feeds.py              shim → backend.ingest.feeds (+ DB re-exports)
fetch_x.py / backfill.py / enrich.py   shims → backend.ingest.*
web/                        Vite + React + shadcn timeline UI
scripts/                    Container cron entrypoints (refresh / backfill)
feeds.yaml                  RSS seed config
x_accounts.yaml             X seed accounts
Dockerfile                  multi-stage: Vite build + Python runtime
docker-compose.example.yml  generic web + poller + ofelia
.github/workflows/          CI + GHCR publish
requirements.txt
.env.example
AGENTS.md                   guidance for coding agents
docs/                       docs + feature requests
data/                       local DB + logs (gitignored)
```

Shared schema/helpers live in `backend.db`. Root scripts stay as thin entrypoints for cron and docs.
