# MakerVault roadmap

_Last updated: 1 October 2026_

This file tracks completed MakerVault milestones and the planned path toward a stable v1 release. The `main` branch is the deployable source of truth.

## Completed milestones

### v0.4.x — Projects, scheduling and files

- **v0.4.0:** first-class project workspaces, project metadata, cover/gallery images, assigned inventory and cost rollups.
- **v0.4.1:** persistent catalogue-maintenance scheduling with administrator controls and manual Run now.
- **v0.4.2:** project files and repository links using the shared FileAsset model.
- **v0.4.3:** standalone Files library with optional project assignment and direct file management.

### v0.5.0 — BOM and inventory allocation

- First-class project bills of materials.
- Quantity-aware allocation from physical inventory without mutating stock totals.
- Partial/multi-stock allocation, allocation history and free/allocated quantity reporting.
- Transactional integrity protections against over-allocation and incompatible stock changes.

### v0.6.0 — 3D Printing & Model Library

- Native owned-printer, filament-product, physical-spool, printing-location, model/revision and print-history records.
- Direct STL/3MF model upload using the shared MakerVault file system.
- Provider-neutral external spool links and multi-material printer slots.
- Spoolman inventory synchronisation and local Creality CFS discovery.
- SpoolmanDB-backed filament catalogue and OrcaSlicer-backed printer catalogue expansion.
- Manual and scheduled printing-integration synchronisation while MakerVault remains standalone-first.

### v0.6.1 — Model intelligence & 3D viewer

- Local STL and 3MF geometry analysis.
- Dimensions, triangle/vertex counts, mesh complexity, surface area and approximate volume.
- Interactive Three.js viewer with orbit, zoom, pan, wireframe, grid, axes and fullscreen.
- Owned-printer build-volume fit checks.
- Model files remain local to MakerVault during analysis.

### v0.6.2 — SimplyPrint integration

- Read-only SimplyPrint API integration using account/company ID and API key.
- Printer-state and loaded-filament context mapped to MakerVault's provider-neutral records.
- Recent print-history import.
- Explicit physical-spool linking rather than automatic spool creation.
- Manual connection testing, Sync now and scheduled synchronisation.

### v0.6.3 — Responsive UI & generic component cleanup

- Responsive desktop/tablet/mobile application shell and touch-friendly workflows.
- Dedicated Settings tabs for Library updates and 3D Printing.
- Improved responsive layout for printing integration settings.
- Generic electronics components are manufacturer-neutral throughout the schema, API and UI.
- Upgrade migrations consolidate legacy duplicate generic components while preserving references.
- MakerVault application branding added to the main interface.

### v0.6.4 — Model/file intelligence & version workflow

- Immutable FileAsset version lineage with latest-version library/project views and downloadable history.
- STL/3MF thumbnails and direct View actions in Files, Projects and model management.
- Direct model-revision upload that preserves earlier STL/3MF revisions and automatically re-runs local analysis.
- Mesh-health analysis for watertightness, open/boundary edges, non-manifold edges and degenerate triangles.
- Six-way axis-aligned orientation guidance comparing support-risk surface, bed contact and build height.
- Slicer output remains authoritative; MakerVault's orientation guidance is deliberately a local geometry heuristic.

### v0.6.5 — Print cost & history analytics

- Automatic material-cost estimation from physical-spool purchase price and initial filament weight.
- Manual cost overrides remain supported and are stored historically on print material usage.
- Aggregate success rate, recorded print time, material consumption, waste and cost metrics.
- Per-printer job/success/time summaries and richer recent-print history rows.
- Currency-safe aggregation that does not silently combine unrelated currencies.

### v0.6.6 — Slicer metadata intelligence

- Read slicer metadata stored inside compatible 3MF packages without invoking or depending on a slicer.
- Detect common slicer application identity and saved printer/process/filament profiles.
- Normalise common saved settings such as layer height, nozzle diameter, infill, wall count, support state and brim configuration.
- Surface those settings alongside MakerVault's geometry/mesh/orientation intelligence with clear provenance and limitations.
- Keep parsing local, bounded and safe for self-hosted deployments.
- Production-style multi-file 3MF rendering with multicolour/material-slot awareness.
- Multi-plate project detection and interactive per-plate viewer filtering.

### v0.7.0.1 — Multi-user isolation & secure storage

- Enforced backend ownership boundaries for private user data while retaining shared reference catalogues.
- Migrated legacy private records safely to an existing administrator/owner account.
- Added administrator-only account management, quota controls, aggregate storage reporting and guarded destructive actions without a cross-user private-file browser.
- Added configurable instance-default and per-user storage quotas, including Unlimited mode and server-side enforcement before storage grows.
- Added personal storage dashboards with total usage, quota percentage and category breakdowns for models/3MF, project files, images and other files.
- Counted immutable file revisions and persistent generated user assets toward quota while excluding temporary processing/decryption files.
- Added authenticated encryption at rest for user-private file storage using opaque object names and key material separated from the media volume.
- Preserved Model Intelligence and authenticated media access through controlled storage/decryption paths.
- Added a safe legacy plaintext-to-encrypted migration path and verified it against a real pre-v0.7 production snapshot.
- Added a dedicated self-hosted GitHub Actions runner with an optional GitHub-hosted execution path.
- Production upgrade, ownership audit, encrypted-file migration and mobile administrator UI were validated successfully before release.

### v0.7.1 — Universal search & catalogue completion

- Added ownership-safe universal search across projects, inventory, boards, components, files, 3D models, printers, spools and filament products.
- Added persistent shell quick search plus a dedicated advanced Search page with type, project, manufacturer, date and sort controls.
- Added direct result navigation into Files and 3D Printing libraries with exact-record focus and responsive/mobile search refinements.
- Added live catalogue coverage reporting for boards, components, printers and filaments, including representative unresolved records.
- Expanded curated board/component technical profiles and explicit source-authority/provenance handling.
- Extended OrcaSlicer printer ingestion to derive build volumes from machine profiles and inheritance chains.
- Improved catalogue image enrichment with structured product metadata, conservative open-media matching and exact OrcaSlicer printer cover references.
- Added conservative multi-material image handling that accepts curated manufacturer-backed combo imagery without fuzzy variant matching.
- Preserved licensing/source attribution and remote-reference behaviour for imagery that cannot safely be redistributed.
- Validated the milestone against live catalogue data and completed backend, frontend, dependency/security and Docker image CI checks before release.

### v0.7.2 — Maker Tags & interactive wiring

- Added owner-scoped QR, NFC and RFID Maker Tags for inventory, spools, printers, projects and locations, including reassignment/history, printable QR labels, broad reader identities and mobile/desktop scan workflows.
- Added project-attached and standalone structured Wiring Lab diagrams with searchable board/component/inventory nodes, catalogue-aware pin selectors, drag positioning, editable connections and JSON/SVG export.
- Added cautious electrical validation for obvious power/ground, voltage, bus-direction and output conflicts while preserving explicit unknown states for incomplete catalogue data.
- Completed a focused board catalogue/image-quality pass with lookup normalisation, authoritative source refreshes and conservative community fallbacks where manufacturer sources do not exist.
- Validated the milestone on mobile/live data and completed frontend, backend, dependency/security and Docker image CI before release on 1 October 2026.

## Planned milestones

---

### v0.7.3 — Live printer connectivity, monitoring & manufacturer adapters

**Released v0.7.3.2:** the provider-neutral live layer now covers Moonraker/Klipper, OctoPrint, Creality local, Bambu Lab local, PrusaLink, Anycubic LAN and FlashForge local. Creality connection and print monitoring have been validated against K2 and K1; K1 also passed Moonraker monitoring; Bambu/Prusa/Anycubic/FlashForge remain experimental pending volunteer hardware validation. Live CFS, AMS, ACE and FlashForge material-station observations map into the same provider-neutral printer-slot records without auto-creating physical spools. Elegoo/QIDI/Sovol/Voron can reuse Moonraker where their firmware exposes it; Snapmaker and remaining manufacturer-specific gaps are still open.

**Goal:** make printer monitoring local-first and provider-neutral, with SimplyPrint remaining optional.

#### Provider-neutral live printer layer

- Add a common printer connection/capability abstraction separate from inventory and multi-material integrations.
- Normalise online/offline state, printer state, current job, progress, elapsed/remaining time, temperatures, filename, thumbnails, cameras, warnings/errors and material context where supported.
- Allow one MakerVault printer to combine multiple useful sources without creating duplicate printer records.
- Prefer direct/local connections where available; cloud/service integrations remain optional.
- Add automatic creation/update/completion of MakerVault PrintJob records from live printer activity where confidence is sufficient.
- Implemented explicit plain-G-code gram estimates and Moonraker extrusion-length/metadata estimates with source labels and manual-row precedence. TODO: additional manufacturer-reported weights, binary/archived G-code and explicit per-tool/spool allocation. Missing metadata remains unrecorded; duration and CFS percentages are not converted to grams.
- Keep polling/subscription frequency configurable and avoid making the core app dependent on any single manufacturer ecosystem.
- Planned for v0.9.0: implement and hardware-test viewable camera streams per adapter, beginning with Creality K1/K2. A camera capability or WebRTC flag alone does not provide a browser feed; the live UI must explicitly identify unavailable feeds until stream support is implemented.

#### Core printer adapters

- Add **Moonraker / Klipper** support as a first-class local printer adapter.
- Add **OctoPrint** support as a first-class local printer adapter.
- Expand the existing Creality local connection beyond CFS slot data to expose printer/job status where the available interface allows.
- Keep SimplyPrint as an optional source for status/history rather than a prerequisite for monitoring.
- Add manufacturer/local adapter families for **Bambu Lab**, **Anycubic**, **FlashForge**, **Prusa**, **Elegoo**, **QIDI**, **Sovol**, **Snapmaker** and **Voron**, using local APIs/protocols where available and cloud APIs only where they add value.
- Treat **Voron** primarily through its common Klipper/Moonraker stack, while allowing Voron-specific metadata and community hardware integrations to layer on top rather than creating duplicate printer records.

#### Multi-material/manufacturer framework

- Formalise the existing provider-neutral multi-material slot model into a documented adapter contract.
- Retain and expand **Creality CFS** support.
- Add explicit adapter targets for **Bambu Lab AMS / AMS Lite**, **Anycubic ACE / ACE Pro**, **Prusa MMU3 and successor systems**, **FlashForge multi-material/filament systems**, **Elegoo multi-material systems**, **QIDI multi-material systems**, **Sovol multi-material/toolchanger systems where exposed**, **Snapmaker multi-material systems**, and **Voron community multi-material/toolchanger ecosystems**.
- Model each manufacturer integration as capabilities rather than assumptions: printer telemetry, job state, temperatures, camera, loaded-material slots, RFID/tag data, remaining material, multi-colour/tool assignment, and optional printer controls are exposed only when that adapter actually supports them.
- Allow a printer to combine a manufacturer adapter with Moonraker/Klipper, OctoPrint or SimplyPrint without duplicating the physical printer in MakerVault.
- Treat **Prusa**, **Anycubic**, **FlashForge**, **Sovol** and similar manufacturers as full printer-integration families that may provide live status and job telemetry as well as multi-material context.
- Keep undocumented or reverse-engineered capabilities isolated behind experimental adapters so they can be disabled independently if upstream firmware changes.
- Implement documented capabilities even when development hardware is unavailable.
- Mark adapters that have not been exercised against real hardware as **experimental / community validation required** rather than claiming full support.
- Add fixtures/mock responses and contract tests so unowned hardware adapters can still be exercised in CI.
- Document the information needed from volunteer testers and provide a repeatable validation checklist.
- Promote an adapter from experimental to supported only after successful real-hardware validation.

#### Optional printer control

**v0.7.3.2 implementation:** per-source opt-in and owner/editor-guarded Pause, Resume and confirmed Cancel for Creality local, Moonraker manufacturer profiles and OctoPrint. Persistent receipts prevent request replay; fresh job/state checks guard dispatch. Controls require hardware validation, beginning with the development K2. Other adapters remain monitoring-only for this pass; hardware validation is tracked in [TODO #37](https://github.com/gavrd7/MakerVault/issues/37).

- Design adapters with explicit capability/permission reporting from the start.
- Initial monitoring remains read-only by default.
- Add Pause/Resume and confirmed Cancel only where the adapter safely supports them.
- Treat Start print as a later optional capability because it carries greater safety/state/file-selection implications.
- Keep advanced controls such as movement, heating, macros and raw G-code outside the initial monitoring milestone unless a clear MakerVault use case emerges.

---

### v0.8.0 — Printed parts & physical tracking

**Released v0.8.0:** explicit retained-part batches with owner-scoped project/location/state tracking, replacement links, change history and Maker Tags. Whole-job material context is shown without duplicating filament totals. Automatic part creation is not enabled.

**Goal:** close the loop from digital model and print job to the physical object that now exists.

- Introduce first-class Printed Part records.
- Link printed parts to model/revision, PrintJob, printer, project, quantity and consumed materials/cost where known.
- Track physical state such as available, installed/in-use, spare, failed, scrapped or retired.
- Track storage/location and project installation.
- Reuse the v0.7.2 Maker Tags system for QR/NFC identification and physical labels.
- Offer explicit printed-part creation from successful monitored print jobs. Never create parts automatically by default; saving models and retaining parts are optional, while filament accounting covers all confidently tracked print jobs where a usable source is available.
- Track replacements, reprints and scrapped/failed physical parts without losing production history.
- Surface project-level views of installed/required/spare printed parts.

---

### v0.9.0 — Printer camera feeds & live viewing

**In development:** shared provider contracts and per-adapter guidance, K1 direct/Helper Script presets, experimental PrusaLink snapshot discovery and manufacturer-reported Anycubic/FlashForge HTTP candidates; on-demand JPEG/PNG and MJPEG-derived live images, Moonraker/OctoPrint discovery, manual same-host sources and experimental Creality legacy/token-protected WebRTC. HTTP viewing is approximately 1 fps; WebRTC media requires browser LAN/VPN access. Full-rate proxy streaming, generic HLS/RTSP/WebRTC, separate camera hosts and media relaying remain follow-up work. Owner confirmed K1/K2 playback on 2 October 2026; per-route, firmware/browser and lifecycle checks remain pending. Camera setup is separate from telemetry, with printer-card previews, dashboard camera links and an optional camera step after adding a live source.

**Goal:** show usable printer camera feeds inside MakerVault, with local-first connections and accurate per-adapter support reporting.

Revised by the owner on 1 October 2026. Camera-feed development replaces the former printer maintenance/workshop milestone; maintenance logs, schedules and reminders remain outside planned scope.

- Begin hardware validation with the available **Creality K1 and K2**, including K1 access through Creality and Moonraker. Validate each stream route independently; working printer monitoring does not establish camera support.
- Add a provider-neutral camera-source contract separating reported camera metadata, configured sources, browser-viewable feeds and connection errors.
- Discover camera sources where adapters expose usable metadata and allow explicit configuration where discovery is unavailable. Support choosing a camera when multiple sources are available.
- Implement supported snapshot/MJPEG routes first; assess WebRTC, HLS and other transports per adapter instead of assuming a reported flag provides a working stream.
- Add a responsive viewer to **Open live**, with clear loading, unavailable/error and reconnect states, plus fullscreen viewing. Add compact dashboard and 3D Printing entry points without starting streams automatically on every card.
- Keep playback user-initiated by default and stop stream connections when the viewer closes or the selected camera changes.
- Handle authenticated/local feeds through owner-scoped access where needed, keeping printer credentials out of browser URLs, diagnostics and logs.
- Validate configured endpoints and redirects against existing remote-access protections; bound proxy connections, response sizes and timeouts, and support HTTPS/reverse-proxy deployments without mixed-content failures.
- Extend Moonraker/OctoPrint and manufacturer adapters where documented camera interfaces are available. Unsupported or untested transports stay explicitly unavailable/experimental.
- Add protocol fixtures and automated permission/error/cleanup tests, plus a hardware checklist covering desktop/mobile playback, authentication, reconnects and bandwidth.
- Document source setup, transport limitations and the tested model/firmware/adapter matrix. Promote support only after real playback validation.

---

### v1.0 — Release hardening & documentation

**Goal:** turn the accumulated feature set into a polished, documented and dependable first stable release.

- Complete the end-user/self-hosting guide and publish it in a maintainable GitHub Pages/wiki-style format.
- Add first-run/setup guidance for users with limited Docker experience.
- Document backup/restore, encrypted key backup and disaster recovery.
- Document upgrade paths and supported migration guarantees.
- Finalise integration capability/support matrices and experimental-adapter labelling.
- Review import/export and data portability.
- Expand automated upgrade/regression testing across representative historical releases.
- Final accessibility/responsive/UI consistency pass.
- Security review of authentication, file handling, integrations, remote printer access and destructive workflows.
- Review configuration defaults, diagnostics and support bundles/logging.
- Define the supported v1 deployment model and release/upgrade policy.

## Post-v1 exploration

### MakerVault hardware tag reader

**Goal:** provide an optional local hardware companion for fast physical-object identification without making dedicated hardware a requirement for MakerVault.

- Explore an ESP32-based network reader using common NFC/RFID hardware such as PN532-class readers.
- Allow a tap/scan to resolve a Maker Tag against the user's MakerVault instance over the local network.
- Support useful workshop workflows such as identifying inventory/components, spools, printers and storage locations; opening the linked record; and initiating context-aware actions where appropriate.
- Reuse the generic Maker Tags identity model and API rather than introducing a hardware-specific tag database.
- Design secure device enrolment/authentication, revocation and least-privilege API access before allowing reader-initiated changes.
- Consider a simple enclosure/PCB/reference build plus ESPHome/Home Assistant interoperability where it does not compromise the standalone MakerVault workflow.
- Keep ordinary QR scanning, phone NFC and USB/OTG readers fully supported so the hardware reader remains optional.
- Revisit implementation after the stable v1 release rather than expanding pre-v1 scope.

---

## Ongoing tracks

The following remain cross-cutting rather than tied to only one milestone:

- deeper slicer/profile analysis where useful metadata is reliably available;
- broader engineering-file previews and metadata;
- BOM/inventory workflow refinements;
- additional manufacturer integrations and multi-material adapters;
- catalogue/image/specification enrichment;
- security scans, dependency maintenance and CI improvements;
- mobile/responsive improvements;
- performance and database/indexing work as real-world data sets grow.

Version scope may still be adjusted as implementation teaches us more, but the sequence above represents the current intended path to v1.


