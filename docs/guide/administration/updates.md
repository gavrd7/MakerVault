# Update MakerVault

**Goal:** move to the current deployable release while keeping a recoverable copy of your data.

1. Read the release notes/CHANGELOG for changes since your installed version.
2. If upgrading from before v0.7, read [the migration chapter](../advanced/legacy-upgrade.md) first.
3. Make and verify a [complete backup](backup.md), including media and keys.
4. Run the commands below from your source folder.

```bash
git status --short
git rev-parse HEAD
git fetch --prune origin
git switch main
git pull --ff-only origin main
sudo docker compose up -d --build
sudo docker compose ps
sudo docker compose logs --tail=100 makervault
```

If `git status --short` shows your own changes, stop before switching/pulling and preserve them. Do not use a hard reset to discard unknown local work. A failed fast-forward means the checkout needs review, not a force pull.

Startup applies migrations and catalogue maintenance/seed steps. Keep `.env`; do not replace it with the example file. Compare `.env.example` for new settings and add only the ones needed for your deployment.

## Check the result

Sign in, confirm the version, open a project, download a private file and inspect integrations. Missing records after an update may mean the wrong account or storage path was used; do not immediately initialise new data.

`docker compose restart` does not build new application code or reload changed environment settings. Use `up -d --build` for a code update, or `up -d` for normal `.env` changes.

## If an update fails

Read the application logs first. Preserve the original backup and avoid repeated destructive experiments. If you need to return to the earlier version, restore the matching database, files, key and configuration with that earlier source revision on a clean target. Older code may not understand an upgraded database.

The repository also provides `make update`, but the explicit commands above make the process easier to inspect for new operators.
