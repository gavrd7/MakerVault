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

Completed and merged to `main` on 27 September 2026.

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

## v0.6.0 — 3D Printing & Model Library

Next major milestone.

MakerVault expands its existing project/file/inventory foundation into a first-class 3D-printing workspace while reusing the same stored files rather than creating a parallel asset system.

Planned scope:

- First-class 3D model records with name, description, tags, source/reference URL and optional project association.
- Model revisions so design iterations can be tracked without losing earlier files or notes.
- Attach existing MakerVault STL, 3MF, OBJ and supported CAD assets to models without duplicating storage.
- Add richer model/file previews, beginning with interactive STL/3MF viewing where practical.
- First-class printer records for the machines available to MakerVault.
- Filament/spool inventory with material, colour, diameter, supplier, purchase data and remaining quantity.
- Optional Spoolman integration using its REST API, with configurable one-way or bidirectional spool inventory synchronisation and explicit conflict/source-of-truth handling.
- Optional SimplyPrint filament integration where API access is available, with import/export compatibility retained for installations without API access.
- Creality CFS discovery for supported printers: query local printer/CFS state to show which filament is currently loaded in each slot, including material, colour, remaining amount and RFID identity when exposed by the printer.
- Allow discovered CFS slots/RFID identities to be matched to MakerVault spool records and, where configured, to corresponding Spoolman/SimplyPrint records.
- Treat Creality CFS integration as capability-detected and read-only first; do not depend on undocumented write/control behaviour or RFID programming for the core workflow.
- Print history linking a model revision, printer and consumed spool(s), including quantity, duration, outcome and notes.
- Surface model/print information naturally inside Projects and the global Files library rather than creating isolated silos.
- Preserve MakerVault permissions, authenticated file delivery and existing file-extension/security rules.

Initial scope deliberately excludes live printer control, slicer automation, RFID tag writing/programming and broad OctoPrint/Moonraker-style telemetry control. External filament integrations should degrade gracefully when unavailable, and MakerVault must remain usable as a standalone source of truth.

## After v0.6.0

Candidate follow-on areas include deeper inventory/BOM refinements, richer previews for additional engineering file types, print-cost estimation, and optional printer/slicer integrations. No later version number is assigned yet.
