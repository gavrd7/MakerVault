# MakerVault v0.1.1

MakerVault is a self-hosted makerspace inventory and project system. This first runnable foundation includes:

- Django 5.2 LTS backend and authentication
- Local accounts, MFA-capable django-allauth, and optional generic OIDC client support
- React 19 frontend built into the application image
- PostgreSQL 18 database
- Redis + Celery background worker in the same MakerVault container as the web process
- Initial relational schema for boards, components, inventory, projects, BOMs, files, repositories, marketplace listings, filament/spools, printers, 3D models/revisions, and print history
- Storage selectable per deployment between Docker named volumes and normal host bind mounts
- Configurable timezone, language, currency, measurement system, PUID, PGID and umask
- Basic dashboard and spreadsheet-style inventory grid

## Containers

The stack intentionally uses three containers:

1. `makervault` — Django/Gunicorn + React assets + Celery worker
2. `makervault-postgres` — PostgreSQL
3. `makervault-redis` — Redis queue/cache

PostgreSQL and Redis do not publish host ports.

## First start

```bash
cp .env.example .env
```

Generate a Django secret key:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

Place that value in `DJANGO_SECRET_KEY` and set a strong `POSTGRES_PASSWORD`.

For a first local test you can create the initial administrator automatically:

```dotenv
MAKERVAULT_ADMIN_USERNAME=admin
MAKERVAULT_ADMIN_PASSWORD=choose-a-strong-password
```

Then:

```bash
docker compose up -d --build
docker compose logs -f makervault
```

Open `http://SERVER-IP:8765` by default (or your reverse-proxy hostname). The host port is controlled by `MAKERVAULT_PORT` in `.env`, so for example `MAKERVAULT_PORT=9123` publishes MakerVault on port 9123. The Gunicorn service remains on port 8000 *inside* the Docker network; you normally do not need to change that. Set `MAKERVAULT_BIND_ADDRESS=127.0.0.1` if your reverse proxy runs on the host and you do not want the application port listening on other interfaces.

After the admin user has been created, remove `MAKERVAULT_ADMIN_PASSWORD` from `.env` and recreate/restart the app container so the password is no longer present in its environment.

## Storage: Docker volumes or host folders

The same Compose file supports both modes.

## Published web port

The host-side HTTP port is configurable in `.env`:

```dotenv
MAKERVAULT_BIND_ADDRESS=0.0.0.0
MAKERVAULT_PORT=8765
```

Change `8765` to any free host port, for example `9123`. Docker maps this to MakerVault's fixed internal port 8000. Keeping the internal port fixed simplifies health checks and reverse-proxy/container networking while still allowing each installation to choose any host port.

### Docker-managed volumes (default)

```dotenv
MEDIA_STORAGE=makervault_media
POSTGRES_STORAGE=makervault_postgres
REDIS_STORAGE=makervault_redis
```

### Host bind mounts

For a server layout such as `/mnt/Server/MakerVault`:

```bash
sudo mkdir -p /mnt/Server/MakerVault/{media,postgres,redis}
```

Then set:

```dotenv
MEDIA_STORAGE=/mnt/Server/MakerVault/media
POSTGRES_STORAGE=/mnt/Server/MakerVault/postgres
REDIS_STORAGE=/mnt/Server/MakerVault/redis
```

Compose interprets an absolute source path as a bind mount and a simple name as a Docker named volume.

### Permissions

The MakerVault web/worker processes run as the UID/GID selected in `.env`:

```dotenv
PUID=1000
PGID=1000
UMASK=0022
FIX_PERMISSIONS=true
```

At startup the app container adjusts its `makervault` account to those IDs and, by default, fixes ownership of its writable media directory. This is useful for normal Linux bind mounts.

PostgreSQL is intentionally left under the official image's own database account. Its entrypoint initializes/chowns its data directory as required. Do **not** force the PostgreSQL service to use `PUID`/`PGID`.

If the media path is on NFS or another filesystem where container root cannot chown, set `FIX_PERMISSIONS=false` and prepare the directory ownership on the host yourself.

## Locale and time

```dotenv
TZ=Europe/London
DJANGO_TIME_ZONE=Europe/London
DJANGO_LANGUAGE_CODE=en-gb
MAKERVAULT_CURRENCY=GBP
MAKERVAULT_MEASUREMENT_SYSTEM=metric
```

`TZ` controls the container timezone. Django stores timestamps in UTC and presents them in `DJANGO_TIME_ZONE`. Currency and measurement settings are exposed to the application as MakerVault defaults and can later be overridden per user/site in the UI.

## Reverse proxy / Internet exposure

Before exposing MakerVault, configure at least:

```dotenv
DJANGO_ALLOWED_HOSTS=maker.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://maker.example.com
DJANGO_SECURE_COOKIES=true
TRUST_PROXY_HEADERS=true
ALLAUTH_TRUSTED_PROXY_COUNT=1
```

Once you have verified HTTPS is working correctly through your proxy, you can additionally enable:

```dotenv
DJANGO_SECURE_SSL_REDIRECT=true
DJANGO_HSTS_SECONDS=31536000
```

Only enable long HSTS after the hostname is reliably HTTPS-only.

The reverse proxy should pass `Host`, `X-Forwarded-For`, and `X-Forwarded-Proto` headers. `ALLAUTH_TRUSTED_PROXY_COUNT=1` tells django-allauth that exactly one proxy in that chain is trusted for client-IP/rate-limit handling; adjust it if your deployment has a different number of trusted proxies.

## OIDC

MakerVault can use a generic OpenID Connect provider through django-allauth. Enable it with:

```dotenv
OIDC_ENABLED=true
OIDC_PROVIDER_ID=authentik
OIDC_PROVIDER_NAME=Authentik
OIDC_SERVER_URL=https://auth.example.com/application/o/makervault/
OIDC_CLIENT_ID=...
OIDC_CLIENT_SECRET=...
OIDC_PKCE=true
OIDC_AUTO_SIGNUP=true
```

The callback path is:

```text
/accounts/oidc/<OIDC_PROVIDER_ID>/login/callback/
```

The exact `OIDC_SERVER_URL` is provider-specific and should point to the provider's OIDC discovery/server URL expected by django-allauth.

MakerVault also creates two normal Django groups at startup: **Viewer** (read-only core permissions) and **Editor** (view/add/change core permissions); full administrators remain Django superusers.

Local public registration is disabled by default. `OIDC_AUTO_SIGNUP=true` allows accounts authenticated by your configured OIDC provider to be provisioned on first login; set it to `false` if you want administrators to pre-create/link accounts instead.

## Email

SMTP is optional. If `EMAIL_HOST` is blank, MakerVault uses Django's dummy email backend so password-reset links are not leaked into container logs. Configure `EMAIL_HOST`, port, credentials, TLS and `DEFAULT_FROM_EMAIL` if you want local-account password reset and email verification.

## Current v0.1 schema

The initial migration already creates entities for:

- manufacturers and external catalogue sources
- board models + per-platform compatibility records
- component categories and component models
- projects
- inventory items
- BOM lines
- uploaded file assets
- repository links
- supplier/marketplace listings
- printers
- filament products and physical spools
- 3D models and revisions
- print jobs

This lets later importers (ESPBoards, SpoolmanDB, filament databases, Git repositories, marketplace/product URLs) write into a stable relational model rather than forcing a schema rewrite.

## Development notes

The React source is in `frontend/`. The production Docker build compiles it in a Node build stage, then copies only the generated assets into the Python image. Node is not present in the running MakerVault container.

The app container runs Gunicorn and Celery under Supervisor. This keeps v0.1 to three containers while preserving a clean path to split the web and worker processes into separate containers later using the same image.

## Useful commands

```bash
make up
make logs
make shell
make migrate
make createsuperuser
make check
```

Django admin is available at `/admin/`. Uploaded media is served through an authenticated Django endpoint in v0.1; only raster images are allowed inline, while CAD, firmware, archives, SVGs and executables are forced to download.


## Git-based development and updates

MakerVault is intended to be maintained in Git. See [`docs/GIT_WORKFLOW.md`](docs/GIT_WORKFLOW.md) for the recommended workflow. You can initialise a new local repository with:

```bash
./scripts/init-git.sh
```

For an existing Git deployment, a normal update can be performed with:

```bash
make update
```

That performs a fast-forward-only `git pull` and rebuilds/recreates only the `makervault` application service. PostgreSQL and Redis remain running with their existing persistent storage. Docker layer caching means unchanged Python and Node dependency layers are reused rather than performing a completely clean build every time.
