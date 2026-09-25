# Changelog

## v0.1.1

- Made the published MakerVault HTTP port explicitly configurable with `MAKERVAULT_PORT`.
- Changed the example/default host port from `8000` to `8765` to reduce conflicts with common self-hosted services.
- Kept the container-internal Gunicorn port at `8000`; only the host-side published port changes.
- Added Git repository guidance and line-ending attributes.
- Added `make rebuild-app` to rebuild/recreate only the MakerVault application service.
- Added `make update` for a fast-forward Git pull followed by an application-only rebuild.

## v0.1.0

- Initial MakerVault Docker/Django/PostgreSQL/Redis foundation.
