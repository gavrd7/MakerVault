# Catalogue Enrichment 2.0 — release acceptance audit

Tracks [#83](https://github.com/gavrd7/MakerVault/issues/83) and [#85](https://github.com/gavrd7/MakerVault/issues/85).

This is a **verification checklist**, not an assertion that these requirements are complete. Run against an isolated fresh database; do **not** reset production storage.

| Acceptance criterion | Existing evidence | Remaining verification |
| --- | --- | --- |
| Idempotent fresh board/component seed | `seed_catalogue`, starter definitions; new `test_catalogue_acceptance` | Validate expected counts and startup background task execution on fresh Debian deployment |
| >80 board/component/filament continuation | Unit tests for batch cursors, PostgreSQL checkpoints, task continuations | Capture one full automatic cycle including worker restart |
| Retain user-entered values | Existing per-domain tests; new repeat-seed test | Test production-like upgrade data snapshot in isolated backup restore |
| Non-ESP and vendor component enrichment | Curated board profiles, limited exact manufacturer chip references | Mocked authoritative **multi-vendor online** enrichment not yet demonstrated |
| Filament upstream fetch efficiency | Deterministic product cursors | Confirm upstream fetched once per sweep rather than once per 80-row batch |
| Printer partial failure recovery | Bounded retry unit tests | Verify incomplete OrcaSlicer vendor manifests resume or are retried without redoing successful providers |
| Image fairness/restart recovery | Kind priority rotation and aggregate diagnostics | Confirm within-kind cursor restart, no starvation for individual records, and correct missing-image reason reporting |
| Provider failures vs no trusted source vs N/A | Image failure classification and board field statuses | Confirm cross-domain per-item reason, last attempt and next retry reporting |
| Background 24-hour maintenance | Scheduling and asynchronous continuation tasks | Verify due/last-run timestamps and **all** queues complete automatically |
| Release safety | Unit tests and manual Debian test server | CI, migrations, fresh startup, before/after coverage, backup/restore, docs and version/tag checks |

## Repeatable offline validation

Run on the isolated Debian test container (using the usual two Compose files):

```bash
python manage.py test core.tests.test_catalogue_acceptance core.tests.test_catalogue_seed core.tests.test_catalogue_enrichment core.tests.test_component_catalogue core.tests.test_filament_catalogue_enrichment core.tests.test_orcaslicer_catalogue core.tests.test_catalogue_image_sources --keepdb -v 2
python manage.py migrate --check
python manage.py catalogue_coverage --json
```

The new acceptance tests seed the **real** board/component definitions into an isolated test database, run the seed twice, verify counts and protect manually edited descriptions/specification keys. They do **not** prove live third-party enrichment, automatic startup orchestration, or full acceptance for #83/#85.

## Remaining manual test evidence to collect

1. On a disposable fresh-install environment, record starting `catalogue_coverage --json` and maintenance settings. Trigger or wait for the normal automatic scheduled cycle (avoid manual per-domain commands); capture task completion and before/after coverage.
2. Restart the worker/container between bounded batches and check that jobs resume using persisted checkpoints and do not duplicate records.
3. Simulate temporary upstream outage and unavailable official image independently; confirm bounded retry, accurate outcome classification, and no overwritten user data.
4. Check printer and filament upstream request counts (full downloads should not recur for every batch).
5. Compare images for incorrect product matches and count actual photos separately from generic illustrations.

Only close #83 and #85 when verified evidence satisfies their stated acceptance criteria, or explicitly split and retain unresolved acceptance items.
