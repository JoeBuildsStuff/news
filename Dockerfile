# Build from repo root: docker build -t news .
FROM node:22-bookworm-slim AS web-builder
WORKDIR /web
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm run build

FROM python:3.12-slim-bookworm AS runner
WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends curl \
  && rm -rf /var/lib/apt/lists/* \
  && groupadd --system --gid 1001 appgroup \
  && useradd --system --uid 1001 --gid appgroup appuser \
  && mkdir -p /data \
  && chown appuser:appgroup /data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appgroup \
  api.py fetch_feeds.py fetch_x.py backfill.py enrich.py \
  feeds.yaml x_accounts.yaml ./
COPY --chown=appuser:appgroup scripts ./scripts
COPY --from=web-builder --chown=appuser:appgroup /web/dist ./web/dist

ENV HOST=0.0.0.0 \
    PORT=3000 \
    DB_PATH=/data/feeds.db \
    DB_JOURNAL_MODE=DELETE \
    WEB_DIST=/app/web/dist \
    PYTHONUNBUFFERED=1

USER appuser
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
  CMD curl -fsS http://127.0.0.1:3000/api/health | grep -q '"status":"ok"'

CMD ["python", "api.py"]
