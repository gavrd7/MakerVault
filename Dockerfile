# syntax=docker/dockerfile:1.7

FROM node:22-alpine AS frontend-builder
WORKDIR /frontend
COPY frontend/package.json ./package.json
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=Europe/London \
    WEB_CONCURRENCY=2 \
    CELERY_CONCURRENCY=2 \
    GUNICORN_TIMEOUT=120

RUN apt-get update && apt-get install -y --no-install-recommends \
      gosu \
      libmagic1 \
      supervisor \
      tzdata \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./requirements.txt
# The Python base image can carry preinstalled packaging libraries. Remove them
# explicitly before installing MakerVault's audited runtime floors so scanners do
# not retain stale vulnerable distributions alongside the upgraded copies.
RUN pip uninstall -y msgpack setuptools >/dev/null 2>&1 || true \
    && pip install --no-cache-dir "setuptools>=78.1.1" "msgpack>=1.2.1,<2" \
    && pip install --no-cache-dir -r requirements.txt \
    && python -c "import importlib.metadata as m; assert tuple(map(int, m.version('msgpack').split('.'))) >= (1,2,1); assert tuple(map(int, m.version('setuptools').split('.'))) >= (78,1,1)"

RUN groupadd --gid 911 makervault \
    && useradd --uid 911 --gid 911 --create-home --home-dir /home/makervault --shell /bin/bash makervault \
    && mkdir -p /app/media /app/staticfiles /app/run \
    && chown -R makervault:makervault /app/media /app/staticfiles /app/run

COPY backend/ /app/backend/
COPY LICENSE THIRD_PARTY_NOTICES.md /app/
COPY --from=frontend-builder /frontend/dist/ /app/backend/core/static/app/
COPY docker/entrypoint.sh /usr/local/bin/makervault-entrypoint
COPY docker/supervisord.conf /etc/supervisor/conf.d/makervault.conf
RUN chmod -R a+rX /app/backend \
    && chmod +x /usr/local/bin/makervault-entrypoint

WORKDIR /app/backend
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/makervault-entrypoint"]
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/makervault.conf"]
