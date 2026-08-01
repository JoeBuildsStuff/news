#!/usr/bin/env python3
"""Poll configured X accounts and upsert posts into the local SQLite database."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv
from xdk import Client

from fetch_feeds import DEFAULT_DB
from fetch_feeds import connect as feed_connect
from fetch_feeds import list_recent, mark_feed, upsert_feed

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "x_accounts.yaml"
POST_FIELDS = ["created_at", "author_id", "conversation_id", "lang", "public_metrics", "text"]


def load_env() -> None:
    load_dotenv(ROOT / ".env.local")
    load_dotenv(ROOT / ".env")


def load_accounts(path: Path) -> list[dict]:
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    accounts = data.get("accounts") or []
    if not accounts:
        raise SystemExit(f"No accounts found in {path}")
    return accounts


def make_client() -> Client:
    bearer = os.getenv("X_BEARER_TOKEN")
    if not bearer:
        raise SystemExit(
            "Missing X_BEARER_TOKEN. Add it to .env.local "
            "(from the X Developer Console)."
        )
    return Client(bearer_token=bearer)


def ensure_x_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS x_accounts (
            username TEXT PRIMARY KEY COLLATE NOCASE,
            user_id TEXT NOT NULL,
            resolved_at TEXT NOT NULL
        );
        """
    )


def format_api_error(exc: BaseException) -> str:
    text = str(exc)
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            payload = None
        if isinstance(payload, dict):
            detail = payload.get("detail") or payload.get("title")
            reason = payload.get("reason")
            if detail and reason:
                return f"{detail} (reason={reason})"
            if detail:
                return detail
    if "client-not-enrolled" in text or "Client Forbidden" in text:
        return (
            "X API access not enabled for this app. In https://console.x.com "
            "attach the App to a Project and enroll in pay-per-use / API access, "
            "then regenerate the Bearer Token."
        )
    return text


def resolve_user_id(conn: sqlite3.Connection, client: Client, username: str) -> str:
    row = conn.execute(
        "SELECT user_id FROM x_accounts WHERE username = ? COLLATE NOCASE",
        (username,),
    ).fetchone()
    if row:
        return row["user_id"]

    try:
        response = client.users.get_by_username(username=username)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(format_api_error(exc)) from exc
    user = response.data
    if user is None:
        raise RuntimeError(f"User not found: @{username}")
    user_id = str(user.id)
    conn.execute(
        """
        INSERT INTO x_accounts (username, user_id, resolved_at)
        VALUES (?, ?, ?)
        ON CONFLICT(username) DO UPDATE SET
            user_id = excluded.user_id,
            resolved_at = excluded.resolved_at
        """,
        (username, user_id, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    print(f"  resolved @{username} → {user_id}")
    return user_id


def latest_post_id(conn: sqlite3.Connection, feed_id: str) -> str | None:
    row = conn.execute(
        """
        SELECT guid FROM items
        WHERE feed_id = ?
        ORDER BY CAST(guid AS INTEGER) DESC
        LIMIT 1
        """,
        (feed_id,),
    ).fetchone()
    return row["guid"] if row else None


def store_posts(
    conn: sqlite3.Connection,
    *,
    feed_id: str,
    username: str,
    posts: list,
) -> tuple[int, int]:
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    updated = 0
    for post in posts:
        post_id = str(post.id)
        text = getattr(post, "text", None) or ""
        created = getattr(post, "created_at", None)
        if created is not None and hasattr(created, "isoformat"):
            published = created.astimezone(timezone.utc).isoformat()
        elif isinstance(created, str):
            published = created.replace("Z", "+00:00")
        else:
            published = None

        title = text.strip().split("\n", 1)[0][:180] or f"@{username} post"
        link = f"https://x.com/{username}/status/{post_id}"

        existing = conn.execute(
            "SELECT 1 FROM items WHERE feed_id = ? AND guid = ?",
            (feed_id, post_id),
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
            (feed_id, post_id, title, link, text, published, now),
        )
        if existing:
            updated += 1
        else:
            inserted += 1
    return inserted, updated


def fetch_account(
    conn: sqlite3.Connection,
    client: Client,
    account: dict,
    *,
    max_results: int,
    exclude_replies: bool,
    exclude_retweets: bool,
    days: int | None = None,
) -> None:
    username = account["username"].lstrip("@")
    feed = {
        "id": account["id"],
        "name": account["name"],
        "url": f"https://x.com/{username}",
    }
    upsert_feed(conn, feed)
    mode = f"backfill {days}d" if days else "incremental"
    print(f"→ {feed['id']}: @{username} ({mode})")

    try:
        user_id = resolve_user_id(conn, client, username)
        exclude: list[str] = []
        if exclude_replies:
            exclude.append("replies")
        if exclude_retweets:
            exclude.append("retweets")

        kwargs: dict = {
            "id": user_id,
            "max_results": max(5, min(max_results, 100)),
            "post_fields": POST_FIELDS,
        }
        if exclude:
            kwargs["exclude"] = exclude

        if days is not None:
            start = datetime.now(timezone.utc) - timedelta(days=days)
            kwargs["start_time"] = start.strftime("%Y-%m-%dT%H:%M:%SZ")
            kwargs["max_results"] = max(kwargs["max_results"], 100)
        else:
            since_id = latest_post_id(conn, feed["id"])
            if since_id:
                kwargs["since_id"] = since_id

        posts: list = []
        pages = 0
        for page in client.users.get_posts(**kwargs):
            pages += 1
            if page.data:
                posts.extend(page.data)
            # Incremental polls only need the newest page.
            if days is None:
                break

        inserted, updated = store_posts(
            conn, feed_id=feed["id"], username=username, posts=posts
        )
        mark_feed(conn, feed["id"], status="ok" if days is None else "backfill-ok")
        conn.commit()
        print(
            f"  ok — {len(posts)} posts across {pages} page(s) "
            f"({inserted} new, {updated} updated)"
        )
    except Exception as exc:  # noqa: BLE001 - surface fetch errors per account
        message = format_api_error(exc)
        mark_feed(conn, feed["id"], status="error", error=message)
        conn.commit()
        print(f"  error — {message}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch X posts into local SQLite")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--list", action="store_true", help="List recent stored items")
    parser.add_argument("--limit", type=int, default=20, help="Items to show with --list")
    parser.add_argument(
        "--max-results",
        type=int,
        default=10,
        help="Posts per page for incremental polls (5–100)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Backfill posts from the last N days (paginates; ignores since_id)",
    )
    parser.add_argument(
        "--include-replies",
        action="store_true",
        help="Include reply posts (excluded by default)",
    )
    parser.add_argument(
        "--exclude-retweets",
        action="store_true",
        help="Skip retweets",
    )
    args = parser.parse_args()

    load_env()
    conn = feed_connect(args.db)
    ensure_x_schema(conn)
    try:
        if args.list:
            list_recent(conn, args.limit)
            return

        client = make_client()
        accounts = load_accounts(args.config)
        for account in accounts:
            fetch_account(
                conn,
                client,
                account,
                max_results=args.max_results,
                exclude_replies=not args.include_replies,
                exclude_retweets=args.exclude_retweets,
                days=args.days,
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
