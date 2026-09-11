# FR-004: Store and display item images

| Field | Value |
|-------|-------|
| Status | done |
| Created | 2026-09-10 |
| Updated | 2026-09-10 |
| Related | `items.image_url`, `backend.db`, `backend.ingest.x`, `backend.ingest.backfill`, hub UI |

## Problem

The hub stored title/link/summary only. OpenAI and Anthropic RSS are text teasers with no `media:content` / enclosures, so a feed-parser-only approach would leave the default sources imageless. X posts often have photos that we were dropping.

## Decision

**Implemented:** one `items.image_url` text column (remote URL, not a blob store).

1. **RSS** — use media/enclosures/HTML `<img>` when the feed has them; otherwise GET the article page and parse `og:image` / `twitter:image`. Cap extra fetches with `--fill-images` (default 25 per feed per run) so hourly polls do not hammer OpenAI’s 1k-entry RSS.
2. **X** — request `attachments.media_keys` + media fields; store the first photo URL or video preview.
3. **Anthropic backfill** — parse `og:image` from HTML already fetched for title/summary.
4. **UI** — timeline thumbnail + reader hero. Broken hotlinks hide via `onError`.

Article-body enrich still uses `X-Retain-Images: none` (inline markdown images stay out of `body_markdown`).

## Notes

Existing rows fill on subsequent `fetch_feeds.py` / `fetch_x.py` / `backfill.py` runs. Raise `--fill-images` to catch up faster.
