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
MAKERVAULT_IMAGE=ghcr.io/gavrd7/makervault:1.0.0
```

## Build-it-yourself update

If your installation intentionally builds MakerVault locally, update the checkout and rebuild with the override file:

```bash
git status --short
git rev-parse HEAD
git fetch --prune origin
git switch main
git pull --ff-only origin main
sudo docker compose -f compose.yaml -f compose.build.yaml up -d --build
sudo docker compose -f compose.yaml -f compose.build.yaml ps
sudo docker compose -f compose.yaml -f compose.build.yaml logs --tail=100 makervault
sudo docker compose -f compose.yaml -f compose.build.yaml exec -T makervault python manage.py v1_release_preflight
```

If `git status --short` shows your own changes, stop before switching/pulling and preserve them. Do not use a hard reset to discard unknown local work.

## Switching between GHCR and local builds

Both routes use the same service names and persistent storage. You can therefore switch image source without migrating your data.

To switch from a local build to the published image:

```bash
sudo docker compose pull makervault
sudo docker compose up -d makervault
```

To switch back to a source build:

```bash
sudo docker compose -f compose.yaml -f compose.build.yaml up -d --build makervault
```

A database migration is not guaranteed to be reversible simply by switching to an older application image. Back up before changing versions.

## Check the result

The `v1_release_preflight` command performs a read-only deployment check for the database, migrations, Redis, encryption key, media/backup storage and production configuration.

Sign in, confirm the version, open a project, download a private file and inspect integrations.

`docker compose restart` does not pull a new image, rebuild source or reload changed environment settings.

## If an update fails

Read the application logs first. Preserve the original backup and avoid repeated destructive experiments. If you need to return to an earlier version, restore the matching database, files, key and configuration with that earlier application version on a clean target. Older code may not understand an upgraded database.
