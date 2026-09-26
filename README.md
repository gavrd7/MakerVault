# MakerVault v0.2.1

MakerVault is a self-hosted makerspace inventory and project system for electronics, firmware, fabrication and 3D-printing assets.

v0.2.1 expands the first real catalogue/inventory workflow with a much broader curated catalogue and local catalogue-image management:

- Django 5.2 LTS backend and authentication
- local accounts, MFA-capable django-allauth, and optional generic OIDC client support
- React + AG Grid frontend
- PostgreSQL database
- Redis + Celery worker in the same MakerVault application container
- board catalogue with common ESP32/ESP8266, Raspberry Pi/Pico, Arduino, Seeed XIAO, M5Stack, Adafruit, SparkFun and Teensy families
- expanded starter catalogue with 65+ board definitions and 130+ common maker-component definitions across sensors, displays, communications, power, audio, controls, motors, connectors, prototyping and more
- structured component attributes such as type, interface, voltage/input and package/form factor
- catalogue image upload and secure remote-image caching into MakerVault media storage
- spreadsheet-style physical inventory with inline editing
- manual board/component creation
- secure ESPBoards.dev URL import with preview and duplicate-aware enrichment
- existing schema for projects, BOMs, files, repositories, listings, filament/spools, printers, 3D models/revisions and print history
- bind-mount or Docker-volume storage selected through .env
- configurable timezone, language, currency, measurement system, PUID, PGID and umask

## Containers

The stack intentionally uses three containers:

1. makervault — Django/Gunicorn + React assets + Celery worker
2. makervault-postgres — PostgreSQL
3. makervault-redis — Redis queue/cache

PostgreSQL and Redis do not publish host ports.

## First start

~~~bash
cp .env.example .env
~~~

Generate a Django secret key:

~~~bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
~~~

Place that value in DJANGO_SECRET_KEY and set a strong POSTGRES_PASSWORD.

Then:

~~~bash
docker compose up -d --build
docker compose logs -f makervault
~~~

Open http://SERVER-IP:8765 by default, or your configured reverse-proxy hostname.

## Updating an existing v0.1 deployment

The normal Git deployment update is:

~~~bash
cd /opt/makervault
git pull --ff-only
sudo docker compose up -d --build --no-deps makervault
~~~

or, where your Docker permissions permit it:

~~~bash
make update
~~~

The v0.2 startup seeds catalogue records idempotently. Existing user-created records are not deleted, and the seeder only creates starter entries that do not already exist.

## Storage: Docker volumes or host folders

The same Compose file supports both modes.

### Docker-managed volumes

~~~dotenv
MEDIA_STORAGE=makervault_media
POSTGRES_STORAGE=makervault_postgres
REDIS_STORAGE=makervault_redis
~~~

### Host bind mounts

~~~dotenv
MEDIA_STORAGE=/mnt/Server/MakerVault/media
POSTGRES_STORAGE=/mnt/Server/MakerVault/postgres
REDIS_STORAGE=/mnt/Server/MakerVault/redis
~~~

Compose interprets an absolute source path as a bind mount and a simple name as a Docker named volume.

## Published web port

~~~dotenv
MAKERVAULT_BIND_ADDRESS=0.0.0.0
MAKERVAULT_PORT=8765
~~~

The application remains on port 8000 inside the container; only the host-side port is configurable.

## Permissions and locale

~~~dotenv
PUID=1000
PGID=1000
UMASK=0022
FIX_PERMISSIONS=true

TZ=Europe/London
DJANGO_TIME_ZONE=Europe/London
DJANGO_LANGUAGE_CODE=en-gb
MAKERVAULT_CURRENCY=GBP
MAKERVAULT_MEASUREMENT_SYSTEM=metric
~~~

MakerVault changes its application UID/GID at startup for bind-mounted media. PostgreSQL remains managed by the official PostgreSQL image's own user.

## Catalogue and inventory

On startup, seed_catalogue creates an idempotent starter set of board and component definitions. The catalogue is deliberately separate from physical inventory: one board definition can represent any number of units you actually own.

Physical inventory IDs are generated automatically when omitted:

- boards: MCU-0001
- components: CMP-0001
- tools/assets: AST-0001
- printed parts: PRT-0001
- other: OTH-0001

Editors/admins can change quantity, status, project, location, price and supplier directly in the inventory grid.

## URL imports

v0.2 includes the first source adapter: **ESPBoards.dev**.

The Import URL flow previews extracted data before committing it. The importer is deliberately restricted to approved public hosts and validates redirects/DNS answers to prevent it becoming an SSRF proxy into the server or LAN.

See docs/IMPORTERS.md for the current security model and planned adapters. ESPBoards imports now attempt to cache a sanitised local copy of the source image automatically; existing remote-image records can be cached with `make cache-catalogue-images`.

## Reverse proxy / Internet exposure

Before exposing MakerVault, configure at least:

~~~dotenv
DJANGO_ALLOWED_HOSTS=maker.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://maker.example.com
DJANGO_SECURE_COOKIES=true
TRUST_PROXY_HEADERS=true
ALLAUTH_TRUSTED_PROXY_COUNT=1
~~~

Once HTTPS is verified, you can additionally enable:

~~~dotenv
DJANGO_SECURE_SSL_REDIRECT=true
DJANGO_HSTS_SECONDS=31536000
~~~

Only enable long HSTS after the hostname is reliably HTTPS-only.

## OIDC

MakerVault can use a generic OpenID Connect provider through django-allauth:

~~~dotenv
OIDC_ENABLED=true
OIDC_PROVIDER_ID=authentik
OIDC_PROVIDER_NAME=Authentik
OIDC_SERVER_URL=https://auth.example.com/application/o/makervault/
OIDC_CLIENT_ID=...
OIDC_CLIENT_SECRET=...
OIDC_PKCE=true
OIDC_AUTO_SIGNUP=true
~~~

The callback path is:

~~~text
/accounts/oidc/<OIDC_PROVIDER_ID>/login/callback/
~~~

MakerVault creates Viewer and Editor Django groups at startup. Full administrators remain Django superusers.

## Files and media

Uploaded media is served through an authenticated Django endpoint. Raster images may display inline; CAD, firmware, archives, SVGs and executables are forced to download.

The data model already supports firmware/source archives, wiring, documents, PCB files, CAD, STL and 3MF assets. A dedicated file browser and Three.js STL/3MF viewer are planned for a later milestone.

## Development and Git

See docs/GIT_WORKFLOW.md.

Useful commands:

~~~bash
make up
make logs
make rebuild-app
make update
make shell
make migrate
make seed-catalogue
make cache-catalogue-images
make createsuperuser
make check
~~~

GitHub Actions verifies Python compilation/importer tests, the React/Vite build and the production Docker image for pull requests and main.


## Catalogue images

MakerVault stores catalogue pictures in the configured media directory rather than relying permanently on third-party hotlinks.

From a board or component detail pane, administrators/editors can:

- upload a JPEG, PNG or WebP image;
- provide a public HTTPS image URL for MakerVault to cache locally;
- replace or remove a cached image.

Uploaded/downloaded images are decoded with Pillow, metadata is stripped, oversized images are reduced, and the stored result is a WebP file. Remote image URLs are checked to prevent access to loopback, private, link-local, reserved and other non-public network addresses.

To cache source images already attached to catalogue metadata:

~~~bash
make cache-catalogue-images
~~~

The physical files live under the configured media storage, e.g. /mnt/Server/MakerVault/media/boards/catalog/ and /mnt/Server/MakerVault/media/components/catalog/.
