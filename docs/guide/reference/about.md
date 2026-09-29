# About this guide

## Version and scope

This is the user-guide foundation for **MakerVault v0.7.0.1**, reviewed on **29 September 2026** against source commit `59d12f81a2941178bca4e6fb1cea68f2081c60b4`. It documents current implemented features, not the entire roadmap or a completed v1 release.

The primary deployment route is Linux with the supplied Docker Compose configuration. Platform-specific NAS/Portainer and Windows/macOS installation walkthroughs are outside this edition's verified scope. No measured minimum hardware specification is claimed.

## Verification

Content was checked against the source README, environment example, Compose/entrypoint, authentication settings, role setup and frontend workflows. Documentation build/link checks verify presentation and internal references; they do not replace a clean-server installation, backup/restore rehearsal or hardware/provider integration test.

The Nginx configuration is a same-host example, and OIDC uses provider-neutral instructions. Neither is a claim that a specific user's domain, certificate or identity provider has been configured or tested.

## Keep it current

Chapters are Markdown files under `docs/guide`. Navigation and theme live in `mkdocs.yml`. The maintainer workflow is described in `docs/GUIDE_MAINTENANCE.md` in the repository. Update the affected chapter with each feature change, then check the guide version and release checklist.

Before v1, complete a clean installation and restore rehearsal on supported targets, capture sanitised screenshots from the release UI, and check each integration with supported hardware/accounts. Screenshots should complement complete written steps so a small UI change does not make the manual unusable.

## Sources

- [MakerVault repository](https://github.com/gavrd7/MakerVault)
- [Docker Engine installation](https://docs.docker.com/engine/install/)
- [Docker Compose](https://docs.docker.com/compose/)
- [GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)
- [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)
- [Nginx HTTPS configuration](https://nginx.org/en/docs/http/configuring_https_servers.html)

Repository software is AGPL-3.0-or-later. Third-party media keeps its original licence/provenance; application media attribution is available in **About**.
