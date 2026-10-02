# About this guide

## Version and scope

This guide describes **MakerVault v0.9.0.2**. Its overview and integration status were reconciled on **2 October 2026** with merged source commit `a4c12274b645ebb7f568f7b19b4d1e467d51c222`. It describes implemented features, not a completed v1 release or proof of every deployment/hardware scenario.

The primary deployment route is Linux with the supplied Docker Compose configuration. Platform-specific NAS/Portainer and Windows/macOS installation walkthroughs are outside this edition's verified scope. No measured minimum hardware specification is claimed.

## Verification

Content was checked against the source README, environment example, Compose/entrypoint, authentication settings, role setup and frontend workflows. Documentation build/link checks verify presentation and internal references; they do not replace a clean-server installation, backup/restore rehearsal or hardware/provider integration test.

The Nginx configuration is a same-host example, and OIDC uses provider-neutral instructions. Neither is a claim that a specific user's domain, certificate or identity provider has been configured or tested.

## Keep it current

Chapters are Markdown files under `docs/guide`. Navigation and theme live in `mkdocs.yml`. The maintainer workflow is described in `docs/GUIDE_MAINTENANCE.md` in the repository. Update the affected chapter with each feature change, then check the guide version and release checklist.

K1/K2 monitoring and camera playback have owner confirmation, including acceptance of the compact camera layout. Other hardware and route/lifecycle checks remain tracked separately. Before v1, complete clean-install, restore and upgrade rehearsals, capture sanitised screenshots, and publish accurate integration support boundaries. Screenshots should complement complete written steps so a small UI change does not make the manual unusable.

## Sources

- [MakerVault repository](https://github.com/gavrd7/MakerVault)
- [Docker Engine installation](https://docs.docker.com/engine/install/)
- [Docker Compose](https://docs.docker.com/compose/)
- [GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)
- [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)
- [Nginx HTTPS configuration](https://nginx.org/en/docs/http/configuring_https_servers.html)

Repository software is AGPL-3.0-or-later. Third-party media keeps its original licence/provenance; application media attribution is available in **About**.
