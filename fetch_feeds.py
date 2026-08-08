#!/usr/bin/env python3
"""Shim: RSS ingest CLI. Implementation lives in backend.ingest.feeds / backend.db."""

from backend.config import DEFAULT_CONFIG, DEFAULT_DB, DEFAULT_X_CONFIG, USER_AGENT
from backend.db import (
    connect,
    fetch_one,
    list_enabled_subscriptions,
    list_recent,
    mark_feed,
    seed_subscriptions,
    upsert_feed,
)
from backend.ingest.feeds import main

__all__ = [
    "DEFAULT_CONFIG",
    "DEFAULT_DB",
    "DEFAULT_X_CONFIG",
    "USER_AGENT",
    "connect",
    "fetch_one",
    "list_enabled_subscriptions",
    "list_recent",
    "main",
    "mark_feed",
    "seed_subscriptions",
    "upsert_feed",
]

if __name__ == "__main__":
    main()
