"""Shared FastAPI dependencies: DB connection and optional admin auth."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from fastapi import Header, HTTPException

from backend.config import DEFAULT_DB
from backend.db import connect

_db_path: Path = Path(os.environ["DB_PATH"]) if os.environ.get("DB_PATH") else DEFAULT_DB


def configure_db(db_path: Path | None = None) -> None:
    global _db_path
    if db_path is not None:
        _db_path = db_path
    elif os.environ.get("DB_PATH"):
        _db_path = Path(os.environ["DB_PATH"])


def get_db_path() -> Path:
    return _db_path


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = connect(_db_path)
    try:
        yield conn
    finally:
        conn.close()


def admin_token() -> str | None:
    token = os.environ.get("NEWS_ADMIN_TOKEN")
    return token.strip() if token and token.strip() else None


def auth_required() -> bool:
    return admin_token() is not None


def require_admin(
    authorization: str | None = Header(default=None),
) -> None:
    token = admin_token()
    if token is None:
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    provided = authorization.split(" ", 1)[1].strip()
    if provided != token:
        raise HTTPException(status_code=403, detail="Invalid admin token")
