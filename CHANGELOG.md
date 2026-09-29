# Changelog

## v0.7.1 — in development

- Started the Universal Search & Catalogue Completion milestone.
- Added an ownership-safe universal search backend spanning projects, inventory, boards, components, files, 3D models, printers, physical spools and filament products.
- Added persistent shell search with debounced grouped quick results and a dedicated advanced Search page with record-type, project, manufacturer and sorting controls.
- Added regression coverage ensuring private search results remain owner-scoped while shared catalogue records remain searchable.
- Added a live catalogue-completeness audit for boards, components, printer models and filament products, including image/specification coverage percentages and representative missing-data samples.
- Added the catalogue coverage dashboard to Settings → Library updates as the baseline for the focused enrichment pass.
- Extended OrcaSlicer catalogue synchronisation to derive missing printer build volumes from concrete machine profiles and inheritance chains while preserving existing curated specifications.
- Reworked catalogue image maintenance to prioritise the catalogue with the highest missing-image ratio, with explicit `--kind printers|boards|components` targeting for focused passes.
- Improved printer image discovery by trying exact manufacturer/model terms before generic printer wording while retaining open-license and confidence requirements.
- Added per-catalogue/provider image-seeding diagnostics and sample failure reporting, plus detailed Orca vendor-manifest failure output.

## v0.7.0.1 — 2026-09-29

- Added the first multi-user ownership foundation: projects, inventory, files, printing locations/integrations, physical spools, owned printers, 3D models and print jobs now carry an explicit owner.
- Added a guarded legacy-data migration that preserves existing project creator attribution and assigns otherwise ambiguous pre-v0.7 private records only when MakerVault can identify a sole/explicit owner safely.
- Added `MAKERVAULT_LEGACY_OWNER_USERNAME` as an upgrade escape hatch for existing installations with multiple accounts and ambiguous legacy private data.
- New private records created through the main MakerVault APIs now record their authenticated owner, including model/file revision workflows and printing imports.
- Added per-user storage profiles, an instance-wide 10 GiB default quota policy, category counters and the authenticated `/api/storage/` usage-summary endpoint as the basis for quota enforcement and the personal storage dashboard.
- Enforced authenticated-owner isolation across private API querysets: lists, detail routes, edits and deletes no longer expose another user's private records, including to staff/superusers through ordinary MakerVault APIs.
- Added cross-owner relationship validation for projects, inventory, files/revisions, printers/locations, spools, model assets, print jobs and material usage.
- Changed project slugs, inventory IDs, printing-location names, integration providers and spool IDs from instance-global uniqueness to owner-scoped uniqueness.
- Isolated printing integrations, scheduled sync jobs and external provider links per user so identical remote IDs can safely exist in different accounts.
- Protected private MEDIA_URL delivery with database ownership checks and removed private user records from the Django admin browser.
- Added two-user regression coverage for list isolation, guessed-UUID 404 behaviour, cross-owner linking and owner-scoped identifiers.
- Enforced effective per-user storage quotas before private uploads can grow persistent storage, including general files, immutable file versions, project files/images and STL/3MF model revisions.
- Project cover replacements are charged only for positive net growth, while immutable revisions continue to count in full.
- Added a personal dashboard storage card showing used/quota capacity, remaining space, Models/3MF, project files, images and other-file breakdowns, plus 80%/90%/full warning states.
- Added superuser-only **Users & storage** administration with account status, aggregate private-record/storage counts, instance default quotas, per-user overrides and Unlimited policies without exposing another user's private filenames or project contents.
- Added guarded account disable/reactivate, private-data purge and account deletion controls; self-lockout actions are blocked and destructive operations require exact username confirmation.
- Added AES-256-GCM authenticated encryption for user-private FileAsset data, project covers and inventory images, using opaque random object names and a key source separated from the media volume.
- Added automatic generation/persistence of the private-storage key in a dedicated Docker key volume, with startup refusal if encrypted blobs exist but the key is missing to prevent accidental key replacement and data loss.
- Added a safe legacy-media migration path: pre-v0.7 plaintext private files remain readable during upgrade and are rewritten to encrypted opaque blobs on startup; failed source objects are retained for retry.
- Authenticated private-media delivery and Model Intelligence now read through the encrypted storage layer, while shared catalogue/reference media remains instance-wide and unencrypted.
- Added encryption regression coverage for opaque naming, authenticated round trips, tamper detection, ownership-checked media delivery and legacy plaintext migration.

- Expanded the built-in generic component catalogue from 180 to 387 entries, adding common starter-kit parts, passives, semiconductors, sensors, displays, communications modules, controls, power modules, connectors, logic ICs, motors and maker hardware.
- Added catalogue regression coverage for representative maker-project staples and raised the minimum component-coverage guard.
- Versioned starter-catalogue records consistently so existing installations receive the expanded catalogue idempotently on startup without replacing user-maintained component data.

- Started the v0.7.0 multi-user isolation and secure-storage milestone.
- Defined shared catalogue data versus private user-owned workspace data as an explicit application boundary.
- Planned per-user storage quotas, personal storage usage reporting, administrator user management and encrypted-at-rest user uploads.


## v0.6.6 — 2026-09-28

- Raised local model-analysis format to version 5 for slicer-aware 3MF metadata.
- Added bounded parsing of slicer metadata/config files embedded inside 3MF packages.
- Detects common slicer applications including OrcaSlicer, Bambu Studio, PrusaSlicer, Slic3r and Cura when their identifying metadata is present.
- Normalises commonly stored printer, print/process and filament profile names.
- Surfaces common stored slicer settings including layer/first-layer height, nozzle diameter, infill density/pattern, wall/perimeter count, top/bottom layers, support state and brim configuration.
- Added a dedicated Slicer metadata section to the Model Intelligence panel with source-file disclosure and explicit guidance that MakerVault is reading saved package metadata rather than running a slicer.
- Slicer metadata parsing is size-bounded and uses safe XML parsing; model files remain local to MakerVault.
- Added regression coverage using an OrcaSlicer-style 3MF project settings package.
- Added a production-style 3MF viewer fallback for Bambu/Orca multi-file packages that the stock Three.js 3MF loader can otherwise render as an empty scene.
- Added multi-plate project structure extraction from `model_settings.config`, including plate membership, object counts, material slots and multicolour detection.
- Multi-plate projects no longer show misleading combined-project orientation or owned-printer-fit guidance; those are reserved for future per-plate evaluation.
- Improved initial/reset camera framing so loaded geometry is centred against both horizontal and vertical viewport dimensions.
- Added interactive **All plates / Plate N** filtering to the 3D viewer for Bambu/Orca-style slicer projects, with automatic re-framing when the active plate changes.
- Plate cards in Model Intelligence now act as viewer controls and show their stored material-slot assignments.
- Slicer-project 3MFs preferentially use MakerVault's project-aware renderer so object placement, plate membership and stored filament colours remain available to the viewer.


## v0.6.5 — 2026-09-28

- Added automatic material-cost estimation for print-history usage rows when a physical spool has a purchase cost and starting filament weight. Manually entered costs remain authoritative.
- Physical spool API records now expose purchase cost, currency and derived cost-per-gram for client-side estimates.
- Added aggregate print analytics for completed success rate, recorded print time, filament consumption, waste and material cost.
- Added per-printer job count, success/failure rate and recorded print-time summaries.
- Expanded recent-print rows with duration, material usage, waste and recorded/estimated material cost.
- Print-history entry shows the calculated spool-cost estimate before saving while allowing an explicit override.
- Cost aggregation is currency-safe: the configured MakerVault currency is totalled separately and other-currency rows are reported as excluded.


## v0.6.4 — 2026-09-28

- Model intelligence analysis now refreshes the selected model in place instead of closing the viewer/manage workflow and returning to the Model Library.
- Added local mesh-topology health checks for boundary edges, non-manifold edges, degenerate triangles and watertightness.
- Added six-way axis-aligned print-orientation analysis using a 45° downward-facing surface heuristic, bed-contact estimate and build height, with a recommended orientation and comparison table in the 3D viewer.
- Large meshes skip topology edge counting above a bounded triangle threshold while retaining the rest of the geometry/orientation analysis.
- Normalised View/Download/Detach and Files/Project action sizing and spacing so download links visually match surrounding buttons.
- Extended the STL/3MF viewer into model management, the global Files library and project file lists.
- Added lazy rendered STL/3MF thumbnail previews in Files and Projects, replacing generic extension badges for viewable 3D assets.
- Model revision rows now provide direct **View** and **Download** actions.
- Added direct **Upload new version** from model management; each upload creates a new immutable ModelRevision/FileAsset pair, preserves the previous revision and runs local geometry analysis automatically.
- Added immutable version lineage for general FileAsset records with **Upload new version** actions in Files and Projects; the newest version is shown normally while previous files remain available from version history.
- Hardened project-file deletion so a protected model-linked file cannot lose its stored bytes before the database protection check completes.


## v0.6.3 — 2026-09-28

- Added an explicit responsive viewport and mobile browser metadata so MakerVault scales correctly on phones and tablets.
- Reworked the application shell below 900px into a sticky, horizontally scrollable touch navigation bar while preserving Administration, Account & Security and Sign out actions on small screens.
- Added app-wide phone breakpoints with safe-area support, 44px touch targets, 16px form controls to avoid iOS input zoom, single-column forms/panels, responsive printer/settings/project layouts and full-screen mobile detail sheets.
- AG Grid catalogue/inventory tables now stay readable on narrow screens using horizontal touch scrolling instead of crushing columns.
- Mobile modals behave as bottom sheets with dynamic-viewport sizing and safe-area padding.
- Removed `ComponentModel.manufacturer` from the database schema; board, printer and filament manufacturer models remain unchanged.
- Removed manufacturer from the component API, search, catalogue table, detail view and add-component form.
- Removed manufacturer metadata from the starter component catalogue and stopped seed jobs from creating component-brand manufacturer records.
- Migration `0020_remove_component_manufacturer` removes the component relation and deletes legacy manufacturer rows that were used only by components, while preserving manufacturers still referenced by boards, printers or filaments.
- Older clients may still submit a legacy `manufacturer` field when creating a component; MakerVault safely ignores it rather than recreating the removed dataset.
- Added regression coverage proving components have no manufacturer field, the API does not recreate legacy brands, and starter seed data no longer creates component-only manufacturers.
- Hardened the component-manufacturer migration sequence for PostgreSQL by separating data cleanup from the schema change, avoiding deferred-trigger conflicts during upgrade.
- Added a follow-up migration that merges duplicate generic components exposed by manufacturer removal while preserving and re-pointing inventory, BOM, file and product-listing references.
- Made starter component seeding tolerant of pre-existing duplicate identities so catalogue startup cannot fail with `MultipleObjectsReturned`.
- Reorganised Settings into dedicated **Library updates** and **3D Printing** tabs, establishing a per-feature settings pattern for future areas of MakerVault.
- Reworked 3D-printing integration cards to use responsive, practical-width columns with wrapping actions instead of compressing four cards into one row.
- Replaced the temporary sidebar “M” mark and text title with the committed MakerVault brand logo, while retaining a compact responsive treatment and version label.

## v0.6.2 — 2026-09-28

- Added a live SimplyPrint REST API adapter using account/company ID plus API-key authentication.
- SimplyPrint API keys are retained server-side in integration configuration and are never returned by the Settings API; the frontend only receives an `api_key_configured` flag.
- SimplyPrint is deliberately **read-only/import-only** in this first build so MakerVault remains authoritative.
- Printer discovery uses persistent provider-neutral `ExternalPrinterLink` records; exact existing MakerVault printer-name matches can be linked without overwriting native model/serial/location/notes.
- Imported printer state records SimplyPrint online/state/group/API/UI/firmware/temperature context in printer profile metadata and surfaces the current SimplyPrint state on the printer card.
- SimplyPrint assigned filament/extruders are mapped into provider-neutral `PrinterFilamentSlot` records without automatically creating MakerVault physical spools.
- SimplyPrint filament UID/NFC/colour/material metadata is retained on discovered slots; exact physical spool links become persistent only after the user explicitly links/creates the spool.
- The existing **Add to inventory / Link existing spool** flow now records exact SimplyPrint filament IDs as `ExternalSpoolLink` mappings for future deterministic syncs.
- Recent SimplyPrint print history imports into native MakerVault `PrintJob` records with status, duration, filename/provenance and aggregate reported filament usage, without guessing which MakerVault spool supplied the material.
- Added manual connection testing, manual Sync now and persistent scheduled sync controls to the SimplyPrint Settings card.
- Legacy SimplyPrint placeholder settings are upgraded from **Planned** to **Not configured** automatically.
- Added regression coverage for credential masking, API-key probe headers, existing-printer linking, no-automatic-spool creation, print-history import and explicit SimplyPrint spool mapping.

## v0.6.1 — 2026-09-28

- Added local STL and 3MF geometry analysis stored on model revisions without requiring a schema migration.
- New model uploads are analysed automatically, while existing revision files can be analysed or re-analysed on demand.
- Geometry intelligence records physical dimensions, triangle/vertex counts, mesh complexity, surface area, approximate volume, units and analysis warnings.
- Added an interactive Three.js STL/3MF viewer with orbit, zoom, pan, reset, wireframe, grid, axes and fullscreen controls.
- Model Library rows show compact geometry summaries and analysis state.
- Added owned-printer build-volume fit checks, including direct fit, XY-rotation fit, oversize and unknown-volume states.
- Model analysis stays local to MakerVault; model files are not sent to an external analysis service.
- Added regression coverage for binary STL, 3MF packages, automatic upload analysis and manual revision re-analysis.

## v0.6.0.5 — stable v0.6.0 baseline

- Fixed Spoolman sync failures caused by high-precision floating-point weights/costs by quantizing imported numeric values to MakerVault field precision before validation.
- Added regression coverage for long-decimal Spoolman remaining weight, initial weight, purchase cost, filament diameter, density and spool weights.
- Added a dedicated **Filament Library** view for saved MakerVault filament products.
- Saved filament products now have an **Edit** action covering manufacturer, product/material identity, colour/appearance, finish/pattern/glow, diameter/density/weights, print temperatures and drying settings.
- Editing a filament product preserves the same database identity, so all existing physical spools continue to reference the corrected product.
- Original catalogue/source provenance is retained when a saved filament product is edited.

## v0.6.0.4 — development revision

- Added confirmed **Delete** actions to the full Spool Inventory and Model Library.
- Spool deletion removes the physical inventory record and provider links while retaining the filament product; nullable printer-slot/history references are preserved without the deleted spool.
- Model deletion removes the model/revision/link records while retaining shared MakerVault FileAsset records and print-history entries.
- Added explicit delete permissions to the frontend configuration so destructive controls only appear for authorised users.
- Hardened Spoolman sync error handling so unexpected failures no longer leave a stale **Connected** status.
- Spoolman HTTP failures now include the API's returned validation/error message when available, making per-spool sync failures diagnosable from the Settings UI.
- Added regression coverage for deletion semantics, Spoolman unexpected exceptions and Spoolman API validation-error reporting.

## v0.6.0.3 — development revision

- Added an optional OrcaSlicer-backed 3D-printer catalogue synchroniser using Orca's vendor `machine_model_list` manifests.
- Expanded catalogue maintenance with a dedicated **3D printer catalogue** toggle, scheduled refresh and server-level enable/disable setting.
- Fresh/sparse MakerVault installations perform a best-effort OrcaSlicer catalogue expansion during startup; populated catalogues rely on the normal persistent maintenance schedule.
- OrcaSlicer catalogue imports are idempotent, preserve source/ref/vendor-version provenance and never delete local printer models or overwrite populated MakerVault hardware specifications.
- Normalised Orca manufacturer naming (including Bambu Lab/QIDI/ELEGOO aliases) and collapse Creality `_CFS-C` slicer variants into the base printer model plus optional CFS compatibility.
- Bambu Lab model imports are marked as AMS-family compatible while the actual installed AMS/AMS Lite hardware remains an owned-printer setting.
- Added printer-catalogue model/manufacturer coverage counts to Settings so catalogue growth is visible after a sync.
- Printer catalogue enclosure state now supports unknown, preventing name-only upstream records from being incorrectly labelled as open-frame printers.
- Added OrcaSlicer AGPL-3.0 catalogue-source attribution to MakerVault's third-party notices.

## v0.6.0.2 — development revision

- Separated printer-model multi-material compatibility from the hardware actually installed on each owned printer.
- Added per-printer add-on controls such as Creality CFS / Bambu AMS installed, with safe removal that retires stale live slot assignments.
- CFS synchronisation now only targets active printers where the compatible CFS add-on is explicitly installed.
- Existing printers with previously discovered non-generic multi-material slots are migrated as having the add-on installed so current setups keep working.
- Added separate printer catalogue images for bare printers and printer + multi-material/Combo configurations.
- Printer cards automatically prefer the Combo/add-on image when the owned printer has the add-on installed, with fallback to the bare-printer image.
- Catalogue image maintenance now searches and caches bare and Combo/add-on printer images independently with separate open-media attribution metadata.

## v0.6.0.1 — development revision

- Introduced four-part development build versions so iterative v0.6.0 work can be identified precisely without advancing the v0.6.1 feature milestone.
- The running version is now sourced centrally by the backend and displayed dynamically in the MakerVault sidebar/About page.
- Repaired pre-v0.6.0.1 CFS slot links: live colour/material/vendor conflicts always detach an incorrect physical spool, while compatible legacy links are retained and marked for future syncs.
- Added printer-catalogue image fields and extended MakerVault's open-licensed Wikimedia/Openverse image seeder and attribution register to 3D-printer models.
- Added compact printer-model thumbnails beside owned printer entries with a neutral fallback when no confidently matched open image is available.

## v0.6.0 — milestone baseline

- Replaced the 3D Printing placeholder with the first native printing/model workspace.
- Added provider-neutral external spool links so MakerVault spools can map to optional services such as Spoolman or SimplyPrint without making those services required.
- Added provider-neutral printer filament slots for Creality CFS, Bambu AMS and future multi-material adapters.
- Reworked print material tracking into multi-spool material usage rows, preserving legacy print consumption data while supporting CFS/AMS-style multi-material jobs.
- Added ModelRevisionAsset links so STL/3MF/CAD assets reuse existing FileAsset records instead of duplicating storage.
- Migrated legacy direct ModelRevision file fields into FileAsset links without duplicating stored bytes, leaving FileAsset as the single revision-file system.
- Added native create APIs/UI for printers, filament products, physical spools and 3D models.
- Added dedicated 3D-printer and filament manufacturer catalogues so printing data no longer reuses board/component manufacturers.
- Added an owned-printer catalogue with active/inactive state, reusable locations, local host/IP metadata and manufacturer-filtered printer model selection.
- Added starter printer specification profiles that can populate build volume, nozzle size, enclosure and multi-material capabilities when adding an owned printer.
- Added reusable printing/storage locations and structured spool placement at either a storage location or an owned printer.
- Added direct STL/3MF upload from Add Model on desktop or mobile; MakerVault creates the model, initial revision and FileAsset link in one workflow.
- Fixed Add Spool to load the current native filament catalogue directly instead of relying on potentially stale page data.
- Moved optional Spoolman, Creality CFS, SimplyPrint and future multi-material adapter status cards into the main Settings area.
- Added configurable Spoolman endpoint/sync direction and connection testing, plus CFS readiness status based on registered compatible printers.
- Physical spool IDs are now allocated automatically as `SPL-####` and are no longer entered manually.
- Added real Spoolman inventory synchronisation with native spool/link creation, remote weight/location updates and safe linked-record export for bidirectional mode.
- Added a read-only local Creality CFS adapter using the K-series WebSocket `boxsInfo` feed to discover loaded slots, filament metadata and RFID-derived remaining percentage.
- Added optional unique RFID/tag identity to physical spool records so otherwise identical reels can remain distinct. Creality CFS material/profile codes are deliberately not treated as physical tag serials: CFS now respects exact colour when suggesting filament products and requires explicit user confirmation to link/create the physical spool for a loaded slot.
- Added per-integration `Sync now`, optional scheduled background sync, configurable sync interval, last/next sync timestamps and persisted sync results.
- Replaced the hard-coded 3D Printing integration roadmap cards with a compact status strip that only shows integrations the user has enabled, including connected/disconnected/error state.
- Added dedicated filament manufacturer/material selectors and manufacturer-product suggestions backed by the open SpoolmanDB catalogue, with custom values retained as a fallback.
- Added native filament appearance fields for opaque, translucent and transparent materials.
- Added a visual filament colour palette, custom colour/hex selector and transparency preview for manual filament creation.
- Added an optional SpoolmanDB browser with search, source-record preview and import into native MakerVault filament products.
- Preserved SpoolmanDB multi-colour, transparency, finish, pattern, glow, temperature, weight and source-provenance metadata during import.
- Added model revision creation and existing MakerVault file attachment/detachment workflows.
- Protected model-linked files from deletion until they are detached from the revision.
- Added PostgreSQL regression coverage for printing overview, native CRUD, external spool identity, revision file reuse and project/file integrity.
- Spoolman and Creality CFS have live adapters; SimplyPrint and the remaining future multi-material integrations stay optional/planned while MakerVault remains standalone-first.


## v0.5.0

- Added first-class project bill-of-materials management for catalogue boards, catalogue components and custom materials.
- Added quantity-aware BOM allocation records so physical inventory can be allocated without mutating or duplicating stock records.
- Added migration 0005, including best-effort conversion of legacy BOM inventory links into allocation records.
- Projects now show BOM line counts, required/allocated/remaining quantities, allocation status and estimated BOM cost.
- Added create/edit/remove BOM controls and allocate/adjust/release inventory workflows inside the project workspace.
- Inventory now exposes total quantity, BOM-allocated quantity and free quantity in both the grid and detail view.
- Allocation operations use database transactions and row locks to prevent concurrent over-allocation.
- Added data-integrity guards preventing BOM over-allocation, stock over-allocation, incompatible project assignment, repair/retired status while allocated, stock quantity reductions below allocations, and deletion of allocated inventory.
- BOM allocation and release events are recorded in inventory lifecycle history.
- Added BOM allocation administration views and extensive API/integrity/permission tests.
- Existing project files, standalone Files workflows and catalogue maintenance remain unchanged.


## v0.4.3

- Added direct uploads from the Files page so FileAsset records no longer require a project.
- Standalone files use the same established MakerVault extension allow-list and authenticated storage rules as project assets.
- Added Standalone as the default project choice for direct file uploads, with optional project assignment at upload time.
- Added a Standalone files filter to the global Files library.
- Added file management from the Files page so an existing asset can be attached to or detached from a project without re-uploading or duplicating the stored file.
- Added direct standalone file removal with stored-file cleanup.
- Added FileAsset permissions to the SPA configuration for role-aware upload/manage controls.
- Added API tests for standalone upload, existing extension validation, project attachment without duplication and stored-file deletion.
- No database migration is required.


## v0.4.2

- Added project file uploads using the existing FileAsset model without a new database migration.
- Project files are grouped by source code, firmware, executable/binary, CAD, STL/mesh, 3MF/slicer, PCB, wiring/schematic, document, archive and other categories.
- Added automatic file-category suggestions in the upload UI while keeping the category user-editable.
- Added file version and description metadata, original filename/size metadata and SHA-256 hashing.
- Non-image project assets continue to use MakerVault's authenticated download-only media delivery.
- Added project file removal with stored-file cleanup.
- Added project repository links for GitHub, GitLab, local and other repositories, including default branch metadata.
- Replaced the placeholder Files page with a cross-project categorized asset browser that reuses the same FileAsset records and links back to the owning project.
- Project cards and detail metrics now show digital asset/repository counts alongside inventory and photos.
- Added project asset API tests for upload validation, hashing, detail serialization, deletion and repository links.
- Added docs/ROADMAP.md as the canonical current milestone reference.


## v0.4.1

- Added persistent automatic catalogue-maintenance scheduling with a default 24-hour interval.
- Added Celery Beat inside the existing MakerVault application container; no extra Docker service is required.
- Added an administrator-only Settings page for catalogue maintenance.
- Schedule interval is configurable from 1 to 720 hours and persists in PostgreSQL across container rebuilds/restarts.
- Added separate toggles for technical board-data checks and catalogue-image checks.
- Added a Run now control for immediate manual maintenance without changing the saved schedule.
- The scheduler queues existing enrichment/image jobs with a forced source retry on the configured cadence, while preserving locks, licence/confidence checks and user-value protection.
- Removed the old behaviour that queued catalogue enrichment on every container restart.
- Environment flags ENRICH_BOARD_CATALOGUE and SEED_CATALOGUE_IMAGES remain server-level hard disables that the GUI cannot override.
- Added last-run, next-run and trigger metadata to the settings view.
- Added migration 0004 for the singleton catalogue maintenance settings record.


## v0.4.0

- Replaced the placeholder Projects page with a full project workspace.
- Added project create/edit/detail APIs and responsive project cards/detail drawer.
- Added project notes, tags and reference URL fields with migration 0003.
- Added project status, start/completion dates, descriptions and build notes.
- Added project cover image upload/removal using MakerVault's sanitised local WebP pipeline.
- Added project photo gallery storage through existing FileAsset records.
- Added assigned physical inventory visibility inside project details.
- Added project inventory-cost rollups from assigned physical inventory purchase prices.
- Added project permissions to the SPA configuration for role-aware controls.
- Added a reusable image viewer/lightbox with zoom, pan, fit/reset and browser fullscreen.
- Board catalogue images now open directly in the image viewer; project cover/gallery images use the same viewer.
- Prepared the project workspace for follow-on catalogue maintenance, project file/repository workflows, and BOM/inventory allocation.


## v0.3.8

- Added explicit per-field technical specification state: known value, unknown, or not applicable.
- Unknown fields remain blank in the UI and are retained in a backend enrichment backlog instead of being confused with unsupported capabilities.
- Known unsupported capabilities render as N/A; explicit negative capabilities such as Native USB can render as No.
- Added persistent technical_unresolved_fields and technical_field_status metadata to board specifications without a database migration.
- Curated board profiles can now mark capabilities as not applicable using authoritative board/family knowledge.
- Added initial N/A coverage for common Arduino and Raspberry Pi Pico variants.
- Added explicit negative AVR capability facts such as no native USB on ATmega328P/2560/4809 and zero DAC channels.
- The Refresh specs action now applies all available enrichment layers to every board, not only ESP-family boards.
- Enrichment state is versioned so future source adapters can revisit only unresolved fields.
- No database migration is required.


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
