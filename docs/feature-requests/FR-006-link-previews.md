# FR-006: Link, image, and video previews

| Field | Value |
|-------|-------|
| Status | done |
| Created | 2026-09-12 |
| Updated | 2026-09-12 |
| Related | `items.media_json`, `link_previews`, `backend.ingest.x`, `backend.services.link_previews`, hub reader |

## Problem

X posts store tweet text with raw `t.co` URLs. Native photos, videos, and website cards never reached the reader: the hub showed one optional `image_url` (often missing) and left links as text. Brand threads (e.g. OpenAI product launches) look like a paste of timestamps plus `https://t.co/…` instead of the image, playable video, or article card you see on X.

Unfurling those `t.co` links at read time is not enough. Photo/video shorts land on `x.com/.../photo/1` or `/video/1` HTML, not a hotlinkable file. OpenAI article pages also 403 anonymous scrapers. The X API already returns `includes.media` (photo URL, video `variants`) and `entities.urls` (title, description, card images).

## Options

1. **Store X media + URL entities at ingest** — request `entities` and media `variants`; persist a JSON list on the item; render in the reader.
2. **Client-only unfurl of `t.co`** — works for some websites; cannot play native X video or reliably get photos.
3. **Proxy every URL through Jina/Firecrawl** — extra keys, slower, still misses X CDN media.

## Decision

**Implemented:** option 1, with option 2 as a fallback for leftover URLs that were not in `media_json`.

- `items.media_json` — list of `{kind: photo|video|website, url, …, tco}`.
- `image_url` stays the timeline thumb (first photo, else video preview, else website image).
- Reader strips previewed URLs from the post text, shows `<img>`, `<video controls>` (best mp4 variant), or a website card.
- X animated GIFs stay `kind: video` with `gif: true` (older rows are detected from `/tweet_video/` URLs). The reader loops them muted. `video.twimg.com` 403s `<video>` loads that send a Referer, and Chrome ignores `referrerpolicy` on media elements, so the reader streams those mp4s via `GET /api/media/video` (host allowlist + URL must already be on an item).
- `POST /api/unfurl` caches previews in `link_previews` for URLs that already appear on a stored item (SSRF: public hosts only). Native X status/photo/video pages are skipped.
- Re-run `python fetch_x.py --days N` to backfill existing posts.

## Notes

YouTube/Vimeo leftover links embed via youtube-nocookie / player.vimeo. RSS article bodies still use the existing markdown + `image_url` hero.
