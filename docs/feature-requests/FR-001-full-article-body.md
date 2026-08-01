# FR-001: Fetch and store full article body

| Field | Value |
|-------|-------|
| Status | done |
| Created | 2026-08-01 |
| Updated | 2026-08-01 |
| Related | `enrich.py`, `fetch_feeds.py`, `items.body_*`, Jina Reader (`JINA_API_KEY`) |

## Problem

Today we only store RSS/scrape **teasers** in `items.summary`:

- OpenAI RSS: ~1–2 sentence blurb
- Anthropic: short description (og:description / feed summary)

Neither OpenAI’s official RSS nor Anthropic’s community mirrors reliably include the full post body. Full text requires a follow-up fetch of `items.link`.

We want a clear path to retrieve and optionally persist full articles for reading, search, or later LLM use — without bloating the happy path until we pick an approach.

## Decision

**Implemented with Jina Reader** (`enrich.py`):

- Schema: `items.body_markdown`, `body_fetched_at`, `body_status` (`ok` \| `error` \| `skipped`), `body_error`
- Request defaults (validated vs alternatives): JSON + default Readability `content` (do **not** force `X-Respond-With: markdown`, which bypasses cleanup), `X-Retain-Images: none`, `X-Retain-Media: none`, `X-Remove-Selector: nav,header,footer`
- X posts skipped by default (full text already in `summary`)
- Separate second-pass script; does not block RSS/X fetches

## Current state

```text
items: title, link, summary, published_at, body_markdown, body_status, …
```

Run: `python enrich.py` (needs `JINA_API_KEY` in `.env.local`).

## Options considered

### 1. Local scrape (httpx + trafilatura / readability-lxml)

- Free, in-process; fragile on JS-heavy OpenAI/Anthropic SPAs.

### 2. Firecrawl (or similar scrape API)

- Reliable JS rendering; paid credits.

### 2b. Jina Reader (`r.jina.ai`) — **chosen**

- Hosted URL→markdown; bearer auth; good results on OpenAI + Anthropic in testing.
- Cost/rate limits per Jina account.

### 3. Browser automation (Playwright / agent-browser)

- Heaviest local runtime; overkill unless Jina fails.

### 4. Full-text RSS proxies

- Less control; dependency risk.

### 5. On-demand only (don’t store)

- Lower complexity; skipped in favor of persisted bodies for offline/search/LLM use.

## Notes

- Discussed 2026-07-31 / 2026-08-01; implemented 2026-08-01.
- A/B on OpenAI article: default `content` + remove selectors beat forced markdown and `readerlm-v2` (latter truncated).
