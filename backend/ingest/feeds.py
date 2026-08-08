"""Fetch configured RSS feeds and upsert items into a local SQLite database."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from backend.config import DEFAULT_CONFIG, DEFAULT_DB
from backend.db import (
    connect,
    fetch_one,
    list_enabled_subscriptions,
    list_recent,
    seed_subscriptions,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and store RSS feeds locally")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="YAML used only for one-time seed (subscriptions live in SQLite)",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--list", action="store_true", help="List recent stored items")
    parser.add_argument("--limit", type=int, default=20, help="Items to show with --list")
    args = parser.parse_args()

    conn = connect(args.db, seed=False)
    try:
        seed_subscriptions(conn, feeds_path=args.config)

        if args.list:
            list_recent(conn, args.limit)
            return

        feeds = list_enabled_subscriptions(conn, "rss")
        if not feeds:
            print("No enabled RSS subscriptions in the database.", file=sys.stderr)
            return
        for feed in feeds:
            fetch_one(conn, feed)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
