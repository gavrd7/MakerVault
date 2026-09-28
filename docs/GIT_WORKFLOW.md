# MakerVault Git workflow

MakerVault is designed to live in a Git repository. The recommended workflow is intentionally simple:

- `main` contains the deployable version.
- Use a short-lived feature branch for substantial work, e.g. `feature/espboards-importer`.
- Open a pull request for review/CI and merge completed work back to `main`.
- Delete merged feature branches so the branch list reflects active work.
- Tag notable stable releases (for example `v0.6.3`).
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

GitHub, GitLab, Forgejo and Gitea all work; MakerVault has no runtime dependency on a particular Git host.

## Updating a deployment

For a normal source update, explicitly return the deployment checkout to `main`:

```bash
git fetch --prune origin
git switch main
git pull --ff-only origin main
docker compose up -d --build
```

or use:

```bash
make update
```

PostgreSQL, Redis and media live in persistent storage and are not removed by an application rebuild.

Docker's layer cache means dependency-install layers are reused unless `requirements.txt`, `frontend/package.json`, the Dockerfile, or another earlier build layer changes.

## Smaller changes

For backend or frontend source-only changes, use:

```bash
docker compose up -d --build --no-deps makervault
```

The build still runs because the production image intentionally contains its application code and compiled frontend rather than bind-mounting mutable source. With cached Python and Node dependency layers this is normally much faster than a clean rebuild.

Production should remain image-based so deployments are reproducible.

## Feature branches

Example:

```bash
git switch main
git pull --ff-only origin main
git switch -c feature/example-change

# Work, test and commit.
git add .
git commit -m "Add example change"
git push -u origin feature/example-change
```

After CI/review and the pull request has been merged:

```bash
git switch main
git pull --ff-only origin main
git branch -d feature/example-change
git push origin --delete feature/example-change
git fetch --prune origin
```

For non-fast-forward work, use a normal reviewed merge or rebase rather than forcing `main`.
