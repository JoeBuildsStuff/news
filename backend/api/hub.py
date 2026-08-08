"""Read hub + subscription CRUD routes over feeds.db (FR-002)."""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.api.deps import auth_required, get_conn, require_admin
from backend.db import fetch_one, upsert_feed

router = APIRouter()


def row_to_item(row: sqlite3.Row, *, include_body: bool = False) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": row["id"],
        "feed_id": row["feed_id"],
        "feed_name": row["feed_name"],
        "guid": row["guid"],
        "title": row["title"],
        "link": row["link"],
        "summary": row["summary"],
        "published_at": row["published_at"],
        "fetched_at": row["fetched_at"],
        "body_status": row["body_status"],
    }
    if include_body:
        item["body_markdown"] = row["body_markdown"]
        item["body_fetched_at"] = row["body_fetched_at"]
        item["body_error"] = row["body_error"]
    else:
        item["has_body"] = bool(row["body_markdown"]) and row["body_status"] == "ok"
    return item


def row_to_subscription(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "url": row["url"],
        "kind": row["kind"],
        "enabled": bool(row["enabled"]),
        "exclude_retweets": bool(row["exclude_retweets"]),
        "exclude_replies": bool(row["exclude_replies"]),
        "username": row["username"],
        "last_fetched_at": row["last_fetched_at"],
        "last_status": row["last_status"],
        "last_error": row["last_error"],
        "item_count": row["item_count"] if "item_count" in row.keys() else 0,
    }


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "feed"


def allocate_feed_id(conn: sqlite3.Connection, base: str) -> str:
    candidate = base
    n = 2
    while conn.execute("SELECT 1 FROM feeds WHERE id = ?", (candidate,)).fetchone():
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def get_subscription_row(conn: sqlite3.Connection, feed_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT
            f.id, f.name, f.url, f.kind, f.enabled,
            f.exclude_retweets, f.exclude_replies, f.username,
            f.last_fetched_at, f.last_status, f.last_error,
            COUNT(i.id) AS item_count
        FROM feeds f
        LEFT JOIN items i ON i.feed_id = f.id
        WHERE f.id = ?
        GROUP BY f.id
        """,
        (feed_id,),
    ).fetchone()


def fetch_now(conn: sqlite3.Connection, sub: dict[str, Any]) -> str | None:
    """Best-effort one-shot poll so new subscriptions show data immediately."""
    try:
        if sub["kind"] == "rss":
            fetch_one(
                conn,
                {"id": sub["id"], "name": sub["name"], "url": sub["url"], "kind": "rss"},
            )
            return None
        from backend.ingest.x import ensure_x_schema, fetch_account, load_env, make_client

        load_env()
        ensure_x_schema(conn)
        client = make_client()
        fetch_account(
            conn,
            client,
            {
                "id": sub["id"],
                "name": sub["name"],
                "username": sub["username"],
            },
            max_results=10,
            exclude_replies=bool(sub.get("exclude_replies", True)),
            exclude_retweets=bool(sub.get("exclude_retweets", False)),
        )
        return None
    except Exception as exc:  # noqa: BLE001 - create still succeeded
        return str(exc)


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
        rows = conn.execute(
            """
            SELECT
                f.id, f.name, f.url, f.kind, f.enabled,
                f.exclude_retweets, f.exclude_replies, f.username,
                f.last_fetched_at, f.last_status, f.last_error,
                COUNT(i.id) AS item_count
            FROM feeds f
            LEFT JOIN items i ON i.feed_id = f.id
            GROUP BY f.id
            ORDER BY f.kind, f.name COLLATE NOCASE
            """
        ).fetchall()
    return {
        "auth_required": auth_required(),
        "subscriptions": [row_to_subscription(row) for row in rows],
    }


@router.post("/api/subscriptions")
def create_subscription(
    body: SubscriptionCreate,
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    if body.kind == "rss":
        if not body.url or not body.url.strip():
            raise HTTPException(status_code=400, detail="url is required for RSS")
        url = body.url.strip()
        username = None
        feed_id = ""  # assigned inside the DB transaction
    else:
        if not body.username or not body.username.strip():
            raise HTTPException(status_code=400, detail="username is required for X")
        username = body.username.strip().lstrip("@")
        url = f"https://x.com/{username}"
        feed_id = f"x-{username.lower()}"

    fetch_error: str | None = None
    with get_conn() as conn:
        if body.kind == "rss":
            feed_id = allocate_feed_id(conn, slugify(name))
        else:
            existing = conn.execute(
                "SELECT id FROM feeds WHERE id = ? OR (kind = 'x' AND username = ? COLLATE NOCASE)",
                (feed_id, username),
            ).fetchone()
            if existing:
                raise HTTPException(
                    status_code=409,
                    detail=f"X account already subscribed as {existing['id']}",
                )

        upsert_feed(
            conn,
            {
                "id": feed_id,
                "name": name,
                "url": url,
                "kind": body.kind,
                "username": username,
                "enabled": True,
                "exclude_retweets": body.exclude_retweets,
                "exclude_replies": body.exclude_replies,
            },
        )
        # upsert_feed does not refresh exclude_* on conflict; force flags for create.
        conn.execute(
            """
            UPDATE feeds
            SET enabled = 1,
                exclude_retweets = ?,
                exclude_replies = ?,
                kind = ?,
                username = ?
            WHERE id = ?
            """,
            (
                1 if body.exclude_retweets else 0,
                1 if body.exclude_replies else 0,
                body.kind,
                username,
                feed_id,
            ),
        )
        conn.commit()

        sub = {
            "id": feed_id,
            "name": name,
            "url": url,
            "kind": body.kind,
            "username": username,
            "exclude_retweets": body.exclude_retweets,
            "exclude_replies": body.exclude_replies,
        }
        if body.fetch_now:
            fetch_error = fetch_now(conn, sub)

        row = get_subscription_row(conn, feed_id)
        assert row is not None
        result = row_to_subscription(row)

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
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, kind FROM feeds WHERE id = ?", (feed_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Subscription not found")

        updates: list[str] = []
        params: list[Any] = []
        if body.name is not None:
            updates.append("name = ?")
            params.append(body.name.strip())
        if body.url is not None:
            if row["kind"] != "rss":
                raise HTTPException(status_code=400, detail="url only applies to RSS")
            updates.append("url = ?")
            params.append(body.url.strip())
        if body.enabled is not None:
            updates.append("enabled = ?")
            params.append(1 if body.enabled else 0)
        if body.exclude_retweets is not None:
            if row["kind"] != "x":
                raise HTTPException(
                    status_code=400, detail="exclude_retweets only applies to X"
                )
            updates.append("exclude_retweets = ?")
            params.append(1 if body.exclude_retweets else 0)
        if body.exclude_replies is not None:
            if row["kind"] != "x":
                raise HTTPException(
                    status_code=400, detail="exclude_replies only applies to X"
                )
            updates.append("exclude_replies = ?")
            params.append(1 if body.exclude_replies else 0)

        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        params.append(feed_id)
        conn.execute(
            f"UPDATE feeds SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
        updated = get_subscription_row(conn, feed_id)
        assert updated is not None
        return {"subscription": row_to_subscription(updated)}


@router.delete("/api/subscriptions/{feed_id}")
def delete_subscription(
    feed_id: str,
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    """Soft-disable: stop polling, keep history."""
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM feeds WHERE id = ?", (feed_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Subscription not found")
        conn.execute("UPDATE feeds SET enabled = 0 WHERE id = ?", (feed_id,))
        conn.commit()
        updated = get_subscription_row(conn, feed_id)
        assert updated is not None
        return {"subscription": row_to_subscription(updated)}


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

    with get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM items i {where}",
            params,
        ).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT
                i.id, i.feed_id, f.name AS feed_name, i.guid,
                i.title, i.link, i.summary, i.published_at, i.fetched_at,
                i.body_status, i.body_markdown, i.body_fetched_at, i.body_error
            FROM items i
            JOIN feeds f ON f.id = i.feed_id
            {where}
            ORDER BY COALESCE(i.published_at, i.fetched_at) DESC
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
            """
            SELECT
                i.id, i.feed_id, f.name AS feed_name, i.guid,
                i.title, i.link, i.summary, i.published_at, i.fetched_at,
                i.body_status, i.body_markdown, i.body_fetched_at, i.body_error
            FROM items i
            JOIN feeds f ON f.id = i.feed_id
            WHERE i.id = ?
            """,
            (item_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Item not found")
    return row_to_item(row, include_body=True)
