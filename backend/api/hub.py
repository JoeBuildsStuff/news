"""Read hub + subscription CRUD routes over feeds.db (FR-002)."""

from __future__ import annotations

import sqlite3
from typing import Any, Iterator, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.api.deps import auth_required, get_conn, require_admin
from backend.config import USER_AGENT
from backend.services import subscriptions as subs
from backend.services.link_previews import (
    allowed_twimg_video_url,
    get_or_fetch_preview,
    parse_media_json,
    preview_to_media,
    url_in_corpus,
)

router = APIRouter()

ITEM_SELECT = """
    i.id, i.feed_id, f.name AS feed_name, i.guid,
    i.title, i.link, i.summary, i.image_url, i.published_at, i.fetched_at,
    i.body_status, i.body_markdown, i.body_fetched_at, i.body_error,
    i.conversation_id, i.media_json
"""


def row_to_item(row: sqlite3.Row, *, include_body: bool = False) -> dict[str, Any]:
    keys = row.keys()
    media = parse_media_json(row["media_json"]) if "media_json" in keys else []
    item: dict[str, Any] = {
        "id": row["id"],
        "feed_id": row["feed_id"],
        "feed_name": row["feed_name"],
        "guid": row["guid"],
        "title": row["title"],
        "link": row["link"],
        "summary": row["summary"],
        "image_url": row["image_url"] if "image_url" in keys else None,
        "published_at": row["published_at"],
        "fetched_at": row["fetched_at"],
        "body_status": row["body_status"],
        "conversation_id": row["conversation_id"] if "conversation_id" in keys else None,
        "media": media,
    }
    if "thread_count" in keys:
        item["thread_count"] = int(row["thread_count"] or 1)
    if "thread_latest" in keys:
        item["thread_latest"] = row["thread_latest"]
    if include_body:
        item["body_markdown"] = row["body_markdown"]
        item["body_fetched_at"] = row["body_fetched_at"]
        item["body_error"] = row["body_error"]
    else:
        item["has_body"] = bool(row["body_markdown"]) and row["body_status"] == "ok"
    return item


def load_thread(conn: sqlite3.Connection, row: sqlite3.Row) -> list[dict[str, Any]]:
    conversation_id = row["conversation_id"] if "conversation_id" in row.keys() else None
    if not conversation_id:
        return [row_to_item(row, include_body=True)]
    siblings = conn.execute(
        f"""
        SELECT {ITEM_SELECT}
        FROM items i
        JOIN feeds f ON f.id = i.feed_id
        WHERE i.feed_id = ? AND i.conversation_id = ?
        ORDER BY COALESCE(i.published_at, i.fetched_at) ASC, CAST(i.guid AS INTEGER) ASC
        """,
        (row["feed_id"], conversation_id),
    ).fetchall()
    if not siblings:
        return [row_to_item(row, include_body=True)]
    return [row_to_item(sibling, include_body=True) for sibling in siblings]


class SubscriptionCreate(BaseModel):
    kind: Literal["rss", "x"]
    name: str = Field(min_length=1, max_length=200)
    url: str | None = None
    username: str | None = None
    exclude_retweets: bool = False
    exclude_replies: bool = True
    fetch_now: bool = True


class SubscriptionPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    url: str | None = None
    enabled: bool | None = None
    exclude_retweets: bool | None = None
    exclude_replies: bool | None = None


@router.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/feeds")
def list_feeds() -> dict[str, Any]:
    """Enabled sources for timeline filter chips."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                f.id,
                f.name,
                f.url,
                f.last_fetched_at,
                f.last_status,
                COUNT(i.id) AS item_count
            FROM feeds f
            LEFT JOIN items i ON i.feed_id = f.id
            WHERE f.enabled = 1
            GROUP BY f.id
            ORDER BY f.name COLLATE NOCASE
            """
        ).fetchall()
    return {
        "feeds": [
            {
                "id": row["id"],
                "name": row["name"],
                "url": row["url"],
                "last_fetched_at": row["last_fetched_at"],
                "last_status": row["last_status"],
                "item_count": row["item_count"],
            }
            for row in rows
        ]
    }


@router.get("/api/subscriptions")
def list_subscriptions() -> dict[str, Any]:
    with get_conn() as conn:
        rows = subs.list_subscription_rows(conn)
    return {
        "auth_required": auth_required(),
        "subscriptions": [subs.row_to_subscription(row) for row in rows],
    }


@router.post("/api/subscriptions")
def create_subscription(
    body: SubscriptionCreate,
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    try:
        with get_conn() as conn:
            result, fetch_error = subs.create_subscription(
                conn,
                kind=body.kind,
                name=body.name,
                url=body.url,
                username=body.username,
                exclude_retweets=body.exclude_retweets,
                exclude_replies=body.exclude_replies,
                do_fetch_now=body.fetch_now,
            )
    except subs.SubscriptionError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc

    out: dict[str, Any] = {"subscription": result}
    if fetch_error:
        out["fetch_error"] = fetch_error
    return out


@router.patch("/api/subscriptions/{feed_id}")
def patch_subscription(
    feed_id: str,
    body: SubscriptionPatch,
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    try:
        with get_conn() as conn:
            updated = subs.update_subscription(
                conn,
                feed_id,
                name=body.name,
                url=body.url,
                enabled=body.enabled,
                exclude_retweets=body.exclude_retweets,
                exclude_replies=body.exclude_replies,
            )
    except subs.SubscriptionError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    return {"subscription": updated}


@router.delete("/api/subscriptions/{feed_id}")
def delete_subscription(
    feed_id: str,
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    """Soft-disable: stop polling, keep history."""
    try:
        with get_conn() as conn:
            updated = subs.unsubscribe(conn, feed_id)
    except subs.SubscriptionError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    return {"subscription": updated}


@router.get("/api/items")
def list_items(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    feed_id: str | None = Query(None, description="Filter by feeds.id"),
    include_body: bool = Query(False),
) -> dict[str, Any]:
    clauses: list[str] = []
    params: list[Any] = []
    if feed_id:
        clauses.append("i.feed_id = ?")
        params.append(feed_id)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    keyed_sql = f"""
        WITH keyed AS (
            SELECT
                {ITEM_SELECT},
                CASE
                    WHEN i.conversation_id IS NOT NULL AND i.conversation_id != ''
                    THEN i.feed_id || ':' || i.conversation_id
                    ELSE 'i:' || CAST(i.id AS TEXT)
                END AS thread_key
            FROM items i
            JOIN feeds f ON f.id = i.feed_id
            {where}
        )
    """

    with get_conn() as conn:
        total = conn.execute(
            f"{keyed_sql} SELECT COUNT(DISTINCT thread_key) FROM keyed",
            params,
        ).fetchone()[0]
        rows = conn.execute(
            f"""
            {keyed_sql},
            ranked AS (
                SELECT
                    keyed.*,
                    COUNT(*) OVER (PARTITION BY thread_key) AS thread_count,
                    MAX(COALESCE(published_at, fetched_at)) OVER (
                        PARTITION BY thread_key
                    ) AS thread_latest,
                    ROW_NUMBER() OVER (
                        PARTITION BY thread_key
                        ORDER BY
                            CASE WHEN guid = conversation_id THEN 0 ELSE 1 END,
                            COALESCE(published_at, fetched_at) ASC,
                            CAST(guid AS INTEGER) ASC
                    ) AS rn
                FROM keyed
            )
            SELECT * FROM ranked
            WHERE rn = 1
            ORDER BY thread_latest DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [row_to_item(row, include_body=include_body) for row in rows],
    }


@router.get("/api/items/{item_id}")
def get_item(item_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute(
            f"""
            SELECT {ITEM_SELECT}
            FROM items i
            JOIN feeds f ON f.id = i.feed_id
            WHERE i.id = ?
            """,
            (item_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Item not found")
        thread = load_thread(conn, row)
    item = row_to_item(row, include_body=True)
    item["thread"] = thread
    item["thread_count"] = len(thread)
    return item


class UnfurlRequest(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=20)


@router.get("/api/media/video")
def proxy_twimg_video(
    request: Request,
    url: str = Query(min_length=1, max_length=2000),
) -> StreamingResponse:
    """Stream a stored X mp4 without sending this site as Referer.

    video.twimg.com 403s browser <video> loads. The URL must already be on an item.
    """
    target = allowed_twimg_video_url(url)
    if target is None or target != url.strip():
        raise HTTPException(status_code=400, detail="unsupported media url")
    with get_conn() as conn:
        if not url_in_corpus(conn, target):
            raise HTTPException(status_code=404, detail="media url is not on a stored item")

    headers = {"User-Agent": USER_AGENT, "Accept": "video/mp4,*/*"}
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header
    client = httpx.Client(timeout=httpx.Timeout(20.0, read=60.0), follow_redirects=False)
    try:
        upstream = client.send(
            client.build_request("GET", target, headers=headers),
            stream=True,
        )
    except httpx.HTTPError as exc:
        client.close()
        raise HTTPException(status_code=502, detail="media fetch failed") from exc
    if upstream.status_code not in {200, 206}:
        upstream.close()
        client.close()
        raise HTTPException(status_code=502, detail="media unavailable")

    def chunks() -> Iterator[bytes]:
        try:
            for chunk in upstream.iter_bytes():
                yield chunk
        finally:
            upstream.close()
            client.close()

    passthrough = {
        key: upstream.headers[key]
        for key in (
            "content-type",
            "content-length",
            "content-range",
            "accept-ranges",
            "cache-control",
        )
        if key in upstream.headers
    }
    return StreamingResponse(chunks(), status_code=upstream.status_code, headers=passthrough)


@router.post("/api/unfurl")
def unfurl_urls(body: UnfurlRequest) -> dict[str, Any]:
    """Resolve stored item URLs into image / video / website previews."""
    previews: list[dict[str, Any]] = []
    with get_conn() as conn:
        for raw in body.urls:
            url = str(raw).strip()
            if not url:
                continue
            if url.startswith("http://") or url.startswith("https://"):
                parsed_ok = True
            else:
                parsed_ok = False
            if not parsed_ok or not url_in_corpus(conn, url):
                previews.append(
                    {
                        "url": url,
                        "kind": "skip",
                        "status": "error",
                        "error": "url is not from a stored item",
                    }
                )
                continue
            preview = get_or_fetch_preview(conn, url)
            media = preview_to_media(preview, tco=url)
            previews.append(
                {
                    "url": url,
                    "resolved_url": preview.get("resolved_url"),
                    "kind": preview.get("kind"),
                    "status": preview.get("status"),
                    "title": preview.get("title"),
                    "description": preview.get("description"),
                    "image_url": preview.get("image_url"),
                    "video_url": preview.get("video_url"),
                    "site_name": preview.get("site_name"),
                    "embed": preview.get("embed"),
                    "media": media,
                    "error": preview.get("error"),
                }
            )
    return {"previews": previews}
