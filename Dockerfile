# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS ui-builder
WORKDIR /build/web/ui
COPY web/ui/package.json web/ui/package-lock.json ./
RUN npm ci
COPY web/ui/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/
RUN apt-get update \
    && apt-get install --yes --no-install-recommends gcc libc6-dev \
    && python -m pip install --no-cache-dir . \
    && apt-get purge --yes --auto-remove gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system --gid 10001 mucha \
    && adduser --system --uid 10001 --gid 10001 --home /nonexistent --no-create-home mucha \
    && mkdir -p /data/ledger /data/packs /data/artifacts /app/web/ui/dist \
    && chown -R mucha:mucha /data

COPY --chown=mucha:mucha packs/ /data/packs/
COPY --from=ui-builder --chown=mucha:mucha /build/web/ui/dist/ /app/web/ui/dist/

USER mucha
EXPOSE 8787
HEALTHCHECK --interval=5s --timeout=3s --start-period=2s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=2).read()"]
CMD ["python", "-m", "src.webserver", "--host", "0.0.0.0", "--port", "8787", "--allow-non-loopback", "--data-dir", "/data", "--packs-root", "/data/packs", "--static-root", "/app/web/ui/dist"]
