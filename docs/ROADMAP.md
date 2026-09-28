# MakerVault roadmap

_Last updated: 28 September 2026_

This file tracks completed MakerVault milestones and the next candidate areas. The `main` branch is the deployable source of truth.

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

## In development

### v0.6.5 — Print cost & history analytics

- Automatic material-cost estimation from physical-spool purchase price and initial filament weight.
- Manual cost overrides remain supported and are stored historically on print material usage.
- Aggregate success rate, recorded print time, material consumption, waste and cost metrics.
- Per-printer job/success/time summaries and richer recent-print history rows.
- Currency-safe aggregation that does not silently combine unrelated currencies.

## Next candidates

After v0.6.5, candidate follow-on areas include:

- deeper slicer-aware analysis beyond the current geometry-only orientation heuristic;
- additional multi-material adapters where a reliable documented/local interface is available;
- richer previews and metadata for additional engineering file types;
- further BOM/inventory workflow refinements;
- broader optional integrations while preserving MakerVault as a standalone source of truth.

Version scope should be assigned only when the next milestone is selected.
