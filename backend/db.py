"""Shared SQLite schema and helpers for feeds / items / subscriptions."""

from __future__ import annotations

import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

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
            image_url TEXT,
            conversation_id TEXT,
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
    ensure_image_column(conn)
    ensure_subscription_columns(conn)
    ensure_conversation_column(conn)
    ensure_media_column(conn)
    ensure_link_preview_schema(conn)
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


def ensure_image_column(conn: sqlite3.Connection) -> None:
    """Migrate existing DBs created before items.image_url existed."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
    if "image_url" not in existing:
        conn.execute("ALTER TABLE items ADD COLUMN image_url TEXT")
        conn.commit()


def ensure_media_column(conn: sqlite3.Connection) -> None:
    """JSON list of photos, videos, and website cards (FR-006)."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
    if "media_json" not in existing:
        conn.execute("ALTER TABLE items ADD COLUMN media_json TEXT")
        conn.commit()


def ensure_link_preview_schema(conn: sqlite3.Connection) -> None:
    """Cache for on-demand URL unfurls (website / image / video)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS link_previews (
            url TEXT PRIMARY KEY,
            resolved_url TEXT,
            kind TEXT NOT NULL,
            title TEXT,
            description TEXT,
            image_url TEXT,
            video_url TEXT,
            site_name TEXT,
            fetched_at TEXT NOT NULL,
            status TEXT,
            error TEXT
        )
        """
    )
    conn.commit()


def ensure_conversation_column(conn: sqlite3.Connection) -> None:
    """X conversation_id so same-author thread replies can group in the hub."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
    if "conversation_id" not in existing:
        conn.execute("ALTER TABLE items ADD COLUMN conversation_id TEXT")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_items_conversation
            ON items(feed_id, conversation_id)
        """
    )
    infer_x_conversation_ids(conn)
    conn.commit()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _looks_like_retweet(title: str | None) -> bool:
    return (title or "").lstrip().startswith("RT @")


def infer_x_conversation_ids(conn: sqlite3.Connection) -> None:
    """Fill missing X conversation_id values from same-author posting bursts.

    Existing rows were stored without conversation_id. Brand threads are
    posted a few seconds apart; cluster those (skip retweets) so the hub
    can group them before the next fetch_x run overwrites with API ids.
    """
    infer_meta_key = "x_conversation_infer"
    infer_version = "2"
    current = _meta_get(conn, infer_meta_key)
    if current != infer_version and current in {None, "1"}:
        conn.execute(
            """
            UPDATE items
            SET conversation_id = NULL
            WHERE feed_id IN (SELECT id FROM feeds WHERE kind = 'x')
            """
        )

    pending = conn.execute(
        """
        SELECT 1
        FROM items i
        JOIN feeds f ON f.id = i.feed_id
        WHERE f.kind = 'x'
          AND (i.conversation_id IS NULL OR i.conversation_id = '')
        LIMIT 1
        """
    ).fetchone()
    if not pending and current == infer_version:
        return

    burst_seconds = 15
    feeds = conn.execute("SELECT id FROM feeds WHERE kind = 'x'").fetchall()
    for feed in feeds:
        rows = conn.execute(
            """
            SELECT id, guid, title, published_at
            FROM items
            WHERE feed_id = ?
              AND (conversation_id IS NULL OR conversation_id = '')
            ORDER BY COALESCE(published_at, fetched_at) ASC,
                     CAST(guid AS INTEGER) ASC
            """,
            (feed["id"],),
        ).fetchall()
        last_ts: datetime | None = None
        last_was_rt = True
        root_guid: str | None = None
        for row in rows:
            is_rt = _looks_like_retweet(row["title"])
            ts = _parse_iso(row["published_at"])
            join = (
                not is_rt
                and not last_was_rt
                and root_guid is not None
                and ts is not None
                and last_ts is not None
                and (ts - last_ts).total_seconds() <= burst_seconds
            )
            conversation_id = root_guid if join else row["guid"]
            if not join:
                root_guid = None if is_rt else row["guid"]
            conn.execute(
                "UPDATE items SET conversation_id = ? WHERE id = ?",
                (conversation_id, row["id"]),
            )
            last_ts = ts
            last_was_rt = is_rt
    _meta_set(conn, infer_meta_key, infer_version)


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


_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".avif")
_META_TAG_RE = re.compile(r"<meta\b([^>]+)>", re.I)
_ATTR_RE = re.compile(r'([^\s=]+)\s*=\s*["\']([^"\']+)["\']', re.I)
_IMG_TAG_RE = re.compile(r"<img\b([^>]+)>", re.I)
_SHARE_IMAGE_KEYS = ("og:image", "og:image:url", "twitter:image", "twitter:image:src")


def normalize_http_url(value: object, *, base: str | None = None) -> str | None:
    """Keep http(s) URLs only; resolve relative paths against base."""
    if not value:
        return None
    url = unescape(str(value)).strip()
    if not url or url.startswith("data:"):
        return None
    if base:
        url = urljoin(base, url)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return url


def normalize_image_url(value: object, *, base: str | None = None) -> str | None:
    """Keep http(s) image URLs only; resolve relative paths against base."""
    return normalize_http_url(value, base=base)


def _looks_like_image(url: str, *, type_: str | None = None, medium: str | None = None) -> bool:
    if medium and medium.lower() == "image":
        return True
    if type_:
        lowered = type_.lower()
        if lowered.startswith("image/") or lowered == "image":
            return True
    path = urlparse(url).path.lower()
    return path.endswith(_IMAGE_EXT)


def _as_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_share_image(html: str, *, base: str | None = None) -> str | None:
    """og:image / twitter:image from article HTML."""
    found: dict[str, str] = {}
    for attrs_raw in _META_TAG_RE.findall(html):
        attrs = {key.lower(): val for key, val in _ATTR_RE.findall(attrs_raw)}
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        content = attrs.get("content")
        if key in _SHARE_IMAGE_KEYS and content:
            found[key] = content
    for key in _SHARE_IMAGE_KEYS:
        if key in found:
            url = normalize_image_url(found[key], base=base)
            if url:
                return url
    return None


def _html_img_src(html: str, *, base: str | None = None) -> str | None:
    for attrs_raw in _IMG_TAG_RE.findall(html):
        attrs = {key.lower(): val for key, val in _ATTR_RE.findall(attrs_raw)}
        src = attrs.get("src")
        if not src:
            continue
        width = _as_int(attrs.get("width"))
        height = _as_int(attrs.get("height"))
        if width is not None and width <= 2:
            continue
        if height is not None and height <= 2:
            continue
        url = normalize_image_url(src, base=base)
        if url and _looks_like_image(url, type_=attrs.get("type")):
            return url
        if url and not _looks_like_image(url):
            # CDN paths often omit an extension; still accept http(s) img src.
            return url
    return None


def _dict_image_url(item: object, *, base: str | None = None) -> str | None:
    if isinstance(item, str):
        return normalize_image_url(item, base=base)
    if not isinstance(item, dict):
        return None
    type_ = str(item.get("type") or "") or None
    medium = str(item.get("medium") or "") or None
    raw = item.get("url") or item.get("href") or item.get("src")
    url = normalize_image_url(raw, base=base)
    if not url:
        return None
    if medium and medium.lower() == "video":
        return None
    if type_ or medium:
        return url if _looks_like_image(url, type_=type_, medium=medium) else None
    return url


def entry_image_url(entry: feedparser.FeedParserDict) -> str | None:
    """Best image from RSS media/enclosures/HTML; no extra HTTP."""
    base = str(entry.get("link") or "") or None
    media_items = [item for item in (entry.get("media_content") or []) if isinstance(item, dict)]
    media_items.sort(key=lambda item: _as_int(item.get("width")) or 0, reverse=True)
    for item in media_items:
        url = _dict_image_url(item, base=base)
        if url:
            return url
    for item in entry.get("media_thumbnail") or []:
        url = _dict_image_url(item, base=base)
        if url:
            return url
    image = entry.get("image")
    if isinstance(image, dict):
        url = _dict_image_url(image, base=base)
        if url:
            return url
    for item in entry.get("enclosures") or []:
        url = _dict_image_url(item, base=base)
        if url:
            return url
    for item in entry.get("links") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("rel") or "").lower() != "enclosure":
            continue
        url = _dict_image_url(item, base=base)
        if url:
            return url
    html_chunks: list[str] = []
    for block in entry.get("content") or []:
        if isinstance(block, dict) and block.get("value"):
            html_chunks.append(str(block["value"]))
    for key in ("summary", "description"):
        val = entry.get(key)
        if val:
            html_chunks.append(str(val))
    for html in html_chunks:
        url = _html_img_src(html, base=base)
        if url:
            return url
    return None


def fetch_og_image(client: httpx.Client, url: str) -> str | None:
    """One HTML GET for og:image. Failures are per-URL, not fatal."""
    try:
        response = client.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            },
            timeout=20.0,
        )
        response.raise_for_status()
        return parse_share_image(response.text, base=str(response.url))
    except (httpx.HTTPError, OSError):
        return None


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


def store_items(
    conn: sqlite3.Connection,
    feed_id: str,
    entries: list,
    *,
    fill_images: int = 0,
    image_delay: float = 0.2,
) -> tuple[int, int, int]:
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    updated = 0
    og_filled = 0
    budget = max(0, fill_images)
    client: httpx.Client | None = None
    try:
        for entry in entries:
            guid = item_guid(entry)
            published = parse_date(entry.get("published_parsed") or entry.get("updated_parsed"))
            if not published:
                published = parse_date(entry.get("published") or entry.get("updated"))
            link = entry.get("link")
            summary = entry.get("summary") or entry.get("description")

            existing = conn.execute(
                "SELECT image_url FROM items WHERE feed_id = ? AND guid = ?",
                (feed_id, guid),
            ).fetchone()

            image_url = entry_image_url(entry)
            if not image_url and existing and existing["image_url"]:
                image_url = existing["image_url"]
            elif not image_url and budget > 0 and link:
                if client is None:
                    client = httpx.Client(
                        follow_redirects=True,
                        timeout=20.0,
                        headers={"User-Agent": USER_AGENT},
                    )
                image_url = fetch_og_image(client, str(link))
                budget -= 1
                og_filled += 1 if image_url else 0
                if image_delay > 0:
                    time.sleep(image_delay)

            conn.execute(
                """
                INSERT INTO items (
                    feed_id, guid, title, link, summary, published_at, fetched_at, image_url
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(feed_id, guid) DO UPDATE SET
                    title = excluded.title,
                    link = excluded.link,
                    summary = excluded.summary,
                    published_at = COALESCE(excluded.published_at, items.published_at),
                    image_url = COALESCE(excluded.image_url, items.image_url)
                """,
                (
                    feed_id,
                    guid,
                    entry.get("title"),
                    link,
                    summary,
                    published,
                    now,
                    image_url,
                ),
            )
            if existing:
                updated += 1
            else:
                inserted += 1
    finally:
        if client is not None:
            client.close()
    return inserted, updated, og_filled


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


def fetch_one(
    conn: sqlite3.Connection,
    feed: dict,
    *,
    fill_images: int = 25,
    image_delay: float = 0.2,
) -> None:
    payload = {**feed, "kind": feed.get("kind") or "rss"}
    upsert_feed(conn, payload)
    print(f"→ {feed['id']}: {feed['url']}")
    try:
        raw = fetch_feed(feed["url"])
        parsed = feedparser.parse(raw)
        if getattr(parsed, "bozo", False) and not parsed.entries:
            raise RuntimeError(f"Failed to parse feed: {parsed.get('bozo_exception')}")
        inserted, updated, og_filled = store_items(
            conn,
            feed["id"],
            parsed.entries,
            fill_images=fill_images,
            image_delay=image_delay,
        )
        mark_feed(conn, feed["id"], status="ok")
        conn.commit()
        extra = f", {og_filled} images" if og_filled else ""
        print(
            f"  ok — {len(parsed.entries)} entries "
            f"({inserted} new, {updated} updated{extra})"
        )
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
