# FR-003: News hub chat assistant

**Status:** implemented (ported from `new-job-title`)  
**Date:** 2026-08-08

## Summary

Port the floating chat panel from [new-job-title](https://new-job-title.joe-taylor.me/) into this Vite + FastAPI news hub so you can ask questions about stored items and (optionally) the live web.

## What landed

- **UI:** `web/src/components/chat/*` + shell (`ChatFooterBar` pinned at bottom of `h-dvh` column, `ChatPanel` floating or inset) mounted from `ChatShell` in `main.tsx` — same chrome as tech-stack-010226 dashboard (tabs + Ask Chat + history); inset mode is an in-flow right column that pushes hub content left (not a sheet overlay); floating `ChatBubble` is not the entry point
- **Client persistence API:** `web/src/actions/chat.ts` → FastAPI `/api/chat/*` (replaced Next.js server actions)
- **Backend:** `backend/services/chat_{db,tools,providers}.py` + `backend/api/chat.py` on the same SQLite DB (`chat_*` tables) + `data/chat` attachments
- **Tools:** `news_search`, `news_get_item`, `news_list_feeds`; live `web_search` / `web_scrape` via Jina (`JINA_API_KEY`, preferred) or Firecrawl (`FIRECRAWL_API_KEY`)
- **Providers:** Anthropic / OpenAI / xAI / Cerebras SSE (same event protocol as the source app)

## Env

See `.env.example`: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `XAI_API_KEY`, `CEREBRAS_API_KEY`, `JINA_API_KEY` (enrich + live web), optional `FIRECRAWL_API_KEY`, `LOCAL_CHAT_USER_ID`, `CHAT_STORAGE_DIR`.

## Out of scope / follow-ups

- Fullpage `/workspace/chat/[id]` route (source app also lacked a working page; inset/floating only)
- Job-market / profile tools from new-job-title (intentionally dropped)
- Auth beyond local soft user id

## Fixes since land

- Persist `chat_messages.model` for assistant/user turns
- OpenAI gpt-5.* uses `/v1/responses` so tools + `reasoning_effort` work together
- Chat title generation: handle empty Cerebras content, raise token budget, fall back to Anthropic

## Source management via chat (2026-08-08)

Chat can manage Sources with the same DB helpers as the Sources panel (`backend.services.subscriptions`):

- `news_list_subscriptions` — all feeds including disabled + X flags
- `news_add_subscription` — RSS (`name` + `url`) or X (`name` + `username`)
- `news_update_subscription` — rename / RSS url / `enabled` / `exclude_retweets` / `exclude_replies`
- `news_unsubscribe` — soft-disable (keep history)

Successful mutation tool results dispatch `news:subscriptions-changed` so timeline chips and an open Sources panel refresh. Note: chat mutations are not gated by `NEWS_ADMIN_TOKEN` (chat HTTP routes are open); use network exposure carefully.
