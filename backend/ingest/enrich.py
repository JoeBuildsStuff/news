#!/usr/bin/env python3
"""Fetch full article bodies via Jina Reader and store them on items.

Uses https://r.jina.ai/ with default Readability cleanup (respond-with content),
JSON responses, and chrome stripping. Does not block RSS/X fetch scripts.

X posts are skipped by default (full text already lives in items.summary).
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from backend.config import DEFAULT_DB, USER_AGENT, load_env
from backend.db import connect

JINA_READER = "https://r.jina.ai"
REMOVE_SELECTOR = "nav,header,footer"


def jina_api_key() -> str:
    key = os.getenv("JINA_API_KEY")
    if not key:
        raise SystemExit(
            "Missing JINA_API_KEY. Add it to .env.local "
            "(from https://jina.ai / Reader API)."
        )
    return key


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_jina_payload(payload: Any) -> tuple[str | None, str]:
    """Return (title, markdown) from a Jina JSON response."""
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        data = payload["data"]
    elif isinstance(payload, dict):
        data = payload
    else:
        raise ValueError(f"Unexpected Jina response type: {type(payload)!r}")

    title = data.get("title")
    content = data.get("content") or data.get("text") or data.get("markdown")
    if not content or not str(content).strip():
        raise ValueError("Jina response missing article content")
    return (str(title) if title else None, str(content).strip())


def fetch_article_markdown(
    client: httpx.Client,
    url: str,
    *,
    api_key: str,
    retries: int = 3,
) -> tuple[str | None, str]:
    # Path form: https://r.jina.ai/{url} — quote so query fragments stay intact.
    endpoint = f"{JINA_READER}/{quote(url, safe=':/?#[]@!$&\'()*+,;=')}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        "X-Retain-Images": "none",
        "X-Retain-Media": "none",
        "X-Remove-Selector": REMOVE_SELECTOR,
    }
    last_exc: BaseException | None = None
    for attempt in range(1, retries + 1):
        try:
            response = client.get(endpoint, headers=headers)
            response.raise_for_status()
            return parse_jina_payload(response.json())
        except (httpx.TransportError, httpx.TimeoutException, OSError) as exc:
            last_exc = exc
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            status = exc.response.status_code
            if status not in {408, 425, 429, 500, 502, 503, 504}:
                raise
        if attempt < retries:
            time.sleep(min(2 ** attempt, 8))
    assert last_exc is not None
    raise last_exc


def mark_body(
    conn: sqlite3.Connection,
    item_id: int,
    *,
    status: str,
    markdown: str | None = None,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE items
        SET body_markdown = COALESCE(?, body_markdown),
            body_fetched_at = ?,
            body_status = ?,
            body_error = ?
        WHERE id = ?
        """,
        (markdown, utc_now(), status, error, item_id),
    )


def pending_items(
    conn: sqlite3.Connection,
    *,
    include_x: bool,
    retry_errors: bool,
    days: int | None,
    limit: int | None,
    feed_id: str | None,
) -> list[sqlite3.Row]:
    clauses = ["link IS NOT NULL", "TRIM(link) != ''"]
    params: list[Any] = []

    if retry_errors:
        clauses.append("(body_status IS NULL OR body_status = 'error')")
    else:
        clauses.append("body_status IS NULL")

    if not include_x:
        clauses.append("feed_id NOT LIKE 'x-%'")

    if feed_id:
        clauses.append("feed_id = ?")
        params.append(feed_id)

    if days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        clauses.append("COALESCE(published_at, fetched_at) >= ?")
        params.append(cutoff)

    sql = f"""
        SELECT id, feed_id, title, link
        FROM items
        WHERE {' AND '.join(clauses)}
        ORDER BY COALESCE(published_at, fetched_at) DESC
    """
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    return list(conn.execute(sql, params).fetchall())


def skip_x_posts(conn: sqlite3.Connection) -> int:
    """Mark X items as skipped so they are not picked up as pending."""
    now = utc_now()
    cur = conn.execute(
        """
        UPDATE items
        SET body_status = 'skipped',
            body_fetched_at = ?,
            body_error = 'x post: full text already in summary',
            body_markdown = COALESCE(body_markdown, summary)
        WHERE feed_id LIKE 'x-%'
          AND body_status IS NULL
        """,
        (now,),
    )
    conn.commit()
    return cur.rowcount


def enrich_one(
    conn: sqlite3.Connection,
    client: httpx.Client,
    row: sqlite3.Row,
    *,
    api_key: str,
) -> str:
    item_id = int(row["id"])
    link = row["link"]
    label = row["title"] or link
    try:
        title, markdown = fetch_article_markdown(client, link, api_key=api_key)
        mark_body(conn, item_id, status="ok", markdown=markdown, error=None)
        conn.commit()
        extra = f" ({title})" if title else ""
        print(f"  ok — {row['feed_id']}: {label}{extra} [{len(markdown)} chars]")
        return "ok"
    except Exception as exc:  # noqa: BLE001 - continue other items
        mark_body(conn, item_id, status="error", error=str(exc))
        conn.commit()
        print(f"  error — {row['feed_id']}: {label} — {exc}", file=sys.stderr)
        return "error"


def list_status(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT
            COALESCE(body_status, 'pending') AS status,
            COUNT(*) AS n
        FROM items
        GROUP BY COALESCE(body_status, 'pending')
        ORDER BY status
        """
    ).fetchall()
    total = sum(int(r["n"]) for r in rows)
    print(f"Body enrichment status ({total} items):")
    for row in rows:
        print(f"  {row['status']}: {row['n']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich items with full article markdown via Jina Reader"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Only enrich items published/fetched within the last N days",
    )
    parser.add_argument("--limit", type=int, default=None, help="Max items to process")
    parser.add_argument("--feed", dest="feed_id", help="Only enrich this feed_id")
    parser.add_argument(
        "--delay",
        type=float,
        default=0.4,
        help="Seconds between Jina requests (default: 0.4)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="HTTP timeout seconds per article (default: 60)",
    )
    parser.add_argument(
        "--include-x",
        action="store_true",
        help="Also fetch X post URLs via Jina (skipped by default)",
    )
    parser.add_argument(
        "--skip-x",
        action="store_true",
        help="Mark pending X posts as skipped (copies summary into body_markdown)",
    )
    parser.add_argument(
        "--retry-errors",
        action="store_true",
        help="Retry items with body_status=error as well as pending",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print body enrichment counts and exit",
    )
    args = parser.parse_args()

    load_env()
    conn = connect(args.db)
    try:
        if args.status:
            list_status(conn)
            return

        if args.skip_x or not args.include_x:
            skipped = skip_x_posts(conn)
            if skipped:
                print(f"Marked {skipped} X posts as skipped")

        rows = pending_items(
            conn,
            include_x=args.include_x,
            retry_errors=args.retry_errors,
            days=args.days,
            limit=args.limit,
            feed_id=args.feed_id,
        )
        if not rows:
            print("No pending articles to enrich.")
            list_status(conn)
            return

        api_key = jina_api_key()
        print(f"Enriching {len(rows)} article(s) via Jina Reader…")
        ok = err = 0
        with httpx.Client(follow_redirects=True, timeout=args.timeout) as client:
            for i, row in enumerate(rows):
                result = enrich_one(conn, client, row, api_key=api_key)
                if result == "ok":
                    ok += 1
                else:
                    err += 1
                if i + 1 < len(rows) and args.delay > 0:
                    time.sleep(args.delay)

        print(f"Done — {ok} ok, {err} error(s)")
        list_status(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
