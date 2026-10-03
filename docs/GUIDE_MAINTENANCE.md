# Maintaining and publishing the user guide

The user guide documents the current release. It uses Markdown under `docs/guide`, Material for MkDocs and a separate `mkdocs.yml`. Existing engineering notes under `docs/` are not included in the public build. No application settings, volumes or runtime services are changed.

## Local preview and validation

From the repository root, use Python 3.12 or newer in a dedicated virtual environment:

```bash
python3 -m venv /tmp/makervault-docs-venv
. /tmp/makervault-docs-venv/bin/activate
python -m pip install -r docs/requirements.txt
python -m mkdocs build --strict
python scripts/check_guide_links.py
python -m mkdocs serve
```

Open the local address printed by MkDocs (normally `http://127.0.0.1:8000`). Dependencies are independent of the application requirements. Top-level theme/build versions are pinned; review dependency updates deliberately. Do not commit `site/` or the virtual environment.

## Publishing with GitHub Pages

GitHub Pages is appropriate for a static manual; it does not run MakerVault itself. MakerVault's application source and public documentation are both intended to be publicly accessible, with the documentation published separately through `MakerVault-docs`.

The included `guide.yml` workflow builds documentation for documentation PRs/main changes and uploads a preview artifact. Deployment happens only when explicitly run with `publish=true` from `main`. It does not automatically publish on merge.

1. Review and merge the documentation PR.
2. In repository **Settings → Pages**, choose **GitHub Actions** as the build source (if the account/repository supports it).
3. Review the `github-pages` environment's deployment protection rules and intended public content.
4. Open **Actions → MakerVault user guide → Run workflow**, choose `main`, and enable **Publish to GitHub Pages**.
5. Open the URL reported by the deploy job. For this repository the expected project-site URL is `https://gavrd7.github.io/MakerVault/` unless Pages/custom-domain settings change it.
6. Test navigation, search, code copying and a narrow/mobile viewport on the published site.

MakerVault uses the separate public `gavrd7/MakerVault-docs` repository for the published guide. Keep source/build assets, `repo_url`, `edit_uri` and `site_url` aligned with that repository when updating the documentation.

Official reference: https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages

## Edit a chapter

1. Use a short-lived documentation branch.
2. Update the Markdown chapter alongside a feature change. Preserve stable filenames/anchors where possible.
3. Add a navigation entry in `mkdocs.yml` for a new chapter.
4. Run the strict build and link checker.
5. Preview the page, check mobile layout and update the source/version note when revalidating an edition.
6. Open a PR. Publish the reviewed edition through the manual workflow.

For a task page, use: goal; prerequisites/permissions; numbered procedure; expected result; common failures; relevant next link. Keep beginner paths concrete. Place optional infrastructure complexity in Advanced features. Do not describe planned adapters as available.

## Source map for reviewers

| Guide subject | Implementation to check |
| --- | --- |
| Install, storage, backup paths | `compose.yaml`, `.env.example`, `docker/entrypoint.sh` |
| Authentication/OIDC/email | `backend/makervault/settings.py`, account/provider forms/templates |
| Roles | `backend/core/management/commands/seed_roles.py` |
| Quotas/private ownership | `backend/core/storage_usage.py`, `user_admin.py`, API ownership checks |
| Catalogue/inventory/projects/files | Corresponding frontend page and backend API handlers |
| Printing and integrations | `PrintingPage.jsx`, `SettingsPage.jsx`, provider sync modules |
| Model intelligence | Model-analysis code and `ModelViewer.jsx` |

## Before v1 publication

- Revalidate every chapter against the release commit; update the edition notice and footer.
- Run a clean beginner install, a second-user permission check and a complete restore on a separate host.
- Check backup commands using both named volumes and bind mounts, including custom key-source handling.
- Confirm supported hardware/platforms; document tested baselines rather than inventing minimum specifications.
- Test enabled integration directions with representative services/hardware and record limitations.
- Verify proxy/OIDC instructions with the chosen supported example providers.
- Add sanitised screenshots for initial setup, inventory, BOM allocation, versions, printing and account storage. Use consistent viewport/data, descriptive alt text and no credentials.
- Decide whether to archive pre-v1 docs or introduce versioned documentation; avoid multiple divergent copies before needed.
- Verify published Pages URLs, search and accessibility. Never publish `.env`, backups or real users' private screenshots.

The initial edition is source-reviewed and build-validated; live deployment and hardware integration acceptance remain separate checks. Record completed acceptance evidence in release notes rather than implying the documentation build exercised the application.
