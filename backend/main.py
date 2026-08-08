"""FastAPI app entry: hub + chat routers, optional SPA, uvicorn CLI."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api.chat import configure as configure_chat_api
from backend.api.chat import router as chat_router
from backend.api.deps import configure_db, get_db_path
from backend.api.hub import router as hub_router
from backend.config import DEFAULT_DB, ROOT, load_env

load_env()

app = FastAPI(title="news", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:5174",
        "http://localhost:5174",
    ],
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(hub_router)
app.include_router(chat_router)

_web_dist: Path | None = None
_spa_mounted = False
configure_db()
configure_chat_api(get_db_path())


def configure(db_path: Path | None = None, web_dist: Path | None = None) -> None:
    global _web_dist
    configure_db(db_path)
    if web_dist is not None:
        _web_dist = web_dist
    elif os.environ.get("WEB_DIST"):
        _web_dist = Path(os.environ["WEB_DIST"])
    configure_chat_api(get_db_path())


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
        "backend.main:app" if args.reload else app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=[str(ROOT)] if args.reload else None,
    )


# Production containers call `python api.py` / `python -m backend` which runs
# main(). For `uvicorn backend.main:app` without main(), mount SPA from env.
if os.environ.get("WEB_DIST") and not _spa_mounted:
    configure()
    mount_spa()


if __name__ == "__main__":
    main()
