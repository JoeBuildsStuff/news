"""Shared subscription list/create/update helpers for hub API + chat tools."""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Literal

from backend.db import fetch_one, upsert_feed


class SubscriptionError(Exception):
    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


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


def list_subscription_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
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


def fetch_now(conn: sqlite3.Connection, sub: dict[str, Any]) -> str | None:
    """Best-effort one-shot poll so new subscriptions show data immediately."""
    try:
        if sub["kind"] == "rss":
            fetch_one(
                conn,
                {"id": sub["id"], "name": sub["name"], "url": sub["url"], "kind": "rss"},
                fill_images=8,
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


def create_subscription(
    conn: sqlite3.Connection,
    *,
    kind: Literal["rss", "x"],
    name: str,
    url: str | None = None,
    username: str | None = None,
    exclude_retweets: bool = False,
    exclude_replies: bool = True,
    do_fetch_now: bool = True,
) -> tuple[dict[str, Any], str | None]:
    name = name.strip()
    if not name:
        raise SubscriptionError("name is required")

    if kind == "rss":
        if not url or not url.strip():
            raise SubscriptionError("url is required for RSS")
        url = url.strip()
        username = None
        feed_id = allocate_feed_id(conn, slugify(name))
    else:
        if not username or not username.strip():
            raise SubscriptionError("username is required for X")
        username = username.strip().lstrip("@")
        url = f"https://x.com/{username}"
        feed_id = f"x-{username.lower()}"
        existing = conn.execute(
            "SELECT id FROM feeds WHERE id = ? OR (kind = 'x' AND username = ? COLLATE NOCASE)",
            (feed_id, username),
        ).fetchone()
        if existing:
            raise SubscriptionError(
                f"X account already subscribed as {existing['id']}",
                status=409,
            )

    upsert_feed(
        conn,
        {
            "id": feed_id,
            "name": name,
            "url": url,
            "kind": kind,
            "username": username,
            "enabled": True,
            "exclude_retweets": exclude_retweets,
            "exclude_replies": exclude_replies,
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
            1 if exclude_retweets else 0,
            1 if exclude_replies else 0,
            kind,
            username,
            feed_id,
        ),
    )
    conn.commit()

    sub = {
        "id": feed_id,
        "name": name,
        "url": url,
        "kind": kind,
        "username": username,
        "exclude_retweets": exclude_retweets,
        "exclude_replies": exclude_replies,
    }
    fetch_error: str | None = None
    if do_fetch_now:
        fetch_error = fetch_now(conn, sub)

    row = get_subscription_row(conn, feed_id)
    assert row is not None
    return row_to_subscription(row), fetch_error


def update_subscription(
    conn: sqlite3.Connection,
    feed_id: str,
    *,
    name: str | None = None,
    url: str | None = None,
    enabled: bool | None = None,
    exclude_retweets: bool | None = None,
    exclude_replies: bool | None = None,
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, kind FROM feeds WHERE id = ?", (feed_id,)
    ).fetchone()
    if not row:
        raise SubscriptionError("Subscription not found", status=404)

    updates: list[str] = []
    params: list[Any] = []
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise SubscriptionError("name cannot be empty")
        updates.append("name = ?")
        params.append(cleaned)
    if url is not None:
        if row["kind"] != "rss":
            raise SubscriptionError("url only applies to RSS")
        updates.append("url = ?")
        params.append(url.strip())
    if enabled is not None:
        updates.append("enabled = ?")
        params.append(1 if enabled else 0)
    if exclude_retweets is not None:
        if row["kind"] != "x":
            raise SubscriptionError("exclude_retweets only applies to X")
        updates.append("exclude_retweets = ?")
        params.append(1 if exclude_retweets else 0)
    if exclude_replies is not None:
        if row["kind"] != "x":
            raise SubscriptionError("exclude_replies only applies to X")
        updates.append("exclude_replies = ?")
        params.append(1 if exclude_replies else 0)

    if not updates:
        raise SubscriptionError("No fields to update")

    params.append(feed_id)
    conn.execute(
        f"UPDATE feeds SET {', '.join(updates)} WHERE id = ?",
        params,
    )
    conn.commit()
    updated = get_subscription_row(conn, feed_id)
    assert updated is not None
    return row_to_subscription(updated)


def unsubscribe(conn: sqlite3.Connection, feed_id: str) -> dict[str, Any]:
    """Soft-disable: stop polling, keep history."""
    row = conn.execute("SELECT id FROM feeds WHERE id = ?", (feed_id,)).fetchone()
    if not row:
        raise SubscriptionError("Subscription not found", status=404)
    conn.execute("UPDATE feeds SET enabled = 0 WHERE id = ?", (feed_id,))
    conn.commit()
    updated = get_subscription_row(conn, feed_id)
    assert updated is not None
    return row_to_subscription(updated)
