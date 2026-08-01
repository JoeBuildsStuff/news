#!/usr/bin/env python3
"""Thin FastAPI read layer over data/feeds.db (FR-002). Pollers stay separate CLIs.

In production (OptiPlex), also serves the Vite build from WEB_DIST on :3000.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from fetch_feeds import DEFAULT_DB, connect

ROOT = Path(__file__).resolve().parent

app = FastAPI(title="news", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:5174",
        "http://localhost:5174",
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)

_db_path: Path = DEFAULT_DB
_web_dist: Path | None = None
_spa_mounted = False


def configure(db_path: Path | None = None, web_dist: Path | None = None) -> None:
    global _db_path, _web_dist
    if db_path is not None:
        _db_path = db_path
    elif os.environ.get("DB_PATH"):
        _db_path = Path(os.environ["DB_PATH"])
    if web_dist is not None:
        _web_dist = web_dist
    elif os.environ.get("WEB_DIST"):
        _web_dist = Path(os.environ["WEB_DIST"])


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = connect(_db_path)
    try:
        yield conn
    finally:
        conn.close()


def row_to_item(row: sqlite3.Row, *, include_body: bool = False) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": row["id"],
        "feed_id": row["feed_id"],
        "feed_name": row["feed_name"],
        "guid": row["guid"],
        "title": row["title"],
        "link": row["link"],
        "summary": row["summary"],
        "published_at": row["published_at"],
        "fetched_at": row["fetched_at"],
        "body_status": row["body_status"],
    }
    if include_body:
        item["body_markdown"] = row["body_markdown"]
        item["body_fetched_at"] = row["body_fetched_at"]
        item["body_error"] = row["body_error"]
    else:
        item["has_body"] = bool(row["body_markdown"]) and row["body_status"] == "ok"
    return item


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/feeds")
def list_feeds() -> dict[str, Any]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                f.id,
                f.name,
                f.url,
                f.last_fetched_at,
                f.last_status,
                COUNT(i.id) AS item_count
            FROM feeds f
            LEFT JOIN items i ON i.feed_id = f.id
            GROUP BY f.id
            ORDER BY f.name COLLATE NOCASE
            """
        ).fetchall()
    return {
        "feeds": [
            {
                "id": row["id"],
                "name": row["name"],
                "url": row["url"],
                "last_fetched_at": row["last_fetched_at"],
                "last_status": row["last_status"],
                "item_count": row["item_count"],
            }
            for row in rows
        ]
    }


@app.get("/api/items")
def list_items(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    feed_id: str | None = Query(None, description="Filter by feeds.id"),
    include_body: bool = Query(False),
) -> dict[str, Any]:
    clauses: list[str] = []
    params: list[Any] = []
    if feed_id:
        clauses.append("i.feed_id = ?")
        params.append(feed_id)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM items i {where}",
            params,
        ).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT
                i.id, i.feed_id, f.name AS feed_name, i.guid,
                i.title, i.link, i.summary, i.published_at, i.fetched_at,
                i.body_status, i.body_markdown, i.body_fetched_at, i.body_error
            FROM items i
            JOIN feeds f ON f.id = i.feed_id
            {where}
            ORDER BY COALESCE(i.published_at, i.fetched_at) DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [row_to_item(row, include_body=include_body) for row in rows],
    }


@app.get("/api/items/{item_id}")
def get_item(item_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT
                i.id, i.feed_id, f.name AS feed_name, i.guid,
                i.title, i.link, i.summary, i.published_at, i.fetched_at,
                i.body_status, i.body_markdown, i.body_fetched_at, i.body_error
            FROM items i
            JOIN feeds f ON f.id = i.feed_id
            WHERE i.id = ?
            """,
            (item_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Item not found")
    return row_to_item(row, include_body=True)


def mount_spa() -> None:
    """Serve Vite build for production. No-op when WEB_DIST is unset (local API)."""
    global _spa_mounted
    if _spa_mounted or _web_dist is None:
        return
    dist = _web_dist
    if not dist.is_dir():
        raise SystemExit(f"WEB_DIST not found: {dist}")

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (dist / full_path).resolve()
        try:
            candidate.relative_to(dist.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")

    _spa_mounted = True


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the local news read API")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--web-dist",
        type=Path,
        default=Path(os.environ["WEB_DIST"]) if os.environ.get("WEB_DIST") else None,
        help="Vite dist directory (enables SPA serving)",
    )
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    configure(args.db, args.web_dist)
    mount_spa()

    import uvicorn

    uvicorn.run(
        "api:app" if args.reload else app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=[str(ROOT)] if args.reload else None,
    )


# Production containers call `python api.py` which runs main(). For `uvicorn api:app`
# without main(), call configure/mount from env at import when WEB_DIST is set.
if os.environ.get("WEB_DIST") and not _spa_mounted:
    configure()
    mount_spa()


if __name__ == "__main__":
    main()
