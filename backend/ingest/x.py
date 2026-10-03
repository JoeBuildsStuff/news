#!/usr/bin/env python3
"""Poll configured X accounts and upsert posts into the local SQLite database."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import yaml
from xdk import Client

from backend.config import DEFAULT_DB, DEFAULT_X_CONFIG, load_env
from backend.db import (
    connect as feed_connect,
    list_enabled_subscriptions,
    list_recent,
    mark_feed,
    normalize_http_url,
    normalize_image_url,
    seed_subscriptions,
    upsert_feed,
)
from backend.services.link_previews import is_x_status_url

DEFAULT_CONFIG = DEFAULT_X_CONFIG
POST_FIELDS = [
    "created_at",
    "author_id",
    "conversation_id",
    "lang",
    "public_metrics",
    "text",
    "attachments",
    "entities",
]
MEDIA_FIELDS = [
    "url",
    "preview_image_url",
    "type",
    "media_key",
    "variants",
    "width",
    "height",
    "alt_text",
    "duration_ms",
]
POST_EXPANSIONS = ["attachments.media_keys"]


def load_accounts(path: Path) -> list[dict]:
    """Legacy YAML loader retained for tests / one-off inspection."""
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


def _attr(obj: object, name: str, default: object = None) -> object:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def collect_media_by_key(page: object) -> dict[str, object]:
    out: dict[str, object] = {}
    includes = getattr(page, "includes", None)
    media_list = getattr(includes, "media", None) if includes is not None else None
    if not media_list:
        return out
    for media in media_list:
        key = _attr(media, "media_key")
        if key:
            out[str(key)] = media
    return out


def collect_media_urls(page: object) -> dict[str, str]:
    """Legacy map of media_key → still/preview URL (tests / older callers)."""
    out: dict[str, str] = {}
    for key, media in collect_media_by_key(page).items():
        url = _media_still_url(media)
        if url:
            out[key] = url
    return out


def _media_still_url(media: object) -> str | None:
    url = _attr(media, "url") or _attr(media, "preview_image_url")
    return normalize_image_url(url)


def _best_mp4_url(media: object) -> str | None:
    variants = _attr(media, "variants") or []
    best_url: str | None = None
    best_rate = -1
    for variant in variants:
        content_type = str(_attr(variant, "content_type") or "").lower()
        url = normalize_http_url(_attr(variant, "url"))
        if not url or "mp4" not in content_type:
            continue
        rate = _attr(variant, "bit_rate") or 0
        try:
            rate_i = int(rate)
        except (TypeError, ValueError):
            rate_i = 0
        if rate_i >= best_rate:
            best_rate = rate_i
            best_url = url
    return best_url


def _url_entities(post: object) -> list:
    entities = _attr(post, "entities")
    urls = _attr(entities, "urls") if entities is not None else None
    return list(urls or [])


def _entity_image_url(entity: object) -> str | None:
    images = _attr(entity, "images") or []
    best_url: str | None = None
    best_width = -1
    for image in images:
        url = normalize_http_url(_attr(image, "url"))
        width = _attr(image, "width") or 0
        try:
            width_i = int(width)
        except (TypeError, ValueError):
            width_i = 0
        if url and width_i >= best_width:
            best_width = width_i
            best_url = url
    return best_url


def post_media_list(post: object, media_by_key: dict[str, object]) -> list[dict]:
    """Photos, playable videos, and website cards for one post."""
    tco_by_key: dict[str, str] = {}
    websites: list[dict] = []
    for entity in _url_entities(post):
        tco = normalize_http_url(_attr(entity, "url"))
        media_key = _attr(entity, "media_key")
        if media_key:
            tco_by_key[str(media_key)] = tco or ""
            continue
        expanded = normalize_http_url(
            _attr(entity, "unwound_url") or _attr(entity, "expanded_url")
        )
        if not expanded or is_x_status_url(expanded):
            continue
        title = _attr(entity, "title")
        description = _attr(entity, "description")
        display = _attr(entity, "display_url")
        image_url = _entity_image_url(entity)
        host = urlparse(expanded).netloc.removeprefix("www.")
        websites.append(
            {
                "kind": "website",
                "url": expanded,
                "title": (
                    str(title).strip()
                    if title
                    else (str(display).strip() if display else None)
                ),
                "description": str(description).strip() if description else None,
                "image_url": image_url,
                "site_name": host,
                "tco": tco,
            }
        )

    out: list[dict] = []
    attachments = _attr(post, "attachments")
    keys = _attr(attachments, "media_keys") if attachments is not None else None
    for key in keys or []:
        media = media_by_key.get(str(key))
        if media is None:
            continue
        media_type = str(_attr(media, "type") or "photo").lower()
        tco = tco_by_key.get(str(key)) or None
        alt = _attr(media, "alt_text")
        if media_type in {"video", "animated_gif"}:
            video_url = _best_mp4_url(media)
            preview = normalize_http_url(_attr(media, "preview_image_url"))
            if video_url:
                entry: dict = {
                    "kind": "video",
                    "url": video_url,
                    "preview_url": preview,
                    "alt": alt,
                    "tco": tco,
                }
                # X animated GIFs are silent mp4s. Flag them so the reader loops
                # them instead of showing a paused video control.
                if media_type == "animated_gif":
                    entry["gif"] = True
                out.append(entry)
            elif preview:
                out.append(
                    {
                        "kind": "photo",
                        "url": preview,
                        "preview_url": None,
                        "alt": alt,
                        "tco": tco,
                    }
                )
            continue
        photo_url = _media_still_url(media)
        if photo_url:
            out.append(
                {
                    "kind": "photo",
                    "url": photo_url,
                    "preview_url": None,
                    "alt": alt,
                    "tco": tco,
                }
            )
    out.extend(websites)
    return out


def post_image_url(post: object, media_by_key: dict[str, object]) -> str | None:
    return media_list_image_url(post_media_list(post, media_by_key))


def media_list_image_url(media_list: list[dict]) -> str | None:
    for item in media_list:
        kind = item.get("kind")
        if kind == "photo" and item.get("url"):
            return str(item["url"])
        if kind == "video" and (item.get("preview_url") or item.get("url")):
            return str(item.get("preview_url") or item["url"])
    for item in media_list:
        if item.get("kind") == "website" and item.get("image_url"):
            return str(item["image_url"])
    return None


def store_posts(
    conn: sqlite3.Connection,
    *,
    feed_id: str,
    username: str,
    posts: list,
    media_by_key: dict[str, object] | None = None,
) -> tuple[int, int]:
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    updated = 0
    media_by_key = media_by_key or {}
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
        media_list = post_media_list(post, media_by_key)
        image_url = media_list_image_url(media_list)
        media_json = json.dumps(media_list, ensure_ascii=False) if media_list else None
        conversation_id = str(getattr(post, "conversation_id", None) or post_id)

        existing = conn.execute(
            "SELECT 1 FROM items WHERE feed_id = ? AND guid = ?",
            (feed_id, post_id),
        ).fetchone()

        conn.execute(
            """
            INSERT INTO items (
                feed_id, guid, title, link, summary, published_at, fetched_at,
                image_url, conversation_id, media_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(feed_id, guid) DO UPDATE SET
                title = excluded.title,
                link = excluded.link,
                summary = excluded.summary,
                published_at = COALESCE(excluded.published_at, items.published_at),
                image_url = COALESCE(excluded.image_url, items.image_url),
                conversation_id = COALESCE(
                    excluded.conversation_id, items.conversation_id
                ),
                media_json = COALESCE(excluded.media_json, items.media_json)
            """,
            (
                feed_id,
                post_id,
                title,
                link,
                text,
                published,
                now,
                image_url,
                conversation_id,
                media_json,
            ),
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
        "kind": "x",
        "username": username,
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
            "expansions": POST_EXPANSIONS,
            "media_fields": MEDIA_FIELDS,
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
        media_by_key: dict[str, object] = {}
        pages = 0
        for page in client.users.get_posts(**kwargs):
            pages += 1
            if page.data:
                posts.extend(page.data)
            media_by_key.update(collect_media_by_key(page))
            # Incremental polls only need the newest page.
            if days is None:
                break

        inserted, updated = store_posts(
            conn,
            feed_id=feed["id"],
            username=username,
            posts=posts,
            media_by_key=media_by_key,
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
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="YAML used only for one-time seed (subscriptions live in SQLite)",
    )
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
        help="Include reply posts for this run (overrides per-account setting)",
    )
    parser.add_argument(
        "--exclude-retweets",
        action="store_true",
        help="Skip retweets for this run (forces exclude; otherwise use per-account setting)",
    )
    args = parser.parse_args()

    load_env()
    conn = feed_connect(args.db, seed=False)
    ensure_x_schema(conn)
    try:
        seed_subscriptions(conn, x_path=args.config)

        if args.list:
            list_recent(conn, args.limit)
            return

        client = make_client()
        accounts = list_enabled_subscriptions(conn, "x")
        if not accounts:
            print("No enabled X subscriptions in the database.", file=sys.stderr)
            return
        for account in accounts:
            if not account.get("username"):
                print(
                    f"  skip {account['id']} — missing username",
                    file=sys.stderr,
                )
                continue
            exclude_replies = (
                False if args.include_replies else bool(account.get("exclude_replies", True))
            )
            exclude_retweets = (
                True
                if args.exclude_retweets
                else bool(account.get("exclude_retweets", False))
            )
            fetch_account(
                conn,
                client,
                account,
                max_results=args.max_results,
                exclude_replies=exclude_replies,
                exclude_retweets=exclude_retweets,
                days=args.days,
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
