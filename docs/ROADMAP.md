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

Current milestone / in progress.

- Upload supported MakerVault file types directly from the Files page without requiring a project.
- Keep standalone and project-linked files in the same FileAsset library.
- Allow optional project assignment at upload time.
- Allow an existing file to move between standalone and project-linked use without re-uploading or duplicating storage.
- Preserve the existing file-extension allow-list and authenticated download behaviour.
- Add standalone filtering and direct file management/removal.
- No database migration required.

## After v0.4.3 — BOM and inventory allocation

Next project-workspace milestone after the standalone file-library refinement.

- Bill of materials management.
- Link BOM lines to catalogue records and/or physical inventory.
- Track required versus assigned/available quantities.
- Make project inventory consumption/allocation clearer without losing lifecycle history.

Milestone numbering beyond v0.4.3 should be assigned when that work begins, rather than inferred from older roadmap text.
