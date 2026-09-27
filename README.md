# MakerVault v0.3.6

MakerVault is a self-hosted makerspace inventory and project system for electronics, firmware, fabrication and 3D-printing assets.

v0.3 turns physical inventory into first-class asset records and begins automatic technical board-specification enrichment:

- Django 5.2 LTS backend and authentication
- local accounts, MFA-capable django-allauth, and optional generic OIDC client support
- React + AG Grid frontend
- PostgreSQL database
- Redis + Celery worker in the same MakerVault application container
- board catalogue with common ESP32/ESP8266, Raspberry Pi/Pico, Arduino, Seeed XIAO, M5Stack, Adafruit, SparkFun and Teensy families
- expanded starter catalogue with 65+ board definitions and 130+ common maker-component definitions across sensors, displays, communications, power, audio, controls, motors, connectors, prototyping and more
- structured component attributes such as type, interface, voltage/input and package/form factor
- catalogue image upload and secure remote-image caching into MakerVault media storage
- automatic background image seeding for default boards/components, preferring ESPBoards.dev for supported ESP32-family boards and freely licensed raster media from Wikimedia Commons as a fallback
- spreadsheet-style physical inventory with inline editing
- clickable physical inventory records with full detail/edit views
- lifecycle history for assignments, status changes, locations and general edits
- background technical board enrichment from ESPBoards.dev for supported ESP-family boards
- richer board technical details including CPU clock/cores, SRAM, ADC/DAC, buses, PWM, pins, voltage and native USB where available
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
cd /mnt/Server/MakerVault/app
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

Editors/admins can change quantity, status, project, location, price and supplier directly in the inventory grid. Clicking a row opens the full physical record, including purchase data, identifiers, notes, catalogue model information and lifecycle history. Project/status/location changes are retained as history rather than silently replacing the previous state.

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
make enrich-board-catalogue
make seed-catalogue-images
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


## Automatic starter images

By default MakerVault queues a background catalogue-image pass after the starter catalogue is seeded:

~~~dotenv
SEED_CATALOGUE_IMAGES=true
CATALOGUE_IMAGE_MAX_PER_RUN=60
CATALOGUE_IMAGE_RETRY_DAYS=7
CATALOGUE_IMAGE_PREFER_ESPBOARDS=false
CATALOGUE_IMAGE_WIKIMEDIA=true
~~~

ESP32-family board definitions first try a matching ESPBoards.dev board page. Remaining boards and components can use matched raster images from Wikimedia Commons, and MakerVault only accepts a small allow-list of free-license labels from the returned Commons metadata. The selected source page, provider, license and author are retained in the catalogue record.

The work runs through Celery after startup, so Gunicorn does not wait for hundreds of external image requests. Records with a local image are skipped. A failed record is not retried until the configured retry period has elapsed. If a user deliberately removes an image in the UI, MakerVault records an opt-out and does not silently put the automatic image back.

To run or retry the population manually:

~~~bash
make seed-catalogue-images
~~~

Images are still sanitised to local WebP files in MEDIA_STORAGE. Online images are never required for normal page rendering after caching.


## Licence

MakerVault software is licensed under **GNU AGPL v3.0 or later (AGPL-3.0-or-later)**. See [LICENSE](LICENSE).

Third-party catalogue images and other media are not relicensed under AGPL. Their original licence/provenance is retained and exposed in **About → Media attribution**. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

For automatic catalogue images, MakerVault defaults to Wikimedia Commons results reported as CC0/Public Domain, CC BY or CC BY-SA. CC BY-NC and NoDerivatives variants are excluded from the default automatic path. ESPBoards automatic image caching is disabled by default because its own board illustrations/pinouts are CC BY-NC 4.0.


## v0.3 inventory lifecycle

v0.3 introduces an `InventoryHistory` audit/lifecycle model. New physical items receive a creation event, and subsequent changes record their previous/new values plus the user responsible for the change. Existing pre-v0.3 inventory remains intact; its history begins when it is next edited.

Board technical facts are enriched independently from catalogue imagery. This allows MakerVault to use factual source data without requiring the associated third-party artwork. Supported ESP-family records are enriched in the background after startup, and a board detail pane also provides **Refresh specs** for an individual record.

~~~dotenv
ENRICH_BOARD_CATALOGUE=true
BOARD_ENRICHMENT_MAX_PER_RUN=80
~~~

The technical source URL and enrichment timestamp are retained in the board specifications.


## Catalogue coverage refresh (v0.3.6)

MakerVault now combines three safe enrichment layers:

1. Curated board/MCU profiles fill missing technical facts for common ESP32, RP2040/RP2350, Arduino/AVR, SAMD21, RA4M1 and Teensy hardware.
2. ESP-family boards can receive additional board-specific factual data from ESPBoards.dev.
3. Missing catalogue images are searched through Wikimedia Commons and then Openverse, accepting only CC0/Public Domain, CC BY and CC BY-SA results with recorded provenance.

Existing populated fields and custom images are not overwritten. A new image-search generation automatically retries records that older MakerVault releases could not match.

To deliberately run the complete catalogue pass:

~~~bash
make refresh-catalogue
~~~

or without Make:

~~~bash
docker compose exec makervault python manage.py seed_catalogue
docker compose exec makervault python manage.py enrich_board_catalogue
docker compose exec makervault python manage.py seed_catalogue_images --force-retry
~~~

Openverse is an image-discovery/index service; the original media licence, creator and landing/source page are retained on each cached record.
