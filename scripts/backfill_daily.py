#!/usr/bin/env python3
"""Daily Anthropic sitemap backfill (gaps left by community RSS)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = os.environ.get("DB_PATH", str(ROOT / "data" / "feeds.db"))


def main() -> int:
    cmd = [sys.executable, "backfill.py", "--db", DB, "--days", "7"]
    print(f"==> backfill: {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd, cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
