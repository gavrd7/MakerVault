# About this guide

## Version and scope

This guide describes **MakerVault v1.0.0**, the first stable release. The release was accepted on **3 October 2026** after representative off-server recovery, a fresh Debian/Docker installation, restart/persistence checks, native HTTPS/Local CA validation and final green CI. Experimental hardware integrations retain explicit validation boundaries.

The primary deployment route is Linux with the supplied Docker Compose configuration. Platform-specific NAS/Portainer and Windows/macOS installation walkthroughs are outside this edition's verified scope. No measured minimum hardware specification is claimed.

## Verification

Content was checked against the source README, environment example, Compose/entrypoint, authentication settings, role setup, storage/recovery implementation and frontend workflows. Documentation build/link checks verify presentation and internal references. The v1 release also completed clean-server installation and representative off-server backup/restore acceptance; hardware/provider testing remains separate for adapters explicitly marked experimental.

The Nginx configuration is a same-host example, and OIDC uses provider-neutral instructions. Neither is a claim that a specific user's domain, certificate or identity provider has been configured or tested.

## Keep it current

Chapters are Markdown files under `docs/guide`. Navigation and theme live in `mkdocs.yml`. The maintainer workflow is described in `docs/GUIDE_MAINTENANCE.md` in the repository. Update the affected chapter with each feature change, then check the guide version and release checklist.

K1/K2 monitoring and camera playback have owner confirmation, including acceptance of the compact camera layout. Other hardware and route/lifecycle checks remain tracked separately, particularly for experimental printer adapters. Screenshots should complement complete written steps so a small UI change does not make the manual unusable.

## Sources

- [MakerVault repository](https://github.com/gavrd7/MakerVault)
- [Docker Engine installation](https://docs.docker.com/engine/install/)
- [Docker Compose](https://docs.docker.com/compose/)
- [GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)
- [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)
- [Nginx HTTPS configuration](https://nginx.org/en/docs/http/configuring_https_servers.html)

Repository software is AGPL-3.0-or-later. Third-party media keeps its original licence/provenance; application media attribution is available in **About**.
