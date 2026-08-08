"""Shared SQLite schema and helpers for feeds / items / subscriptions."""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser
import httpx
import yaml

from backend.config import (
    DEFAULT_CONFIG,
    DEFAULT_X_CONFIG,
    SEED_META_KEY,
    USER_AGENT,
)


def load_config(path: Path) -> list[dict]:
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    feeds = data.get("feeds") or []
    if not feeds:
        raise SystemExit(f"No feeds found in {path}")
    return feeds


def load_yaml_feeds(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return list(data.get("feeds") or [])


def load_yaml_x_accounts(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return list(data.get("accounts") or [])


def connect(db_path: Path, *, seed: bool = True) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # Local default WAL; production named volumes use DELETE (DB_JOURNAL_MODE).
    journal = (os.environ.get("DB_JOURNAL_MODE") or "WAL").upper()
    if journal not in {"WAL", "DELETE", "TRUNCATE", "PERSIST", "MEMORY", "OFF"}:
        journal = "WAL"
    conn.execute(f"PRAGMA journal_mode={journal}")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS feeds (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            last_fetched_at TEXT,
            last_status TEXT,
            last_error TEXT
        );

        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feed_id TEXT NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
            guid TEXT NOT NULL,
            title TEXT,
            link TEXT,
            summary TEXT,
            published_at TEXT,
            fetched_at TEXT NOT NULL,
            body_markdown TEXT,
            body_fetched_at TEXT,
            body_status TEXT,
            body_error TEXT,
            UNIQUE(feed_id, guid)
        );

        CREATE TABLE IF NOT EXISTS app_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_items_published
            ON items(published_at DESC);
        """
    )
    ensure_body_columns(conn)
    ensure_subscription_columns(conn)
    from backend.services.chat_db import ensure_chat_schema

    ensure_chat_schema(conn)
    if seed:
        seed_subscriptions(conn)
    return conn


def ensure_body_columns(conn: sqlite3.Connection) -> None:
    """Migrate existing DBs created before body_* columns existed."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
    migrations = [
        ("body_markdown", "TEXT"),
        ("body_fetched_at", "TEXT"),
        ("body_status", "TEXT"),
        ("body_error", "TEXT"),
    ]
    for name, col_type in migrations:
        if name not in existing:
            conn.execute(f"ALTER TABLE items ADD COLUMN {name} {col_type}")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_items_body_status
            ON items(body_status)
        """
    )
    conn.commit()


def ensure_subscription_columns(conn: sqlite3.Connection) -> None:
    """Add subscription fields used by the UI + DB-backed pollers."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(feeds)")}
    migrations = [
        ("kind", "TEXT NOT NULL DEFAULT 'rss'"),
        ("enabled", "INTEGER NOT NULL DEFAULT 1"),
        ("exclude_retweets", "INTEGER NOT NULL DEFAULT 0"),
        ("exclude_replies", "INTEGER NOT NULL DEFAULT 1"),
        ("username", "TEXT"),
    ]
    for name, col_def in migrations:
        if name not in existing:
            conn.execute(f"ALTER TABLE feeds ADD COLUMN {name} {col_def}")

    # Existing X rows predate kind/username — infer from id / url.
    conn.execute(
        """
        UPDATE feeds
        SET kind = 'x'
        WHERE (kind IS NULL OR kind = 'rss')
          AND (id LIKE 'x-%' OR url LIKE 'https://x.com/%' OR url LIKE 'https://twitter.com/%')
        """
    )
    rows = conn.execute(
        """
        SELECT id, url, username FROM feeds
        WHERE kind = 'x' AND (username IS NULL OR username = '')
        """
    ).fetchall()
    for row in rows:
        username = _username_from_x_url(row["url"])
        if username:
            conn.execute(
                "UPDATE feeds SET username = ? WHERE id = ?",
                (username, row["id"]),
            )
    conn.commit()


def _username_from_x_url(url: str | None) -> str | None:
    if not url:
        return None
    path = url.rstrip("/").split("/")
    if len(path) < 4:
        return None
    handle = path[3].lstrip("@")
    return handle or None


def _meta_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute(
        "SELECT value FROM app_meta WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else None


def _meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO app_meta (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def seed_subscriptions(
    conn: sqlite3.Connection,
    *,
    feeds_path: Path = DEFAULT_CONFIG,
    x_path: Path = DEFAULT_X_CONFIG,
) -> None:
    """One-time YAML → DB seed. Never overwrites UI-edited rows after seeded."""
    if _meta_get(conn, SEED_META_KEY) == "1":
        return

    for feed in load_yaml_feeds(feeds_path):
        conn.execute(
            """
            INSERT INTO feeds (id, name, url, kind, enabled, exclude_retweets, exclude_replies, username)
            VALUES (?, ?, ?, 'rss', 1, 0, 1, NULL)
            ON CONFLICT(id) DO NOTHING
            """,
            (feed["id"], feed["name"], feed["url"]),
        )

    for account in load_yaml_x_accounts(x_path):
        username = str(account["username"]).lstrip("@")
        conn.execute(
            """
            INSERT INTO feeds (id, name, url, kind, enabled, exclude_retweets, exclude_replies, username)
            VALUES (?, ?, ?, 'x', 1, 0, 1, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                account["id"],
                account["name"],
                f"https://x.com/{username}",
                username,
            ),
        )

    _meta_set(conn, SEED_META_KEY, "1")
    conn.commit()


def list_enabled_subscriptions(
    conn: sqlite3.Connection, kind: str
) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, name, url, username, exclude_retweets, exclude_replies
        FROM feeds
        WHERE enabled = 1 AND kind = ?
        ORDER BY name COLLATE NOCASE
        """,
        (kind,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "url": row["url"],
            "username": row["username"],
            "exclude_retweets": bool(row["exclude_retweets"]),
            "exclude_replies": bool(row["exclude_replies"]),
        }
        for row in rows
    ]


def parse_date(value: object) -> str | None:
    if not value:
        return None
    if isinstance(value, time.struct_time):
        return datetime(*value[:6], tzinfo=timezone.utc).isoformat()
    if isinstance(value, str):
        try:
            return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError, IndexError):
            return value
    return None


def item_guid(entry: feedparser.FeedParserDict) -> str:
    for key in ("id", "guid", "link"):
        val = entry.get(key)
        if val:
            return str(val)
    title = entry.get("title") or ""
    published = entry.get("published") or entry.get("updated") or ""
    return f"{title}|{published}"


def fetch_feed(url: str, timeout: float = 30.0) -> bytes:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.content


def upsert_feed(conn: sqlite3.Connection, feed: dict) -> None:
    """Insert or refresh name/url. Does not overwrite enabled / exclude_* flags."""
    kind = feed.get("kind") or "rss"
    username = feed.get("username")
    if username:
        username = str(username).lstrip("@")
    exclude_retweets = 1 if feed.get("exclude_retweets") else 0
    # Default matches historical CLI: replies excluded unless opted in.
    exclude_replies = 0 if feed.get("exclude_replies") is False else 1
    enabled = 0 if feed.get("enabled") is False else 1
    conn.execute(
        """
        INSERT INTO feeds (
            id, name, url, kind, enabled, exclude_retweets, exclude_replies, username
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            url = excluded.url,
            kind = excluded.kind,
            username = COALESCE(excluded.username, feeds.username)
        """,
        (
            feed["id"],
            feed["name"],
            feed["url"],
            kind,
            enabled,
            exclude_retweets,
            exclude_replies,
            username,
        ),
    )


def store_items(conn: sqlite3.Connection, feed_id: str, entries: list) -> tuple[int, int]:
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    updated = 0
    for entry in entries:
        guid = item_guid(entry)
        published = parse_date(entry.get("published_parsed") or entry.get("updated_parsed"))
        if not published:
            published = parse_date(entry.get("published") or entry.get("updated"))

        existing = conn.execute(
            "SELECT 1 FROM items WHERE feed_id = ? AND guid = ?",
            (feed_id, guid),
        ).fetchone()

        conn.execute(
            """
            INSERT INTO items (feed_id, guid, title, link, summary, published_at, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(feed_id, guid) DO UPDATE SET
                title = excluded.title,
                link = excluded.link,
                summary = excluded.summary,
                published_at = COALESCE(excluded.published_at, items.published_at)
            """,
            (
                feed_id,
                guid,
                entry.get("title"),
                entry.get("link"),
                entry.get("summary") or entry.get("description"),
                published,
                now,
            ),
        )
        if existing:
            updated += 1
        else:
            inserted += 1
    return inserted, updated


def mark_feed(
    conn: sqlite3.Connection,
    feed_id: str,
    *,
    status: str,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE feeds
        SET last_fetched_at = ?, last_status = ?, last_error = ?
        WHERE id = ?
        """,
        (datetime.now(timezone.utc).isoformat(), status, error, feed_id),
    )


def fetch_one(conn: sqlite3.Connection, feed: dict) -> None:
    payload = {**feed, "kind": feed.get("kind") or "rss"}
    upsert_feed(conn, payload)
    print(f"→ {feed['id']}: {feed['url']}")
    try:
        raw = fetch_feed(feed["url"])
        parsed = feedparser.parse(raw)
        if getattr(parsed, "bozo", False) and not parsed.entries:
            raise RuntimeError(f"Failed to parse feed: {parsed.get('bozo_exception')}")
        inserted, updated = store_items(conn, feed["id"], parsed.entries)
        mark_feed(conn, feed["id"], status="ok")
        conn.commit()
        print(f"  ok — {len(parsed.entries)} entries ({inserted} new, {updated} updated)")
    except Exception as exc:  # noqa: BLE001 - surface fetch errors per feed
        mark_feed(conn, feed["id"], status="error", error=str(exc))
        conn.commit()
        print(f"  error — {exc}", file=sys.stderr)


def list_recent(conn: sqlite3.Connection, limit: int = 20) -> None:
    rows = conn.execute(
        """
        SELECT f.name AS feed, i.title, i.link, i.published_at
        FROM items i
        JOIN feeds f ON f.id = i.feed_id
        ORDER BY COALESCE(i.published_at, i.fetched_at) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    if not rows:
        print("No items stored yet.")
        return
    for row in rows:
        published = row["published_at"] or "?"
        print(f"[{published}] {row['feed']}: {row['title']}")
        if row["link"]:
            print(f"  {row['link']}")
