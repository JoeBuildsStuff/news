# FR-002: Personal news hub (read UI + thin API)

| Field | Value |
|-------|-------|
| Status | open |
| Created | 2026-08-01 |
| Updated | 2026-08-01 |
| Related | `fetch_feeds.py`, `fetch_x.py`, `backfill.py`, `enrich.py`, `feeds.yaml`, `x_accounts.yaml`, `data/feeds.db`; future Vite UI + FastAPI |

## Problem

Checking OpenAI blog, Anthropic blog/engineering, and brand X accounts separately is the pain. We want **one central feed** of curated AI-lab news we can open daily — not five tabs.

Ingest is already proven (RSS, X, Anthropic sitemap backfill, optional Jina bodies → one SQLite DB). What is missing:

- A **read experience** (timeline / filters / open link or body)
- A clear path to **add or drop subscriptions** over time (sites, X accounts, later Reddit, etc.)
- Eventually an **always-on** hub (homelab), without forcing that on day one

This is a personal product, not a public news site. Closest existing OptiPlex service is Changedetection, but that answers “did this page change?” — we want “my curated stream.”

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

### 2. Vite SPA + FastAPI over the same SQLite — **preferred**

- FastAPI: HTTP read layer; import `connect` / list helpers from `fetch_feeds.py`.
- Vite: browser timeline; no second database; no tokens in the frontend.
- Pollers remain CLIs (cron/manual); FastAPI does **not** own fetch/enrich as the primary design.

### 3. Vite + Express (rent-price-calculator pattern)

- Matches OptiPlex template language split; duplicates DB access in JS. Worse fit for this Python-first repo.

### 4. Next.js full-stack on OptiPlex from day one

- Heavier than needed; deploy before proving daily read habit.

## Preliminary decisions

Reached 2026-08-01 (discussion; not implemented yet):

1. **Product:** personal AI-news hub. Pollers are the ingestion layer we validated first; the hub is the goal.
2. **UI:** scaffold Vite when ready to de-risk “do I open this daily?”
3. **API:** FastAPI as a **thin read API** over `feeds.db` — correct framing. Not a replacement for pollers; not background-task-first.
4. **Ingest stays Python CLIs** writing the shared schema. New sources = new adapters + YAML (or later config), same `items` table.
5. **Subscriptions:** YAML for now; expect add/remove of sites, X accounts, Reddit, etc. over time. Don’t build subscription CRUD UI first.
6. **Deploy:** stay on the laptop until the read UX is worth opening. OptiPlex later ≈ always-on poller + persistent volume + Traefik/SupaGate Pattern A (`news.joe-taylor.me` or similar) — not bolted into `homelab-dynamic` as an anonymous public app.
7. **Invariants unchanged:** one DB; upsert `(feed_id, guid)`; secrets out of git; UI never becomes a second store.

## Decision

_Scaffold not started — revisit when ready to build the read path._

Preferred stack when implementing: **Vite + FastAPI + existing SQLite**, laptop-first.

## Suggested build order

1. Keep growing YAML subscriptions while learning which sources matter.
2. FastAPI: list/filter recent items (title, source, published_at, link, optional body).
3. Vite: chronological feed + source chips / filters.
4. Promote poller + DB + UI to OptiPlex when always-fresh matters.
5. Extra adapters (Reddit, …) after the hub UX exists.

## Notes

- Homelab context: OptiPlex runs always-on apps; this stays a local data pipeline until the product earns a service slot.
- Firecrawl on the OptiPlex is available for hard scrapes later; current niche correctly uses RSS / X / Jina — don’t force Firecrawl into the happy path.
- Related done work: [FR-001](./FR-001-full-article-body.md) (body enrich).
