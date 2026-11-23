# Update MakerVault

**Goal:** move to the current deployable release while keeping a recoverable copy of your data.

MakerVault updates use published GHCR images and the single repository `docker-compose.yml`.

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

## Updating the four-container stack

The published images are downloaded from GHCR using **one `docker-compose.yml`**. MakerVault, its slicer, PostgreSQL and Redis are managed together; there are no profiles, extra Compose files or locally built production images.

```bash
sudo docker compose config --quiet
sudo docker compose pull
sudo docker compose up -d
sudo docker compose ps
```

Installed native slicer engines and their registry live in a separate persistent Docker volume. Updating the MakerVault and combined slicer images does not by itself authorise changing the versions of those native engines; use the application engine manager for explicit changes.

**Upgrading an older multi-file staging deployment:** first back up the complete installation, inspect existing custom files and private `.slicer-staging.env`, and preserve existing image identities and the named engine volume. Map relevant settings into the private `.env` before using the one-file configuration. Do **not** delete legacy containers or volumes until the new deployment has been checked and engine installations have been verified. Consult the dedicated [slicer guide](../3d-printing/slicer.md).

Never use `docker compose down -v` for upgrades; it can delete persistent database, media, keys and native engine storage.

## Check the result

The `v1_release_preflight` command performs a read-only deployment check for the database, migrations, Redis, encryption key, media/backup storage and production configuration.

Sign in, confirm the version, open a project, download a private file and inspect integrations.

`docker compose restart` does not pull a new image, rebuild source or reload changed environment settings.

## If an update fails

Read the application logs first. Preserve the original backup and avoid repeated destructive experiments. If you need to return to an earlier version, restore the matching database, files, key and configuration with that earlier application version on a clean target. Older code may not understand an upgraded database.
