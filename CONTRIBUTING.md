# Contributing to MakerVault

Thanks for helping improve MakerVault.

MakerVault is a self-hosted workshop management application for electronics inventory, projects, files and 3D printing. Contributions are welcome for bug fixes, documentation, accessibility, integrations, tests and carefully scoped new features.

## Before you start

Please:

1. Check the existing issues and pull requests for similar work.
2. For non-trivial features, open a feature request first so the scope can be discussed before implementation.
3. Do not include credentials, API keys, private IP addresses, personal data, backups, database dumps or other sensitive deployment data in issues, pull requests, screenshots or logs.
4. Keep experimental hardware support clearly labelled when representative hardware has not been validated.

Security vulnerabilities should **not** be reported in a public issue. See [SECURITY.md](SECURITY.md).

## Development workflow

The deployable branch is `main`.

Create a topic branch from current `main`, make focused changes, test them, and open a pull request back to `main`.

Example:

```bash
git fetch origin
git switch main
git pull --ff-only origin main
git switch -c fix/short-description
```

Keep commits focused and use descriptive messages.

## Running MakerVault locally

The supported deployment path uses Docker Engine and Docker Compose. See the [installation guide](https://gavrd7.github.io/MakerVault-docs/) for the full setup.

For a development checkout:

```bash
cp .env.example .env
sudo docker compose up -d --build
```

Never commit your real `.env`.

## What to test

Run the checks relevant to your change before opening a pull request.

At minimum, confirm that the changed feature works as expected and that you have not broken adjacent behaviour.

MakerVault CI covers backend tests, frontend tests/build, migrations, security checks, the production image and documentation checks where applicable.

For hardware-facing changes, describe exactly what was tested and on which hardware. If you could not validate on real hardware, say so clearly.

## Pull requests

A useful pull request should:

- explain what changed and why;
- link the related issue when there is one;
- describe how the change was tested;
- call out migrations, configuration changes or upgrade considerations;
- include sanitised screenshots for visible UI changes when useful;
- preserve ownership/privacy boundaries;
- update documentation when user-facing behaviour changes.

Please avoid unrelated refactors in the same PR.

## Documentation

The published guide lives at:

https://gavrd7.github.io/MakerVault-docs/

Guide source is maintained separately at:

https://github.com/gavrd7/MakerVault-docs

Small bundled documentation changes may exist in this repository too, but the public guide should remain aligned.

## Coding and project conventions

Prefer existing project patterns over introducing new frameworks or dependencies without a clear need.

When changing data models, include and test the required migration.

When changing integrations, do not imply broader manufacturer/model support than has actually been implemented or validated.

When handling private files, authentication, backups or account data, preserve the existing security and owner-isolation model.

## Reporting bugs and requesting features

Use the repository's structured issue forms so the report includes enough context to investigate.

For setup/help questions, see [SUPPORT.md](SUPPORT.md).
