# FR-002: Personal news hub (read UI + thin API)

| Field | Value |
|-------|-------|
| Status | done |
| Created | 2026-08-01 |
| Updated | 2026-08-01 |
| Related | `api.py`, `web/`, `fetch_feeds.py`, `fetch_x.py`, `backfill.py`, `enrich.py`, `feeds.yaml`, `x_accounts.yaml`, `data/feeds.db` |

## Problem

Checking OpenAI blog, Anthropic blog/engineering, and brand X accounts separately is the pain. We want **one central feed** of curated AI-lab news we can open daily — not five tabs.

Ingest is already proven (RSS, X, Anthropic sitemap backfill, optional Jina bodies → one SQLite DB). What is missing:

- A **read experience** (timeline / filters / open link or body)
- A clear path to **add or drop subscriptions** over time (sites, X accounts, later Reddit, etc.)
- Eventually an **always-on** host (server or home lab), without forcing that on day one

This is a personal product, not a public news site. Generic page-change monitors answer “did this URL change?” — we want “my curated stream.”

## Target shape

```text
Sources (RSS / X / Reddit / …)
  → adapters (Python CLIs today)
  → data/feeds.db   (one store, upsert on feed_id+guid)
  → FastAPI         (thin read API)
  → Vite UI         (timeline / filter by source)
```

Subscriptions stay config-driven at first (`feeds.yaml`, `x_accounts.yaml`, …). UI-editable subscriptions are out of scope until the feed is sticky.

## Options

### 1. Keep CLIs only (no UI)

- Lowest cost; does not solve the “open one place” problem.

### 2. Vite SPA + FastAPI over the same SQLite — **preferred** / **scaffolded**

- FastAPI: HTTP read layer; import `connect` / list helpers from `fetch_feeds.py`.
- Vite: browser timeline; no second database; no tokens in the frontend.
- Pollers remain CLIs (cron/manual); FastAPI does **not** own fetch/enrich as the primary design.

### 3. Vite + Node/Express API

- Duplicates DB access in JS. Worse fit for this Python-first repo.

### 4. Next.js full-stack on a server from day one

- Heavier than needed; deploy before proving daily read habit.

## Preliminary decisions

Reached 2026-08-01 (discussion; not implemented yet):

1. **Product:** personal AI-news hub. Pollers are the ingestion layer we validated first; the hub is the goal.
2. **UI:** scaffold Vite when ready to de-risk “do I open this daily?”
3. **API:** FastAPI as a **thin read API** over `feeds.db` — correct framing. Not a replacement for pollers; not background-task-first.
4. **Ingest stays Python CLIs** writing the shared schema. New sources = new adapters + YAML (or later config), same `items` table.
5. **Subscriptions:** YAML for now; expect add/remove of sites, X accounts, Reddit, etc. over time. Don’t build subscription CRUD UI first.
6. **Deploy:** stay on the laptop until the read UX is worth opening. A later always-on deploy is reverse-proxied and authenticated — not an anonymous public app.
7. **Invariants unchanged:** one DB; upsert `(feed_id, guid)`; secrets out of git; UI never becomes a second store.

## Decision

**Scaffolded for local testing (2026-08-01):**

- `api.py` — FastAPI on `:8000` (`/api/health`, `/api/feeds`, `/api/items`, `/api/items/{id}`)
- `web/` — Vite + React + shadcn timeline, typeset article body, light/dark mode toggle
- Run: `python api.py` and `cd web && pnpm run dev` → http://127.0.0.1:5173

Local read path is in place. **MVP done** (laptop hub). **Pattern B self-host scaffolded (2026-08-01):** GHCR image from this OSS repo + private `news-homelab` overlay (Traefik/ofelia) — see [docs/self-hosting.md](../self-hosting.md). Follow-ups: cut over on OptiPlex, subscription CRUD UI, extra adapters.
## Suggested build order

1. Keep growing YAML subscriptions while learning which sources matter.
2. ~~FastAPI: list/filter recent items~~ done (`api.py`)
3. ~~Vite: chronological feed + source chips / filters~~ done (`web/`)
4. ~~Always-on host~~ Pattern B (GHCR + private overlay); cut over remaining.
5. Extra adapters (Reddit, …) after the hub UX exists.

## Notes

- Prefer RSS / X / Jina for this niche; don’t force a general scrape platform into the happy path.
- Related done work: [FR-001](./FR-001-full-article-body.md) (body enrich).
- Self-host: [self-hosting.md](../self-hosting.md). Homelab overlay is private (not in this repo).
