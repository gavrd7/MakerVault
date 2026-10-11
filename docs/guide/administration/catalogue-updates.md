# Catalogue updates

**Goal:** keep reference data and images fresh without daily manual work.

1. Open **Settings → Library updates** as an administrator.
2. Review whether automatic maintenance is enabled.
3. Choose the interval; the default is **24 hours**.
4. Select the available board/component, printer, filament and image checks you want.
5. Choose **Save schedule**.
6. Use **Run now** for an immediate queued check and review the last/next run information.

The schedule is stored in PostgreSQL and survives container rebuilds. Background workers perform the work, so queueing a run is not the same as completing it. External sources, retry intervals and per-run limits affect how quickly gaps are filled.

Printer catalogue maintenance uses OrcaSlicer for broad profile-backed coverage and merges MakerVault supplemental FDM/FFF entries for known printers that Orca omits. Supplemental records never remove local models and do not imply live-monitoring support.

Enrichment is designed to preserve populated information rather than overwrite edits just because another source supplies a value. Filament maintenance can refresh missing catalogue fields and consult authoritative manufacturer product/TDS data for values such as density, nozzle/bed temperatures and drying guidance. The filament catalogue combines SpoolmanDB with verified supplemental records for gaps; provenance is retained so the source remains visible. Unsupported models, intentionally unmatched filaments or unavailable reliable sources can remain incomplete indefinitely.

## Server-level controls

`.env` contains master switches such as `ENRICH_BOARD_CATALOGUE` and `SEED_CATALOGUE_IMAGES`. A UI schedule cannot override a server-level hard disable. Check those values if a category never runs.

If nothing runs, inspect the application logs and container health. Celery worker and Beat run inside the application container in this deployment; you do not need to create separate worker services for the standard Compose setup.

[Troubleshooting →](../reference/troubleshooting.md)


## Review reusable spool catalogue suggestions (v1.2.0 candidate)

In **3D Printing → Reusable spools → Browse manufacturer catalogue**, administrators with catalogue-edit permissions can open **Review Suggestions**, next to **Suggest New Model**. The review modal lists pending new designs and corrections, their proposed fields and source links. Review evidence and then choose **Approve** or **Reject**. Resolved suggestions disappear from the pending queue but retain a record in the database.

Administrator-authored additions/corrections are automatically approved when submitted; ordinary editors' submissions are queued. This is a workflow approval, **not independent technical verification**. New records remain unverified and a suggested dryer temperature must include source evidence for the exact design. A source page being reachable does not establish correctness of a specification.

Reusable spool catalogue source checks and conservative image discovery are separate from review. They cannot fill every missing specification or identify every suitable image. General online product search and automatic extraction of spool dimensions are future enhancements, not features of this version.
