# MakerVault

MakerVault is a self-hosted makerspace inventory, project and 3D-printing management platform for electronics, firmware, fabrication, CAD and workshop assets.

**Current development build: v0.7.0.1**

MakerVault is designed as a single local source of truth for a maker workspace. Catalogue records describe what a part or printer *is*; physical inventory records what you actually own; projects connect inventory, files, BOMs, models and repositories; and the 3D-printing workspace adds printers, filament, spools, models, print history, analytics and optional external integrations.

All features described below are part of the current MakerVault application. Historical milestone/version notes live in [CHANGELOG.md](CHANGELOG.md) and [docs/ROADMAP.md](docs/ROADMAP.md).

## Highlights

- Self-hosted Django + React application with PostgreSQL and Redis.
- Board and maker-component catalogue with technical enrichment and local image caching.
- Spreadsheet-style physical inventory with generated IDs, lifecycle history and project assignment.
- Project workspaces with notes, images, files, repositories, BOMs, stock allocation and cost rollups.
- Central Files library for project-linked and standalone assets with immutable file-version history.
- First-class 3D Printing workspace for printers, filament products, physical spools, multi-material slots, models and print history.
- Interactive STL/3MF viewer with local geometry analysis, mesh-health checks, orientation guidance and printer-fit checks.
- STL/3MF thumbnails throughout Files, Projects and the Model Library.
- Print-history analytics and automatic material-cost estimation from physical spool purchase data.
- Optional Spoolman, Creality CFS and SimplyPrint integrations while MakerVault remains usable without any external service.
- Responsive desktop, tablet and mobile interface.
- Local accounts, MFA-capable django-allauth and optional OpenID Connect.
- Background maintenance, enrichment and catalogue-image tasks through Celery.

## Application architecture

The default deployment uses three containers:

1. **makervault** — Django/Gunicorn, compiled React frontend and Celery worker/beat
2. **makervault-postgres** — PostgreSQL
3. **makervault-redis** — Redis queue/cache

PostgreSQL and Redis do not publish host ports by default.

MakerVault application code is built into the production image rather than bind-mounted, making deployments reproducible while allowing Docker to cache dependency layers between builds.

## Quick start

Copy the example environment file:

```bash
cp .env.example .env
```

Generate a Django secret key:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

Set that value as `DJANGO_SECRET_KEY`, choose a strong `POSTGRES_PASSWORD`, then start MakerVault:

```bash
docker compose up -d --build
docker compose logs -f makervault
```

The default web endpoint is:

```text
http://SERVER-IP:8765
```

The host address and port can be changed with:

```dotenv
MAKERVAULT_BIND_ADDRESS=0.0.0.0
MAKERVAULT_PORT=8765
```

## Updating MakerVault

For a normal deployment update:

```bash
cd /mnt/Server/MakerVault/app
git fetch origin
git switch main
git pull --ff-only origin main
sudo docker compose up -d --build
```

or, where Docker permissions allow it:

```bash
make update
```

Database migrations and idempotent catalogue seed/maintenance steps are applied by the normal startup process. Existing user-created records are preserved.

## Storage

MakerVault supports either Docker-managed named volumes or host bind mounts.

### Docker-managed volumes

```dotenv
MEDIA_STORAGE=makervault_media
POSTGRES_STORAGE=makervault_postgres
REDIS_STORAGE=makervault_redis
```

### Host bind mounts

```dotenv
MEDIA_STORAGE=/mnt/Server/MakerVault/media
POSTGRES_STORAGE=/mnt/Server/MakerVault/postgres
REDIS_STORAGE=/mnt/Server/MakerVault/redis
```

An absolute source path is treated as a bind mount; a simple name is treated as a Docker named volume.

## Locale and permissions

Common deployment settings include:

```dotenv
PUID=1000
PGID=1000
UMASK=0022
FIX_PERMISSIONS=true

TZ=Europe/London
DJANGO_TIME_ZONE=Europe/London
DJANGO_LANGUAGE_CODE=en-gb
MAKERVAULT_CURRENCY=GBP
MAKERVAULT_MEASUREMENT_SYSTEM=metric
```

MakerVault can adjust ownership of its writable application/media directories at startup for bind-mounted deployments. PostgreSQL remains managed by the official PostgreSQL image's own user.

---

## Catalogue

MakerVault separates reusable catalogue definitions from physical inventory.

A catalogue entry describes a board, component, printer model or filament product. Physical inventory then represents the units, spools and assets you actually own.

### Boards

The board catalogue includes common families such as:

- ESP32 / ESP8266
- Raspberry Pi / Pico / RP2040 / RP2350
- Arduino
- Seeed XIAO
- M5Stack
- Adafruit
- SparkFun
- Teensy

Board records can contain structured technical information including CPU, clock, cores, SRAM, ADC/DAC, buses, PWM, pin count, operating voltage and native USB.

Unknown technical values remain distinguishable from capabilities known not to apply. MakerVault does not infer that a missing field means unsupported.

### Components

The component catalogue covers common maker hardware including sensors, displays, communications, power, audio, controls, motors, connectors and prototyping parts.

Generic components are intentionally manufacturer-neutral. Structured attributes can include type, interface, voltage/input and package/form factor.

### Automatic enrichment

Supported board records can be enriched from curated profiles and factual online sources. Existing populated/user-edited values are not overwritten merely because another source contains a value.

ESP-family records can receive factual enrichment from ESPBoards.dev.

To run the complete catalogue refresh manually:

```bash
make refresh-catalogue
```

or:

```bash
docker compose exec makervault python manage.py seed_catalogue
docker compose exec makervault python manage.py enrich_board_catalogue
docker compose exec makervault python manage.py seed_catalogue_images --force-retry
```

### Secure URL imports

MakerVault supports secure ESPBoards.dev URL import with preview and duplicate-aware enrichment.

The importer is restricted to approved public hosts and validates redirects/DNS results to prevent it becoming an SSRF proxy into the MakerVault host or local network.

See [docs/IMPORTERS.md](docs/IMPORTERS.md) for importer security details.

---

## Catalogue images

MakerVault stores catalogue images locally rather than relying on permanent third-party hotlinks.

Editors can:

- upload JPEG, PNG or WebP images;
- provide a public HTTPS image URL for MakerVault to cache locally;
- replace or remove an existing image.

Uploaded and downloaded images are decoded with Pillow, metadata is stripped, oversized images are reduced and the stored result is a local WebP file.

Remote URLs are validated to block loopback, private, link-local, reserved and other non-public addresses.

Automatic image discovery can use:

- Wikimedia Commons
- Openverse
- optional ESPBoards artwork when deliberately enabled

MakerVault defaults to open-licensed Commons/Openverse media. ESPBoards artwork is disabled by default because its illustrations/pinouts use CC BY-NC 4.0.

Example settings:

```dotenv
SEED_CATALOGUE_IMAGES=true
CATALOGUE_IMAGE_MAX_PER_RUN=60
CATALOGUE_IMAGE_RETRY_DAYS=7
CATALOGUE_IMAGE_PREFER_ESPBOARDS=false
CATALOGUE_IMAGE_WIKIMEDIA=true
CATALOGUE_IMAGE_OPENVERSE=true
```

Source page, provider, licence and author information are retained for cached catalogue media.

---

## Physical inventory

Physical inventory tracks the actual items you own separately from catalogue definitions.

Generated IDs follow category prefixes such as:

- boards: `MCU-0001`
- components: `CMP-0001`
- tools/assets: `AST-0001`
- printed parts: `PRT-0001`
- other: `OTH-0001`

Inventory records support:

- quantity
- condition/status
- location
- assigned project
- purchase price
- supplier
- identifiers
- notes
- linked catalogue model
- BOM allocated quantity
- free/unallocated quantity

The spreadsheet-style inventory view supports inline editing, while opening a row exposes the complete physical record.

### Inventory lifecycle history

MakerVault records lifecycle/audit history for physical inventory changes.

Creation, project assignment, status, location and other edits preserve previous/new values plus the responsible user rather than silently overwriting history.

---

## Projects

Projects are full MakerVault workspaces rather than simple labels.

A project can contain:

- status and date information
- summary, description and build notes
- tags and external reference URL
- cover image and gallery images
- assigned physical inventory
- purchase-cost rollups
- bill of materials
- stock allocation
- uploaded files
- repository links
- 3D models and model revisions

Project media uses the same authenticated MakerVault file system as the rest of the application.

### Bill of materials and stock allocation

Projects can maintain a structured BOM using catalogue boards/components or custom items.

BOM lines track required quantity, unit cost and allocation coverage. Physical inventory is allocated through separate quantity-aware allocation records, allowing one stock lot to serve multiple BOM lines/projects without changing the inventory item's total quantity.

MakerVault prevents:

- over-allocation;
- conflicting project assignments;
- quantity reductions below allocated stock;
- incompatible repair/retired status changes;
- deletion of inventory that is still allocated.

Allocation changes are recorded in inventory lifecycle history.

---

## Files and version history

The central **Files** page manages project-linked and standalone assets.

Supported workflows include firmware/source files, wiring diagrams, documents, PCB/schematic files, CAD, STL/mesh, 3MF slicer projects, archives and other project assets.

Files can be uploaded without a project and attached/detached later without duplicating stored content.

### Immutable versions

Files support immutable version lineage.

Uploading a new version creates a new stored FileAsset while preserving the previous version and its bytes. Normal Files/Project views show the current version while earlier revisions remain downloadable from version history.

This prevents newer CAD/STL/3MF files from silently changing what an older project/model revision originally referred to.

### Image viewer

Catalogue and project images can be opened in MakerVault's image viewer with:

- zoom in/out
- mouse-wheel zoom
- drag/pan
- fit/reset
- keyboard shortcuts
- browser fullscreen

---

## 3D Printing

The 3D Printing workspace is a first-class part of MakerVault.

It manages:

- owned printers
- printer model catalogue
- printing locations
- filament products
- physical spools
- multi-material slots
- 3D models and revisions
- STL/3MF files
- print history
- material consumption
- print analytics
- optional external integrations

MakerVault remains standalone-first: printers, spools, models and history continue to work even when no external integration is configured.

### Printer catalogue

MakerVault includes curated printer records and can optionally expand/refresh manufacturer/model coverage from OrcaSlicer's public printer manifests.

Orca-derived entries retain provenance, while populated MakerVault specifications and user edits remain authoritative.

Example setting:

```dotenv
SYNC_ORCASLICER_PRINTER_CATALOGUE=true
ORCASLICER_PRINTER_CATALOGUE_REF=main
```

### Filament and physical spools

Filament products store reusable material/product information, while physical spools represent the actual spool in inventory.

Spool records can track:

- material/product
- colour
- remaining and initial weight
- purchase cost
- currency
- RFID/UID
- storage/location
- provider links
- printer/multi-material slot assignment

Filament catalogue browsing can use the public SpoolmanDB feed.

### Multi-material systems

Printer slots use a provider-neutral model so different external systems can map into the same MakerVault records.

Current support includes Creality CFS workflows and the underlying model is suitable for AMS-family and future adapters.

---

## External 3D-printing integrations

Integrations are configured from **Settings → 3D Printing** and are shown only when enabled/configured.

### Spoolman

MakerVault can synchronise physical spool information with Spoolman while retaining native MakerVault inventory records.

### Creality CFS

Local CFS discovery can populate printer filament slots and live material/colour state for compatible configured printers.

MakerVault keeps the distinction between a printer model being compatible with a multi-material system and the hardware actually being installed on a specific owned printer.

### SimplyPrint

SimplyPrint is integrated as a read-only/import-oriented provider.

Supported workflows include:

- printer discovery/state import
- assigned filament/extruder context
- explicit mapping to MakerVault physical spools
- recent print-history import
- connection testing
- manual **Sync now**
- scheduled synchronisation

MakerVault does not automatically create physical spools merely because a cloud service reports a filament assignment.

---

## Model Library and 3D viewer

MakerVault has a native Model Library backed by immutable model revisions and FileAsset links.

STL and 3MF files can be:

- uploaded directly;
- attached to model revisions;
- versioned without replacing older files;
- opened from the Model Library;
- opened from model management;
- opened from Files;
- opened from Projects;
- downloaded from revision/file views.

### STL/3MF thumbnails

MakerVault lazily renders local thumbnails from STL/3MF geometry for Files and Projects.

The thumbnail renderer only starts as items approach the viewport and disposes its WebGL context after producing the preview.

### Interactive viewer

The Three.js viewer supports:

- orbit
- zoom
- pan
- reset
- wireframe
- grid
- axes
- fullscreen
- selection of model revisions/assets

Model files remain on the MakerVault server; the viewer does not require an external model-analysis service.

---

## Model Intelligence

MakerVault analyses STL and 3MF geometry locally.

Current analysis includes:

- dimensions
- triangle and vertex counts
- object count for supported 3MF geometry
- surface area
- approximate volume
- mesh complexity
- units/source units
- watertightness
- boundary/open edges
- non-manifold edges
- degenerate triangles
- owned-printer build-volume fit

### Print-orientation guidance

MakerVault compares all six axis-aligned orientations (±X, ±Y, ±Z).

For each orientation it estimates:

- downward-facing/support-risk surface
- bed-contact area
- build height

It then recommends the best of those six candidates.

This is deliberately a geometry heuristic, not a slicer. Final supports, adhesion strategy and print orientation should still be verified in a slicer.

### 3MF slicer metadata

Compatible 3MF files can also expose slicer metadata already stored inside the package.

MakerVault can detect common slicer identity and extract available saved information such as:

- printer profile
- print/process profile
- filament profile
- layer height
- first-layer height
- nozzle diameter
- infill density/pattern
- wall/perimeter count
- top/bottom layers
- support state
- brim configuration

This does **not** run a slicer. MakerVault reads metadata already embedded in the 3MF file, keeps parsing local and bounded, and shows source/provenance information in the Model Intelligence panel.

Existing files can be re-analysed to populate newer intelligence fields.

---

## Print history, costs and analytics

Print jobs can be recorded against printers, models/revisions, projects and material usage.

A print can record:

- printer
- model/revision
- status
- estimated and actual duration
- quantity
- one or more material/spool usage rows
- used filament
- waste
- material cost
- notes/provenance

### Automatic material costing

When a physical spool has both an initial filament weight and purchase cost, MakerVault derives a cost per gram.

For print material usage it can estimate:

```text
(used filament + waste) × spool cost per gram
```

The calculated value is shown before saving and can be manually overridden. Historical stored costs remain authoritative after the print record is created.

### Print analytics

The 3D Printing overview provides aggregate metrics including:

- completed-print success rate
- recorded print time
- filament consumed
- waste
- material cost
- per-printer job counts
- per-printer success/failure rates
- per-printer recorded print time

Currency totals are kept safe: MakerVault does not silently add costs recorded in unrelated currencies.

---

## Catalogue maintenance and scheduled background work

MakerVault uses a persistent catalogue-maintenance schedule stored in PostgreSQL.

Administrators can open **Settings → Library updates** to:

- enable or disable automatic maintenance;
- choose an interval;
- enable technical board-data checks independently from catalogue-image checks;
- inspect the previous and next scheduled run;
- queue maintenance immediately with **Run now**.

Celery Beat performs a lightweight due-time check and queues the normal maintenance work when required.

The schedule survives container rebuilds/restarts.

Server-level hard-disable settings remain available:

```dotenv
ENRICH_BOARD_CATALOGUE=true
SEED_CATALOGUE_IMAGES=true
```

The Settings UI cannot override a server-level hard disable.

---

## Responsive interface

MakerVault is designed for desktop, tablet and phone use.

The responsive interface includes:

- touch-friendly navigation
- mobile-safe viewport handling
- safe-area support
- touch-sized controls
- single-column forms/panels on narrow screens
- horizontally scrollable data grids where compression would make tables unreadable
- mobile detail sheets/modals
- responsive 3D-printing and Settings layouts

---

## Authentication and security

MakerVault supports local accounts through django-allauth, including MFA-capable account flows, plus optional OpenID Connect.

Viewer and Editor groups are created automatically. Full administrators remain Django superusers.

### OpenID Connect

Example configuration:

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

Callback:

```text
/accounts/oidc/<OIDC_PROVIDER_ID>/login/callback/
```

Administrators can also manage database-backed identity providers from **Account & Security**.

### Reverse proxy / Internet exposure

Before exposing MakerVault, configure at least:

```dotenv
DJANGO_ALLOWED_HOSTS=maker.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://maker.example.com
DJANGO_SECURE_COOKIES=true
TRUST_PROXY_HEADERS=true
ALLAUTH_TRUSTED_PROXY_COUNT=1
```

Once HTTPS is verified:

```dotenv
DJANGO_SECURE_SSL_REDIRECT=true
DJANGO_HSTS_SECONDS=31536000
```

Only enable long-lived HSTS after the hostname is reliably HTTPS-only.

Uploaded media is served through authenticated MakerVault endpoints. Non-image files such as CAD, firmware, archives, SVG and executables are forced to download rather than rendered inline.

---

## Useful commands

```bash
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
make refresh-catalogue
make createsuperuser
make check
```

## Development and Git

See [docs/GIT_WORKFLOW.md](docs/GIT_WORKFLOW.md).

GitHub Actions validates the backend, frontend production build, production Docker image and security/vulnerability checks for pull requests and `main`.

---

## Licence

MakerVault software is licensed under **GNU AGPL v3.0 or later (AGPL-3.0-or-later)**. See [LICENSE](LICENSE).

Third-party catalogue images and other media are not relicensed under AGPL. Their original licence/provenance is retained and exposed in **About → Media attribution**.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for third-party source and licence information.
