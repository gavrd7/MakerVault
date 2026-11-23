# Update MakerVault

**Goal:** move to the current deployable release while keeping a recoverable copy of your data.

MakerVault can be updated either by pulling the published GHCR image or by rebuilding from source. Use the same route you chose for installation unless you deliberately want to switch.

1. Read the release notes/CHANGELOG for changes since your installed version.
2. If upgrading from before v0.7, read [the migration chapter](../advanced/legacy-upgrade.md) first.
3. Make and verify a [complete backup](backup.md), including media and keys.
4. Keep your existing `.env`; never overwrite it with `.env.example`.

## Recommended: update the pre-built GHCR image

From your MakerVault checkout:

```bash
git status --short
git rev-parse HEAD
git fetch --prune origin
git switch main
git pull --ff-only origin main
sudo docker compose pull
sudo docker compose up -d
sudo docker compose ps
sudo docker compose logs --tail=100 makervault
sudo docker compose exec -T makervault python manage.py v1_release_preflight
```

`docker compose pull` downloads the current MakerVault image and any newer PostgreSQL/Redis image allowed by the Compose file. `docker compose up -d` then recreates only what needs changing.

If you pin `MAKERVAULT_IMAGE` in `.env`, change that value to the release you intend to run before pulling. For example:

```dotenv
MAKERVAULT_IMAGE=ghcr.io/gavrd7/makervault:1.7.0
```

## Update using one Compose file

The checkout always uses **`compose.yaml`**. Keep your existing private `.env` and storage. For ordinary published-image upgrades, the commands above are sufficient.

For an intentional **source build**, retain `MAKERVAULT_IMAGE=makervault-local:dev` in your environment, update the checkout as above and rebuild only the app:

```bash
sudo docker compose build makervault
sudo docker compose up -d
sudo docker compose ps
```

For an installation that already uses the verified combined slicer, include the same **`slicer` profile** at each update. Keep the immutable slicer-worker image, native engine store and imported profiles unchanged unless you explicitly choose an approved version update:

```bash
sudo docker compose --profile slicer config --quiet
sudo docker compose --profile slicer pull makervault postgres redis
sudo docker compose --profile slicer up -d
sudo docker compose --profile slicer ps
```

If running a local source build with the slicer profile, run `sudo docker compose build makervault` before `sudo docker compose --profile slicer up -d`. Rebuild the slicer worker separately and deliberately only when needed. The combined container runs the worker and installer on separate UIDs, and the one-shot permission helper is not a fifth running daemon.

**Migration from previous overlays:** the old `compose.build.yaml`, `compose.slicer.yaml` and `compose.slicer.staging.yaml` files have been retired. Before using the single Compose stack on an existing development/staging host, inspect the current engine image ID, private `.slicer-staging.env`, `.env`, named volumes and any local custom Compose file. Preserve the full environment and volume data, then map relevant settings into the private `.env` and validate `docker compose --profile slicer config --quiet`. Do not blindly run old multi-file commands after updating source. No automatic migration or database reset is required, and do not delete the legacy container, its image or any volume before verification.

**Never run `docker compose down -v`** as an upgrade step: it may delete the database, private media encryption keys, backups and installed slicer engines. Backup and independently verify recovery first.

## Check the result

The `v1_release_preflight` command performs a read-only deployment check for the database, migrations, Redis, encryption key, media/backup storage and production configuration.

Sign in, confirm the version, open a project, download a private file and inspect integrations.

`docker compose restart` does not pull a new image, rebuild source or reload changed environment settings.

## If an update fails

Read the application logs first. Preserve the original backup and avoid repeated destructive experiments. If you need to return to an earlier version, restore the matching database, files, key and configuration with that earlier application version on a clean target. Older code may not understand an upgraded database.
