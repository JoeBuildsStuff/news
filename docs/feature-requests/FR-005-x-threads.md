# FR-005: Group same-author X replies as threads

| Field | Value |
|-------|-------|
| Status | done |
| Created | 2026-09-10 |
| Updated | 2026-09-10 |
| Related | `items.conversation_id`, `backend.ingest.x`, `backend.api.hub`, hub UI |

## Problem

Brand accounts post threads as a burst of self-replies. The hub listed each post as its own timeline row, so a 6-post thread crowded out everything else.

## Options

1. **Group by `conversation_id` in the API** — store the X field, collapse list rows, expand in the reader.
2. **Client-only grouping** — fragile pagination; existing rows have no conversation id.
3. **Drop thread replies at ingest** — loses the rest of the thread.

## Decision

**Implemented:** option 1.

- `items.conversation_id` from the X API (fallback: the post id).
- One-time burst clustering for rows that predate the column (same feed, ≤15s apart, not `RT @`).
- `GET /api/items` counts and pages **threads**, not raw posts. `GET /api/items/{id}` returns `thread` in chronological order.
- Timeline: one row + “N-post thread” badge. Reader: linked posts with per-post timestamps and links.

Replies to *other* accounts stay separate items (different `conversation_id`, and `exclude_replies` still applies at ingest).
