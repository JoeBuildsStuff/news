#!/usr/bin/env python3
"""Shim: FastAPI entrypoint. Implementation lives in backend.main."""

from backend.main import app, configure, main, mount_spa

__all__ = ["app", "configure", "main", "mount_spa"]

if __name__ == "__main__":
    main()
