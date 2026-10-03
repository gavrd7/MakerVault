# syntax=docker/dockerfile:1.7

FROM node:22-alpine AS frontend-builder
WORKDIR /frontend
COPY frontend/package.json ./package.json
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS runtime

ARG TARGETARCH
ARG GO2RTC_VERSION=1.9.14

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
      ca-certificates \
      curl \
      gosu \
      libmagic1 \
      openssl \
      supervisor \
      tzdata \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && . /etc/os-release \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-18 \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    GO2RTC_ARCH="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    case "$GO2RTC_ARCH" in \
      amd64) GO2RTC_ASSET="amd64"; GO2RTC_SHA256="32d616af226bd731678ffde328b94cfb94e30339bfefc469cfb76323144615a6" ;; \
      arm64) GO2RTC_ASSET="arm64"; GO2RTC_SHA256="359fabade8a7a51e81a55fe6df6b0ef81764a5e1d63179577534eaaa71904b50" ;; \
      arm) GO2RTC_ASSET="arm"; GO2RTC_SHA256="4d7e1639af5a2722a28e864468fd8099b3c1682565446c798bf9e3b38fde12e4" ;; \
      *) echo "Unsupported architecture for go2rtc: $GO2RTC_ARCH" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://github.com/AlexxIT/go2rtc/releases/download/v$GO2RTC_VERSION/go2rtc_linux_$GO2RTC_ASSET" -o /usr/local/bin/go2rtc; \
    echo "$GO2RTC_SHA256  /usr/local/bin/go2rtc" | sha256sum -c -; \
    chmod 0755 /usr/local/bin/go2rtc; \
    /usr/local/bin/go2rtc -version

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
COPY LICENSE THIRD_PARTY_NOTICES.md .env.example /app/
COPY --from=frontend-builder /frontend/dist/ /app/backend/core/static/app/
COPY docker/entrypoint.sh /usr/local/bin/makervault-entrypoint
COPY docker/run-https.sh /usr/local/bin/makervault-https
COPY docker/supervisord.conf /etc/supervisor/conf.d/makervault.conf
COPY docker/go2rtc.yaml /etc/go2rtc.yaml
COPY docker/licenses/go2rtc-LICENSE /app/licenses/go2rtc-LICENSE
RUN chmod -R a+rX /app/backend \
    && chmod +x /usr/local/bin/makervault-entrypoint /usr/local/bin/makervault-https

WORKDIR /app/backend
EXPOSE 8000 8443 8555/tcp 8555/udp
ENTRYPOINT ["/usr/local/bin/makervault-entrypoint"]
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/makervault.conf"]
