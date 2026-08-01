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
| `api.py` | FastAPI read API over `feeds.db` | `--db` / `--port` |
| `web/` | Vite + React timeline UI | proxies `/api` → `api.py` |

All ingest scripts write the same `feeds` / `items` tables. X also uses `x_accounts` for username→user_id cache. `enrich.py` fills `items.body_*` for article links. `api.py` is read-only; it does not fetch or enrich.

## Layout

```
news/
├── fetch_feeds.py      # RSS fetch + shared SQLite schema/helpers
├── fetch_x.py          # X poller (imports connect/list/mark/upsert from fetch_feeds)
├── backfill.py         # Anthropic sitemap + page scrape backfill
├── enrich.py           # Jina Reader → items.body_markdown
├── api.py              # FastAPI thin read API (FR-002)
├── web/                # Vite + React + shadcn timeline UI
├── feeds.yaml          # RSS feed list
├── x_accounts.yaml     # X accounts to poll
├── requirements.txt
├── .env.example        # copy → .env.local
├── docs/               # human docs + feature requests (see docs/feature-requests/)
├── data/               # gitignored: feeds.db, logs
└── README.md           # human setup/usage
```

Do not invent a package layout unless asked. Keep ingest scripts at repo root; share DB helpers via imports from `fetch_feeds`. The read UI lives under `web/` with `api.py` as the HTTP edge.

Open product/design ideas live under `docs/feature-requests/` (e.g. FR-001 full article body, FR-002 personal news hub). Read those before inventing overlapping features; update the FR when you implement or decide.

## Invariants (do not break)

1. **One DB, shared schema.** Default path is `data/feeds.db`. Schema is created in `fetch_feeds.connect()`; X adds `x_accounts` via `ensure_x_schema()`. Prefer extending that path over ad-hoc `CREATE TABLE` elsewhere.
2. **Upsert by `(feed_id, guid)`.** Re-runs must be idempotent. Never insert duplicates for the same logical item.
3. **Feed IDs are stable keys.** YAML `id` values (`openai`, `x-anthropicai`, `anthropic-news`, …) are primary keys. Renaming an id orphans or duplicates rows—treat as a migration.
4. **Timestamps are UTC ISO-8601 strings** in SQLite text columns.
5. **Secrets stay out of git.** Only `.env.local` / `.env` (gitignored). `fetch_x.py` needs `X_BEARER_TOKEN`; `enrich.py` needs `JINA_API_KEY`.
6. **`data/` is ephemeral/local.** Never commit the DB or fetch logs.

## Data model

```sql
feeds(id PK, name, url, last_fetched_at, last_status, last_error)
items(id, feed_id → feeds, guid, title, link, summary, published_at, fetched_at,
      body_markdown, body_fetched_at, body_status, body_error)
  UNIQUE(feed_id, guid)
x_accounts(username PK COLLATE NOCASE, user_id, resolved_at)  -- X only
```

- RSS/backfill: `guid` is feed entry id/link (or article URL for Anthropic scrape).
- X: `guid` is the numeric post id (string). Incremental polls use `ORDER BY CAST(guid AS INTEGER)` + `since_id`.
- X posts are stored as `items` with `feeds.id` from `x_accounts.yaml` (e.g. `x-openai`), not a separate posts table.
- `body_*`: filled by `enrich.py` via Jina Reader. Status is `ok` | `error` | `skipped`. X posts default to `skipped` (text already in `summary`).

## Source-specific notes

### RSS (`fetch_feeds.py`)

- Config: `feeds.yaml` → list under `feeds:` with `id`, `name`, `url`.
- Anthropic community RSS mirrors are incomplete; `backfill.py` fills recent Anthropic news/engineering/research.
- OpenAI history comes from official RSS—do not scrape openai.com unless asked.

### X (`fetch_x.py`)

- Uses official `xdk` Client with bearer token.
- Default: exclude replies; one page; `since_id` after first successful store.
- `--days N` backfills (paginates, ignores `since_id`).
- User IDs cached in `x_accounts`; only re-resolve if cache miss.
- On `client-not-enrolled` / 403: app must be in a Project with API access at console.x.com; regenerate bearer after enroll.

### Anthropic backfill (`backfill.py`)

- Sitemap `https://www.anthropic.com/sitemap.xml`, sections `news` / `engineering` / `research`.
- Scrapes og:title / og:description + published date from HTML; brittle against site redesigns.
- Default `--delay 0.4` between page fetches—keep polite rate limits.

### Article body enrich (`enrich.py`)

- Needs `JINA_API_KEY`. Calls `https://r.jina.ai/{url}` with `Accept: application/json`, `X-Retain-Images: none`, `X-Retain-Media: none`, `X-Remove-Selector: nav,header,footer` (default Readability `content`, not raw `markdown`).
- Idempotent: only rows with `body_status IS NULL` (or `--retry-errors`). Does not block `fetch_feeds.py` / `fetch_x.py`.
- Skips `feed_id LIKE 'x-%'` by default; copies `summary` into `body_markdown` and marks `skipped`.

### Read hub (`api.py` + `web/`)

- FastAPI imports `connect` from `fetch_feeds`; serves `GET /api/health`, `/api/feeds`, `/api/items`, `/api/items/{id}`.
- Does **not** run fetch/enrich. CORS allows Vite on `:5173`; Vite proxies `/api` in dev.
- UI: chronological timeline + source chips; detail pane shows `body_markdown` when enriched, else summary.

## Commands agents should use

```bash
source .venv/bin/activate   # or: python3 -m venv .venv && pip install -r requirements.txt
python fetch_feeds.py
python fetch_x.py
python fetch_x.py --days 7
python backfill.py --days 7
python enrich.py
python enrich.py --status
python fetch_feeds.py --list --limit 20
python fetch_x.py --list --limit 50
python api.py                              # read API on :8000
cd web && pnpm install && pnpm run dev       # UI on :5173
```

Optional paths: `--config`, `--db` on the fetch scripts; `--db`, `--port`, `--reload` on `api.py`.

## Coding conventions

- Python 3.11+ style: `from __future__ import annotations`, type hints on public helpers, 4-space indent.
- CLI: `argparse`, kebab-case flags.
- HTTP: `httpx` with `USER_AGENT = "news-local-fetcher/1.0 (+local)"` for RSS/scrape.
- Per-source errors: catch, `mark_feed(..., status="error")`, print to stderr, continue other feeds/accounts—do not abort the whole run on one failure.
- Prefer extending existing scripts over new frameworks, ORMs, or async rewrites unless requested.
- Do not move ingest ownership into FastAPI background tasks unless explicitly asked (FR-002: thin read API).
- When adding a feed/account: edit YAML only if no code change is needed; document in README if behavior/flags/env change.

## What not to do

- Do not commit `.env`, `.env.local`, `.venv/`, or `data/`.
- Do not hardcode API tokens.
- Do not replace SQLite without an explicit request.
- Do not “fix” Anthropic RSS by swapping to unofficial scrapers in `feeds.yaml` without noting that `backfill.py` exists for that gap.
- Do not add Node/Next/UI layers beyond the existing `web/` Vite app unless the user asks.

## Docs to keep in sync

User-facing changes (new flags, env vars, feeds, schema) → update **both** `README.md` and this file.
