# MakerVault roadmap

_Last updated: 27 September 2026_

This file records the current milestone sequence agreed during active development so version scope does not drift between chats or branches.

## v0.4.0 — Project workspace

Completed and merged.

- First-class Projects page and project detail workspace.
- Status, dates, summary, description, build notes, tags and reference URL.
- Cover images and gallery images.
- Assigned physical inventory and inventory-cost rollups.
- Shared image viewer for project/catalogue imagery.

## v0.4.1 — Scheduled catalogue maintenance

Completed and merged to `main` on 27 September 2026.

- Persistent automatic catalogue-maintenance schedule.
- Default interval: 24 hours; configurable from 1 to 720 hours.
- Separate board-data and catalogue-image checks.
- Admin Settings controls, last/next run visibility and Run now.
- Celery Beat scheduling inside the existing application container.
- Schedule state stored in PostgreSQL across restarts/rebuilds.

## v0.4.2 — Project files and repositories

Completed and merged on 27 September 2026.

The Projects workspace becomes the hub for the digital assets that belong to a build.

Planned scope:

- Upload and attach project files through the existing `FileAsset` model.
- Group project assets by type rather than presenting one undifferentiated file list.
- Supported groups include source code, firmware, CAD, STL/mesh, 3MF/slicer projects, PCB, wiring/schematics, documents, binaries, archives and other files.
- Show the same asset from the relevant project section and the global categorized Files browser without duplicating storage.
- Preserve file name, version, description and project association.
- Add/remove/download controls subject to MakerVault permissions.
- Surface repository links alongside project files using the existing `RepositoryLink` model.
- Keep project photos/gallery separate from general project files even though both use `FileAsset`.

## v0.4.3 — Standalone file library

Completed and merged on 27 September 2026.

- Upload supported MakerVault file types directly from the Files page without requiring a project.
- Keep standalone and project-linked files in the same FileAsset library.
- Allow optional project assignment at upload time.
- Allow an existing file to move between standalone and project-linked use without re-uploading or duplicating storage.
- Preserve the existing file-extension allow-list and authenticated download behaviour.
- Add standalone filtering and direct file management/removal.
- No database migration required.

## v0.5.0 — BOM and inventory allocation

Current major milestone / in progress.

- First-class bill of materials inside each project.
- BOM lines can reference board catalogue records, component catalogue records or custom materials.
- Track required quantity, unit, optional unit cost and estimated BOM cost.
- Allocate physical inventory with explicit quantities instead of mutating the stock total.
- Support partial allocations and allocation from multiple stock records.
- Track required, allocated and remaining quantities per BOM line.
- Show total, allocated and free quantities in Inventory.
- Preserve allocation/release events in inventory lifecycle history.
- Prevent concurrent over-allocation with transactional row locking.
- Protect allocated stock from incompatible project/status/quantity changes and deletion.
- Migrate any legacy direct BOM inventory links to allocation records.

## After v0.5.0

The next milestone should be selected after v0.5.0 is exercised in real projects. Existing candidate areas include the dedicated 3D-printing/model workflow, richer file previews and further inventory/BOM refinements; no version number is assigned yet.
