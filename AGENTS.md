# AGENTS.md

Instructions for AI coding assistants working in this repository.

## What this is

Local Python CLI that ingests AI-lab news into one SQLite database (`data/feeds.db`):

| Entrypoint | Source | Config |
|------------|--------|--------|
| `fetch_feeds.py` → `backend.ingest.feeds` | RSS | enabled `feeds` rows (`kind=rss`); seed `feeds.yaml` |
| `fetch_x.py` → `backend.ingest.x` | X API (official brand accounts) | enabled `feeds` rows (`kind=x`); seed `x_accounts.yaml` + `X_BEARER_TOKEN` |
| `backfill.py` → `backend.ingest.backfill` | Anthropic sitemap scrape | CLI flags only |
| `enrich.py` → `backend.ingest.enrich` | Jina Reader (full article markdown) | `JINA_API_KEY` |
| `api.py` / `python -m backend` → `backend.main` | FastAPI read + subscription CRUD + chat | `--db` / `--port` / `--web-dist` / optional `NEWS_ADMIN_TOKEN` |
| `web/` | Vite + React timeline UI | proxies `/api` → FastAPI |
| `scripts/` | Container cron entrypoints | `refresh.py`, `backfill_daily.py` |

All ingest scripts write the same `feeds` / `items` tables. Subscriptions are DB rows (`kind`, `enabled`, X exclude flags). YAML files seed once into an empty/unseeded DB. X also uses `x_accounts` for username→user_id cache. Enrich fills `items.body_*` for article links. Hourly ingest stays in CLIs/cron — not FastAPI background tasks. In production the API also serves the Vite `web/dist` when `WEB_DIST` is set.

**Deploy model (Pattern B):** this OSS repo publishes `ghcr.io/joebuildsstuff/news`. Site-specific Traefik / hostname / secrets live in a private `news-homelab` overlay (same split as remotion-player-diy). Do not put `joe-taylor.me` or SupaGate labels in this repo.

## Layout

```
news/
├── backend/                 # package: API, chat, shared DB, ingest
│   ├── main.py              # FastAPI app + uvicorn CLI (+ SPA when WEB_DIST set)
│   ├── config.py            # repo ROOT, DEFAULT_DB, YAML paths, dotenv
│   ├── db.py                # SQLite schema + upsert/list helpers
│   ├── api/                 # hub + chat routers
│   ├── services/            # chat_db, chat_providers, chat_tools
│   └── ingest/              # feeds, x, backfill, enrich CLIs
├── api.py                   # thin shim → backend.main
├── fetch_feeds.py           # thin shim → backend.ingest.feeds (+ re-exports)
├── fetch_x.py / backfill.py / enrich.py   # thin shims
├── scripts/                 # ofelia / cron entrypoints
├── web/                     # Vite + React + shadcn timeline UI
├── Dockerfile
├── docker-compose.example.yml
├── feeds.yaml
├── x_accounts.yaml
├── requirements.txt
├── .env.example
├── .github/workflows/       # CI + GHCR publish
├── docs/
├── data/                    # gitignored
└── README.md
```

Keep real logic in `backend/`. Root `*.py` files are compatibility shims for cron/docs/`python fetch_feeds.py`. Share DB helpers via `backend.db` (root `fetch_feeds` re-exports for older imports). Self-host docs: [docs/self-hosting.md](./docs/self-hosting.md).

Open product/design ideas live under `docs/feature-requests/`. Read those before inventing overlapping features; update the FR when you implement or decide.

## Invariants (do not break)

1. **One DB, shared schema.** Default path is `data/feeds.db` (override with `DB_PATH`). Schema is created in `backend.db.connect()`; X adds `x_accounts` via `ensure_x_schema()`. Production containers set `DB_JOURNAL_MODE=DELETE`.
2. **Upsert by `(feed_id, guid)`.** Re-runs must be idempotent.
3. **Feed IDs are stable keys.** YAML / UI-created `id` values are primary keys — renaming needs a migration.
4. **Timestamps are UTC ISO-8601 strings** in SQLite text columns.
5. **Secrets stay out of git.** Only `.env.local` / `.env` (gitignored).
6. **`data/` is ephemeral/local.** Never commit the DB. Container DB lives on a named volume; safe to wipe and re-poll.
7. **Subscriptions are DB-backed.** YAML seeds once; UI/API edits persist in `feeds`. Do not treat image-baked YAML as runtime truth after seed.

## Data model

```sql
feeds(id PK, name, url, kind, enabled, exclude_retweets, exclude_replies, username,
      last_fetched_at, last_status, last_error)
items(id, feed_id → feeds, guid, title, link, summary, published_at, fetched_at,
      body_markdown, body_fetched_at, body_status, body_error)
  UNIQUE(feed_id, guid)
x_accounts(username PK COLLATE NOCASE, user_id, resolved_at)  -- X only
app_meta(key PK, value)  -- subscriptions_seeded
```

## Source-specific notes

### RSS (`backend.ingest.feeds`)

- Polls enabled `kind='rss'` rows. `feeds.yaml` is a one-time seed only.
- Anthropic community RSS mirrors are incomplete; backfill fills recent Anthropic news/engineering/research.

### X (`backend.ingest.x`)

- Official `xdk` Client with bearer token; `since_id` after first store; `--days N` backfills.
- Per-account `exclude_retweets` / `exclude_replies` from DB; CLI `--exclude-retweets` / `--include-replies` override for the run.

### Anthropic backfill (`backend.ingest.backfill`)

- Sitemap scrape; default `--delay 0.4`.

### Article body enrich (`backend.ingest.enrich`)

- Jina Reader; skips `feed_id LIKE 'x-%'` by default.

### Read hub (`backend.main` + `web/`)

- FastAPI: `/api/health`, `/api/feeds` (enabled chips), `/api/subscriptions` CRUD, `/api/items`, `/api/items/{id}`.
- Chat persistence and SSE provider routes live in `backend.api.chat` + `backend.services.chat_*`; same SQLite DB and `data/chat` storage root.
- Chat providers are optional: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `XAI_API_KEY`, or `CEREBRAS_API_KEY`; live web tools (`web_search` / `web_scrape`) use `JINA_API_KEY` (preferred) or `FIRECRAWL_API_KEY`.
- Optional `NEWS_ADMIN_TOKEN` gates subscription mutations.
- UI Sources panel: add RSS/X, soft-unsubscribe, per-account include-retweets toggle.
- Dev: API `:8000`, Vite `:5173` proxies `/api`.
- Prod image: same process serves Vite build on `:3000` when `WEB_DIST` is set.

## Commands agents should use

```bash
source .venv/bin/activate
python fetch_feeds.py
python fetch_x.py
python backfill.py --days 7
python enrich.py
python api.py
# or: python -m backend
cd web && pnpm install && pnpm run dev
# container:
cp docker-compose.example.yml docker-compose.yml && docker compose up -d
```

## Coding conventions

- Python 3.11+; `argparse`; `httpx` + `USER_AGENT` from `backend.config`.
- Per-source errors: catch, mark feed, continue — do not abort the whole run.
- Do not move ingest into FastAPI background tasks unless asked.
- Do not add Joe-specific Traefik/hostname config to this OSS repo.
- New Python logic goes under `backend/`; keep root shims thin.

## What not to do

- Do not commit `.env`, `.env.local`, `.venv/`, or `data/`.
- Do not hardcode API tokens.
- Do not replace SQLite without an explicit request.
- Do not add Node/Next/UI layers beyond `web/` unless asked.

## Docs to keep in sync

User-facing changes (flags, env, schema, feeds) → update **both** `README.md` and this file.
