# MakerVault Git workflow

MakerVault is designed to live in a Git repository. The recommended workflow is intentionally simple:

- `main` contains the deployable version.
- Use a short-lived feature branch for substantial work, e.g. `feature/espboards-importer`.
- Merge completed work back to `main`.
- Tag notable releases (`v0.1.1`, `v0.2.0`, etc.).
- Never commit `.env`, uploaded media, database data, Redis data, secrets, or local build output.

## Initial repository setup

From the MakerVault project directory:

```bash
git init -b main
git add .
git commit -m "Initial MakerVault import"
```

Then create an empty private repository on your preferred Git host and add it as `origin`:

```bash
git remote add origin <YOUR-REPOSITORY-URL>
git push -u origin main
```

GitHub, GitLab, Forgejo and Gitea all work; MakerVault has no dependency on a particular Git host.

## Updating a deployment

For a normal source update:

```bash
git pull --ff-only
docker compose up -d --build --no-deps makervault
```

or use:

```bash
make update
```

This rebuilds/recreates only the MakerVault application container. PostgreSQL and Redis are not rebuilt or recreated and their persistent storage remains untouched.

Docker's layer cache also means dependency-install layers are reused unless `requirements.txt`, `frontend/package.json`, the Dockerfile, or another earlier build layer changes.

## Smaller changes

For backend or frontend source-only changes, use:

```bash
docker compose up -d --build --no-deps makervault
```

The build still runs, because the production image intentionally contains its application code and compiled frontend rather than bind-mounting mutable source. With cached Python and Node dependency layers this is normally much faster than a clean rebuild.

We may add a dedicated hot-reload development override later if live editing on the server becomes useful. Production should remain image-based so deployments are reproducible.

## Feature branches

Example:

```bash
git switch -c feature/spoolmandb-import
git add .
git commit -m "Add SpoolmanDB catalogue importer"
git switch main
git merge --ff-only feature/spoolmandb-import
git tag v0.2.0
git push origin main --tags
```

For non-fast-forward work, use a normal reviewed merge or rebase rather than forcing `main`.
