# Changelog

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
