# Controlled migration: reviewed Orca staging worker → generic MakerVault Slicer 0.1.0

This is a **staging-only, explicit host action**. Do not run in production.
The published immutable image has already passed isolated HTTP health and real
Orca G-code tests. This migration is the first integration of that image
into the existing MakerVault staging Compose services.

## Safety prerequisites

- Confirm there are **no queued or running slices**. Finish or cancel jobs
  in the MakerVault UI; the installer must not interrupt a running slice.
- Leave the existing worker image, `slicer-engine-assets`, any
  `.slicer-staging.env.pre-upgrade` backups, and application volumes intact.
- No `docker compose down -v`, `docker system prune`, or removal of legacy
  images during this migration.
- Ensure Docker can pull GHCR; allow sufficient storage for both images and
  the volume's copied Orca AppImage and extracted runtime.
- The generic engine image is Linux **AMD64** only.

## Run on Debian staging

```bash
cd ~/MakerVault-Staging
git pull origin feature/self-hosted-slicer-foundation

# Offline contract tests, then non-mutating migration preflight:
python3 -m unittest scripts.tests.test_migrate_generic_slicer_staging -v
sudo python3 scripts/migrate_generic_slicer_staging.py preflight

# ONLY once all slicing jobs are idle:
sudo python3 scripts/migrate_generic_slicer_staging.py migrate

# Confirm app/worker services and the approved engine:
sudo python3 scripts/install_slicer_staging.py status
```

The **preflight** checks the old private configuration, original pinned local
Docker image, reviewed Orca binary digest and staging Compose configuration.
The **migrate** operation:

1. Pulls exactly
   `ghcr.io/gavrd7/makervault-slicer@sha256:3071c79f10ed50e8ecc9a1e6f576be8aa402ca6067682315cf1ed44a4fa45cce`.
2. Prepares the single named engine volume
   `makervault_makervault_slicer_engines`. A temporary Docker maintenance
   container copies the already approved Orca 2.5.0 AppImage and derived
   runtime to `versions/orcaslicer/2.5.0`, then writes the active manifest.
   This container exits; it is **not** an additional running slicer worker.
3. Checks the volume in a separate **read-only**, unprivileged container.
4. Saves the original private staging config to
   `.slicer-staging.env.pre-generic` (mode 0600), without touching previous
   backups. The original Docker image remains locally installed.
5. Updates the pinned image identity but retains the worker token and exact
   accepted Orca binary SHA-256.
6. Recreates **only** the existing `slicer-worker` and `makervault`
   Compose services, checks worker health and automatically attempts to
   restore the old image/configuration if that fails.

The migration does not modify PostgreSQL, Redis, media or models, and never
submits a print. **Docker-level health is not yet proof of an end-to-end
MakerVault slicing job.** Open the existing slicer UI, confirm OrcaSlicer
2.5.0 is available, and slice a small single-filament Benchy to verify
application integration.

## Rollback

Stop/finish slicing jobs, then:

```bash
cd ~/MakerVault-Staging
sudo python3 scripts/migrate_generic_slicer_staging.py rollback
sudo python3 scripts/install_slicer_staging.py status
```

This restores the original private image approvals and recreates the same
two services from the original local image. The persistent engine volume is
preserved for investigation. It **does not delete** previous executable or
application data. Do not modify or remove the backup file before rollback.

## Troubleshooting and release scope

- A refused migration means its fail-closed precondition has not been met.
  Resolve the reported state; do not bypass immutable checks.
- A healthy worker that is unavailable in MakerVault may indicate an
  application/worker identity or transport mismatch. Preserve logs and
  restore the previous image.
- This does **not** implement in-app updates. Engine management remains
  read-only/informational until a restricted host-side updater and explicit
  authorisation process are implemented.
- No other engine is enabled or installed by this migration. Orca 2.5.0 is the
  one verified engine initially activated in the shared worker.
