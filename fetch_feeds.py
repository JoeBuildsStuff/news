#!/usr/bin/env python3
"""Fetch configured RSS feeds and upsert items into a local SQLite database."""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser
import httpx
import yaml

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "data" / "feeds.db"
DEFAULT_CONFIG = ROOT / "feeds.yaml"
USER_AGENT = "news-local-fetcher/1.0 (+local)"


def load_config(path: Path) -> list[dict]:
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    feeds = data.get("feeds") or []
    if not feeds:
        raise SystemExit(f"No feeds found in {path}")
    return feeds


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
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

        CREATE INDEX IF NOT EXISTS idx_items_published
            ON items(published_at DESC);
        """
    )
    ensure_body_columns(conn)
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
    conn.execute(
        """
        INSERT INTO feeds (id, name, url)
        VALUES (?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            url = excluded.url
        """,
        (feed["id"], feed["name"], feed["url"]),
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
    upsert_feed(conn, feed)
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and store RSS feeds locally")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--list", action="store_true", help="List recent stored items")
    parser.add_argument("--limit", type=int, default=20, help="Items to show with --list")
    args = parser.parse_args()

    conn = connect(args.db)
    try:
        if args.list:
            list_recent(conn, args.limit)
            return

        feeds = load_config(args.config)
        for feed in feeds:
            fetch_one(conn, feed)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
