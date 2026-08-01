# AGENTS.md

Instructions for AI coding assistants working in this repository.

## What this is

Local Python CLI that ingests AI-lab news into one SQLite database (`data/feeds.db`):

| Script | Source | Config |
|--------|--------|--------|
| `fetch_feeds.py` | RSS | `feeds.yaml` |
| `fetch_x.py` | X API (official brand accounts) | `x_accounts.yaml` + `X_BEARER_TOKEN` |
| `backfill.py` | Anthropic sitemap scrape | CLI flags only |
| `enrich.py` | Jina Reader (full article markdown) | `JINA_API_KEY` |
| `api.py` | FastAPI read API over `feeds.db` | `--db` / `--port` / `--web-dist` |
| `web/` | Vite + React timeline UI | proxies `/api` → `api.py` |
| `scripts/` | Container cron entrypoints | `refresh.py`, `backfill_daily.py` |

All ingest scripts write the same `feeds` / `items` tables. X also uses `x_accounts` for username→user_id cache. `enrich.py` fills `items.body_*` for article links. `api.py` is read-only; it does not fetch or enrich. In production it also serves the Vite `web/dist` when `WEB_DIST` is set.

**Deploy model (Pattern B):** this OSS repo publishes `ghcr.io/joebuildsstuff/news`. Site-specific Traefik / hostname / secrets live in a private `news-homelab` overlay (same split as remotion-player-diy). Do not put `joe-taylor.me` or SupaGate labels in this repo.

## Layout

```
news/
├── fetch_feeds.py      # RSS fetch + shared SQLite schema/helpers
├── fetch_x.py          # X poller (imports connect/list/mark/upsert from fetch_feeds)
├── backfill.py         # Anthropic sitemap + page scrape backfill
├── enrich.py           # Jina Reader → items.body_markdown
├── api.py              # FastAPI thin read API (+ static UI in prod)
├── scripts/            # ofelia / cron entrypoints
├── web/                # Vite + React + shadcn timeline UI
├── Dockerfile
├── docker-compose.example.yml
├── feeds.yaml
├── x_accounts.yaml
├── requirements.txt
├── .env.example
├── .github/workflows/  # CI + GHCR publish
├── docs/
├── data/               # gitignored
└── README.md
```

Do not invent a package layout unless asked. Keep ingest scripts at repo root; share DB helpers via imports from `fetch_feeds`. Self-host docs: [docs/self-hosting.md](./docs/self-hosting.md).

Open product/design ideas live under `docs/feature-requests/`. Read those before inventing overlapping features; update the FR when you implement or decide.

## Invariants (do not break)

1. **One DB, shared schema.** Default path is `data/feeds.db` (override with `DB_PATH`). Schema is created in `fetch_feeds.connect()`; X adds `x_accounts` via `ensure_x_schema()`. Production containers set `DB_JOURNAL_MODE=DELETE`.
2. **Upsert by `(feed_id, guid)`.** Re-runs must be idempotent.
3. **Feed IDs are stable keys.** YAML `id` values are primary keys — renaming needs a migration.
4. **Timestamps are UTC ISO-8601 strings** in SQLite text columns.
5. **Secrets stay out of git.** Only `.env.local` / `.env` (gitignored).
6. **`data/` is ephemeral/local.** Never commit the DB. Container DB lives on a named volume; safe to wipe and re-poll.

## Data model

```sql
feeds(id PK, name, url, last_fetched_at, last_status, last_error)
items(id, feed_id → feeds, guid, title, link, summary, published_at, fetched_at,
      body_markdown, body_fetched_at, body_status, body_error)
  UNIQUE(feed_id, guid)
x_accounts(username PK COLLATE NOCASE, user_id, resolved_at)  -- X only
```

## Source-specific notes

### RSS (`fetch_feeds.py`)

- Config: `feeds.yaml` → `id`, `name`, `url`.
- Anthropic community RSS mirrors are incomplete; `backfill.py` fills recent Anthropic news/engineering/research.

### X (`fetch_x.py`)

- Official `xdk` Client with bearer token; `since_id` after first store; `--days N` backfills.

### Anthropic backfill (`backfill.py`)

- Sitemap scrape; default `--delay 0.4`.

### Article body enrich (`enrich.py`)

- Jina Reader; skips `feed_id LIKE 'x-%'` by default.

### Read hub (`api.py` + `web/`)

- FastAPI: `/api/health`, `/api/feeds`, `/api/items`, `/api/items/{id}`.
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
cd web && pnpm install && pnpm run dev
# container:
cp docker-compose.example.yml docker-compose.yml && docker compose up -d
```

## Coding conventions

- Python 3.11+; `argparse`; `httpx` + `USER_AGENT = "news-local-fetcher/1.0 (+local)"`.
- Per-source errors: catch, mark feed, continue — do not abort the whole run.
- Do not move ingest into FastAPI background tasks unless asked.
- Do not add Joe-specific Traefik/hostname config to this OSS repo.

## What not to do

- Do not commit `.env`, `.env.local`, `.venv/`, or `data/`.
- Do not hardcode API tokens.
- Do not replace SQLite without an explicit request.
- Do not add Node/Next/UI layers beyond `web/` unless asked.

## Docs to keep in sync

User-facing changes (flags, env, schema, feeds) → update **both** `README.md` and this file.
