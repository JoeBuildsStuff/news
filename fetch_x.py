#!/usr/bin/env python3
"""Shim: X ingest CLI. Implementation lives in backend.ingest.x."""

from backend.ingest.x import (
    ensure_x_schema,
    fetch_account,
    load_env,
    main,
    make_client,
)

__all__ = [
    "ensure_x_schema",
    "fetch_account",
    "load_env",
    "main",
    "make_client",
]

if __name__ == "__main__":
    main()
