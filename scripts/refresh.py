#!/usr/bin/env python3
"""Hourly OptiPlex ingest: RSS + X, then a bounded Jina enrich pass.

Designed to run under ofelia (compose sidecar). Per-source failures are
handled inside each CLI — this wrapper continues the pipeline.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = os.environ.get("DB_PATH", str(ROOT / "data" / "feeds.db"))
PYTHON = sys.executable


def run(label: str, args: list[str]) -> int:
    cmd = [PYTHON, *args]
    print(f"==> {label}: {' '.join(cmd)}", flush=True)
    completed = subprocess.run(cmd, cwd=ROOT)
    if completed.returncode != 0:
        print(f"!! {label} exited {completed.returncode}", file=sys.stderr, flush=True)
    return completed.returncode


def main() -> int:
    codes = [
        run("fetch_feeds", ["fetch_feeds.py", "--db", DB]),
        run("fetch_x", ["fetch_x.py", "--db", DB]),
        run(
            "enrich",
            ["enrich.py", "--db", DB, "--days", "7", "--limit", "40"],
        ),
    ]
    # Non-zero if every step failed; partial success still exits 0 so ofelia
    # does not treat a single source outage as a hard job failure.
    if all(code != 0 for code in codes):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
