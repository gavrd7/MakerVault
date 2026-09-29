# MakerVault roadmap

_Last updated: 29 September 2026_

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

## Planned milestones

### v0.7.1 — Universal search & catalogue completion

**In development:** the ownership-safe universal search API, shell quick-search UI, advanced Search page and live catalogue coverage audit are now implemented on the milestone branch. The remaining work is catalogue enrichment/source expansion, search refinement and validation.

**Goal:** make MakerVault's growing data set easy to find and substantially improve the completeness of shared reference catalogues.

#### Universal search

- Add a persistent search entry point to the main application shell/top or side navigation.
- Provide grouped quick results across boards, components, inventory, projects, files, models, printers, spools and other relevant user-visible records.
- Add a dedicated advanced **Search** page.
- Support type/category filters, project filters, manufacturer/material/status filters, date ranges and other domain-specific facets where appropriate.
- Add relevance/name/date sorting and clear result provenance.
- Preserve multi-user ownership boundaries in all global search results.
- Add keyboard-friendly navigation and a responsive mobile search experience.

#### Catalogue completion

- Add catalogue coverage reporting for missing images, core specifications and unresolved technical fields.
- Run a focused completion pass across board, component, printer and filament catalogues.
- Expand reputable enrichment sources beyond the current ESP-focused technical path where safe and maintainable.
- Continue to distinguish **known**, **unknown** and **not applicable** technical fields.
- Improve image-source coverage and local image caching while preserving licensing/source metadata.
- Keep scheduled maintenance and retry behaviour for records that remain incomplete.

---

### v0.7.2 — Maker Tags & interactive wiring

**Goal:** connect physical objects to MakerVault and add a maker-friendly structured wiring workspace.

#### Maker Tags — QR / NFC

- Introduce a generic tag identity model rather than a spool-only implementation.
- Support QR-code identities and NFC/RFID UIDs.
- Allow tags to resolve to inventory items, spools, printers, projects, storage locations and future printed parts/equipment.
- Generate printable QR labels and mobile-friendly scan targets.
- Support assignment, reassignment, duplicate detection and tag retirement/history.
- Reuse existing physical spool RFID support instead of creating a parallel identity system.
- Keep the tag target ownership-aware in multi-user installations.

#### Interactive wiring diagrams

- Add a project wiring workspace built around MakerVault boards/components.
- Place boards/components as structured nodes rather than static images only.
- Support pin-to-pin connections with labels, colours/notes and connection metadata.
- Save diagrams as editable structured data and provide export/snapshot options.
- Use catalogue pin/capability metadata where available.
- Add lightweight maker-oriented validation such as duplicate pin use, voltage/capability warnings and missing common-ground hints where confidence is sufficient.
- Retain ordinary uploaded wiring/schematic files alongside the interactive editor.
- Deliberately avoid trying to replace professional PCB/EDA tools such as KiCad.

---

### v0.7.3 — Live printer connectivity, monitoring & manufacturer adapters

**Goal:** make printer monitoring local-first and provider-neutral, with SimplyPrint remaining optional.

#### Provider-neutral live printer layer

- Add a common printer connection/capability abstraction separate from inventory and multi-material integrations.
- Normalise online/offline state, printer state, current job, progress, elapsed/remaining time, temperatures, filename, thumbnails, cameras, warnings/errors and material context where supported.
- Allow one MakerVault printer to combine multiple useful sources without creating duplicate printer records.
- Prefer direct/local connections where available; cloud/service integrations remain optional.
- Add automatic creation/update/completion of MakerVault PrintJob records from live printer activity where confidence is sufficient.
- Keep polling/subscription frequency configurable and avoid making the core app dependent on any single manufacturer ecosystem.

#### Core printer adapters

- Add **Moonraker / Klipper** support as a first-class local printer adapter.
- Add **OctoPrint** support as a first-class local printer adapter.
- Expand the existing Creality local connection beyond CFS slot data to expose printer/job status where the available interface allows.
- Keep SimplyPrint as an optional source for status/history rather than a prerequisite for monitoring.
- Add manufacturer/local adapters where sufficiently documented and technically practical.

#### Multi-material/manufacturer framework

- Formalise the existing provider-neutral multi-material slot model into a documented adapter contract.
- Retain and expand Creality CFS support.
- Add framework-level support for **Bambu Lab AMS**, **Elegoo multi-material systems**, **QIDI multi-material systems** and **Snapmaker multi-material systems** where interfaces are sufficiently documented.
- Implement documented capabilities even when development hardware is unavailable.
- Mark adapters that have not been exercised against real hardware as **experimental / community validation required** rather than claiming full support.
- Add fixtures/mock responses and contract tests so unowned hardware adapters can still be exercised in CI.
- Document the information needed from volunteer testers and provide a repeatable validation checklist.
- Promote an adapter from experimental to supported only after successful real-hardware validation.

#### Optional printer control

- Design adapters with explicit capability/permission reporting from the start.
- Initial monitoring remains read-only by default.
- Add Pause/Resume and confirmed Cancel only where the adapter safely supports them.
- Treat Start print as a later optional capability because it carries greater safety/state/file-selection implications.
- Keep advanced controls such as movement, heating, macros and raw G-code outside the initial monitoring milestone unless a clear MakerVault use case emerges.

---

### v0.8.0 — Printed parts & physical tracking

**Goal:** close the loop from digital model and print job to the physical object that now exists.

- Introduce first-class Printed Part records.
- Link printed parts to model/revision, PrintJob, printer, project, quantity and consumed materials/cost where known.
- Track physical state such as available, installed/in-use, spare, failed, scrapped or retired.
- Track storage/location and project installation.
- Reuse the v0.7.2 Maker Tags system for QR/NFC identification and physical labels.
- Allow a completed monitored print job to offer or automatically create printed-part records where model/quantity confidence is high.
- Track replacements, reprints and scrapped/failed physical parts without losing production history.
- Surface project-level views of installed/required/spare printed parts.

---

### v0.9.0 — Printer lifecycle, maintenance & workshop operations

**Goal:** move MakerVault from printer inventory/monitoring into practical long-term equipment management.

- Printer maintenance/service logs.
- Nozzle changes and nozzle inventory/history.
- Lubrication, belt, filter and other periodic service tasks.
- Consumables and wear-part tracking.
- Configurable maintenance intervals based on time, print hours or usage where telemetry is available.
- Maintenance reminders and dashboard status.
- Firmware/version history where integrations expose it.
- Printer runtime and reliability summaries from live monitoring/history.
- Potential workshop equipment/tool tracking using the same Maker Tag foundation where it adds value.

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
