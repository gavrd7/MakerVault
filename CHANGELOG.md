# Changelog

## v0.2.2

- Added automatic background image seeding for starter board and component catalogue records.
- ESP32-family boards prefer matched ESPBoards.dev pages and locally cache their board image where available.
- Added a Wikimedia Commons fallback for boards/components using raster results with accepted free-license metadata.
- Stores image provider, source page, query, license and author provenance with the catalogue record.
- Automatic image work is queued to Celery so application startup remains fast.
- Added configurable per-run limits and retry intervals.
- Existing local/custom images are never overwritten.
- Deliberately removed images are marked as opted out so automatic seeding does not restore them.
- Added seed_catalogue_images management/Makefile commands and source-resolution tests.
- No database migration is required.


## v0.2.1

- Expanded the curated starter catalogue to 65+ board definitions and 130+ common maker components.
- Added broader board-family coverage including Waveshare, LilyGo, Heltec, Olimex, Elecrow and DFRobot alongside existing families.
- Added structured component metadata for type, interface, voltage/input, package/form factor and category-specific attributes.
- Added component detail panes with searchable/filterable catalogue columns.
- Added catalogue image upload for boards and components.
- Added secure HTTPS remote-image caching with private/reserved network blocking, redirect revalidation, size limits and Pillow decoding.
- Catalogue images are sanitised and stored locally as WebP files under MakerVault media storage.
- ESPBoards imports now make a best-effort attempt to cache their product image locally.
- Added a cache_catalogue_images management command for existing records with remote image metadata.
- Added catalogue integrity and image-sanitisation tests.
- No database migration is required for this release.


## v0.2.0

- Added a first-class Board Catalogue page with filtering, board details, connectivity and compatibility information.
- Added an idempotent starter catalogue covering common Espressif/ESP8266, Raspberry Pi/Pico, Arduino, Seeed XIAO, M5Stack, Adafruit, SparkFun and Teensy boards.
- Added a starter component catalogue with common passives, displays, sensors, audio modules, controls, power modules, connectors and motor hardware.
- Added manual board and component creation from the main React interface.
- Added physical inventory creation with automatically generated IDs such as MCU-0001 and CMP-0001.
- Added spreadsheet-style inline editing for inventory quantity, status, assigned project, location, purchase cost and supplier.
- Added authenticated board/component/inventory/project APIs with Django permission checks.
- Added the first URL importer adapter for ESPBoards.dev with a preview-before-commit workflow.
- Added importer SSRF protections: HTTPS/host allow-listing, public-address checks, redirect validation, content-type checks, timeouts and a 4 MiB response cap.
- Added remote catalogue image/reference support through imported board metadata.
- Added CSRF-cookie initialization for the SPA write APIs.
- Added a MakerVault favicon.
- Added GitHub Actions checks for Python compilation/importer tests, the Vite frontend build and the production Docker image build.

## v0.1.1

- Made the published MakerVault HTTP port explicitly configurable with MAKERVAULT_PORT.
- Changed the example/default host port from 8000 to 8765 to reduce conflicts with common self-hosted services.
- Kept the container-internal Gunicorn port at 8000; only the host-side published port changes.
- Added Git repository guidance and line-ending attributes.
- Added make rebuild-app to rebuild/recreate only the MakerVault application service.
- Added make update for a fast-forward Git pull followed by an application-only rebuild.

## v0.1.0

- Initial MakerVault Docker/Django/PostgreSQL/Redis foundation.
