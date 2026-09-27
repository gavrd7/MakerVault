# Changelog

## v0.3.7

- Rendered all MakerVault modals through a React portal at the document root so drawers, AG Grid and overflow/stacking contexts cannot overlap them.
- Fixed the board image-management modal so catalogue/grid content no longer renders through the dialog.
- Reworked board/detail image sizing to preserve the full source image at arbitrary aspect ratios.
- Catalogue images now use intrinsic dimensions with max-width/max-height containment instead of stretching into fixed-size image boxes.
- Added responsive hero/image-manager frames that scale cleanly across desktop, tablet and mobile without bottom-cropping.
- No database migration is required.


## v0.3.6

- Added broad curated technical profiles for common ESP32/ESP8266, RP2040/RP2350, Arduino/AVR, SAMD21, RA4M1 and Teensy hardware.
- Added board-specific profiles for common Super Mini, Seeed XIAO, Waveshare Zero, Raspberry Pi Pico and Arduino variants.
- Enriched common component records with additional part-level function, interface, address, channel and protocol metadata.
- Starter catalogue upgrades remain idempotent and fill missing fields without replacing populated user values.
- Board catalogue enrichment now applies curated profiles to all board records before optional ESPBoards enrichment.
- Added versioned ESPBoards retry tracking so unmatched boards are not fetched on every restart.
- Added Openverse as a second open-licensed image discovery source after Wikimedia Commons.
- Openverse results are limited to CC0/Public Domain, CC BY and CC BY-SA metadata and preserve creator/source/licence attribution.
- Improved board/component image queries and automatically re-attempt missing images previously tried by older seeder versions.
- Added a refresh-catalogue Make target for a full technical-data and image refresh.
- Improved small flash-size formatting and expanded visible board technical fields.
- No database migration is required.


## v0.3.5

- Renamed the main navigation shortcut from Security / MFA to Account & Security.
- Cleaned up the OIDC provider form layout and fixed the encoded <provider-id> callback placeholder.
- Production startup now fails closed when DJANGO_SECRET_KEY is missing, default, or too short.
- Health-check failures no longer return internal exception details to unauthenticated callers.
- GUI-managed OIDC issuer URLs require HTTPS by default; insecure issuers require an explicit server-admin opt-in.
- X-Forwarded-Host trust is now a separate opt-in rather than being enabled with all proxy headers.
- Arbitrary remote catalogue-image fetching is restricted to administrators; editors may still upload local image files.
- Added pip-audit, Bandit, npm audit, Django --deploy and Trivy container-image checks to CI.\n- Raised msgpack to 1.2.1+ and setuptools to 78.1.1+ after the first container scan identified high-severity fixed vulnerabilities in the cached runtime image.
- Reduced the recommended request-body limit in .env.example to 64 MiB for the current feature set.
- No database migration is required.


## v0.3.4

- Grouped account controls under an explicit Account & Security navigation heading.
- Added administrator-only GUI management for OpenID Connect identity providers.
- GUI providers use django-allauth SocialApp records in PostgreSQL rather than writing MakerVault's .env file.
- Added create/edit/remove and enable/disable controls for OIDC providers.
- Displays the exact OIDC callback URI required by the external identity provider.
- Supports per-provider PKCE, UserInfo fetching and automatic user provisioning settings.
- Client secrets are never displayed after storage; leaving the field blank during edits preserves the current secret.
- Existing environment-backed OIDC configuration remains supported as a read-only bootstrap/fallback provider.
- No database migration is required.


## v0.3.3

- Replaced django-allauth's unstyled default account layout with a MakerVault-branded responsive account/security shell.
- Styled account email, password, account connections, logout and MFA pages consistently with the main application.
- Kept django-allauth's existing TOTP, WebAuthn/passkey and recovery-code security flows intact.
- Added responsive navigation back to MakerVault and account settings.
- Preserved allauth JavaScript hooks required for WebAuthn and account-management actions.
- No database migration is required.


## v0.3.2

- Reworked the board detail view into a genuinely responsive layout.
- Uses a wider side-by-side detail pane on large desktops, an overlay drawer at medium widths, and a full-screen sheet on mobile.
- Removed dependence on the old fixed 350px board-detail layout.
- Board images now scale within a bounded responsive hero area without distorting their aspect ratio.
- Board title/actions, badges, specification grids, compatibility, links and provenance adapt independently to available width.
- Specification grids retain a consistent two-column matrix on desktop/tablet and collapse cleanly to one column on small mobile screens.
- Prevented the catalogue grid from being pushed far below the page when opening details at intermediate resolutions.
- No database migration is required.


## v0.3.1

- Standardised board detail specification tables so every board shows the same fields in the same order.
- Missing values now display as an em dash instead of collapsing sections or changing table height.
- Core and technical specification sections now use the same two-column layout.
- Preserved the two-column matrix in narrow board-detail panes for consistent comparison between boards.
- No database migration is required.


## v0.3.0

- Added full clickable physical inventory detail records.
- Added an inventory edit workflow for project, status, location, identifiers, purchase data, supplier, notes and quantity.
- Added persistent inventory lifecycle/history records with the user, timestamp and before/after values.
- Project assignments/unassignments, status changes and location changes receive dedicated lifecycle events.
- Preserved fast spreadsheet-style inline editing while making rows openable for deeper management.
- Added a database migration for the new InventoryHistory model.
- Expanded ESPBoards parsing for technical facts including CPU cores/clock, SRAM, ADC/DAC, UART, SPI, I2C, PWM, pin count, operating voltage and native USB hints.
- Added automatic background technical-spec enrichment for supported ESP-family catalogue boards.
- Added per-board "Refresh specs" action and richer technical detail display/source links.
- Kept technical data enrichment separate from third-party image licensing.
- Added migration consistency checks to CI.


## v0.2.3

- Licensed MakerVault source code under GNU AGPL v3.0 or later.
- Added THIRD_PARTY_NOTICES.md covering runtime media and bundled open-source dependencies.
- Added an About / Licences & Attribution page with a source-code link, warranty notice and live media attribution register.
- Added an attribution API covering cached/source-linked board and component images.
- Tightened Wikimedia Commons automatic image acceptance to CC0/Public Domain, CC BY and CC BY-SA only.
- Explicitly rejects NonCommercial and NoDerivatives Commons variants from the default automatic path.
- Automatic ESPBoards image caching is now disabled by default because its own board illustrations are CC BY-NC 4.0; it remains an explicit non-commercial opt-in.
- Added public in-app endpoints for the AGPL text and third-party notices.
- No database migration is required.


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
