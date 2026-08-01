# Self-hosting news

Run the prebuilt image, or build from this repo. The SQLite DB is **not** in the image — start with an empty volume and let the poller fill it (or wipe the volume anytime and re-poll).

## Quick start (GHCR)

```bash
cp docker-compose.example.yml docker-compose.yml
cp .env.example .env
# edit .env: X_BEARER_TOKEN, JINA_API_KEY
docker compose up -d
# UI + API: http://127.0.0.1:3000
```

Image: `ghcr.io/joebuildsstuff/news:latest`

Hourly ofelia job runs `scripts/refresh.py` (RSS + X + bounded enrich). Daily job runs Anthropic sitemap backfill. Manual:

```bash
docker compose exec poller python /app/scripts/refresh.py
```

Reset the DB:

```bash
docker compose down
docker volume rm <project>_news-data   # name from `docker volume ls`
docker compose up -d
docker compose exec poller python /app/scripts/refresh.py
```

## Build locally

Uncomment `build:` under `web` / `poller` in compose, or:

```bash
docker build -t news:local .
```

## Reverse proxy

Point your proxy at container port `3000`. Protect the UI if the host is public — this app has no built-in auth.

Homelab-specific Traefik / hostname / SupaGate wiring belongs in a **private overlay** repo (see remotion-player-diy → remotion-player-homelab), not in this OSS tree.
