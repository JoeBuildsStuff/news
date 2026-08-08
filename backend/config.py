"""Repo paths and shared constants. ROOT is the repository root (parent of backend/)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = Path(os.environ.get("DB_PATH", ROOT / "data" / "feeds.db"))
DEFAULT_CONFIG = ROOT / "feeds.yaml"
DEFAULT_X_CONFIG = ROOT / "x_accounts.yaml"
USER_AGENT = "news-local-fetcher/1.0 (+local)"
SEED_META_KEY = "subscriptions_seeded"


def load_env() -> None:
    load_dotenv(ROOT / ".env.local")
    load_dotenv(ROOT / ".env")
