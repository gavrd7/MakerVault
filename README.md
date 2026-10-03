# MakerVault

**Your workshop, organised.**

MakerVault is a self-hosted application for electronics inventory, projects, files and 3D printing. Keep track of what you own, what a build needs, which revision you printed and where the finished parts belong.

**Release candidate: v1.0.0-rc.1 · Final gate: clean-install smoke test**

[User guide](docs/guide/index.md) · [Installation](docs/guide/getting-started/install.md) · [Roadmap](docs/ROADMAP.md) · [Changelog](CHANGELOG.md)

## What you can do

| Workspace | Current capabilities |
| --- | --- |
| Catalogues | Boards, generic components, printers and filament products; technical specifications, images, provenance and scheduled enrichment |
| Inventory | Physical stock, generated IDs, quantities, locations, condition, purchase information, lifecycle history and available/allocated quantities |
| Projects and BOMs | Build notes, images, files, repository links, cost rollups and quantity-aware allocation from owned stock |
| Files | Standalone or project-linked assets, immutable version history, authenticated downloads and encrypted private uploads |
| Search | Universal search with filters and navigation to matching records |
| Maker Tags | QR, NFC and RFID identities, printable QR labels, record resolution and reassignment history |
| Interactive Wiring | Project or standalone diagrams with catalogue-aware pins, editable connections, basic electrical checks and JSON/SVG export |
| Models | STL/3MF viewing, thumbnails, revisions, local geometry and mesh analysis, printer-fit checks, orientation guidance and supported slicer metadata |
| 3D Printing | Owned printers, physical spools, multi-material slots, print history, material/cost analytics and optional live integrations |
| Printed parts | Explicitly retained physical part batches, project/location/state tracking, replacements and Maker Tags |

Catalogue definitions describe a product; inventory records describe the physical items you own. Personal workspaces are owner-scoped while reference catalogues are shared. Projects are not shared team folders.

The interface works on desktop, tablet and mobile. Local accounts, MFA, optional OpenID Connect, Viewer/Editor permissions and administrator storage quotas are included.

## Live printers and cameras

MakerVault works without a cloud printer account. Direct monitoring, filament synchronisation and camera configuration are separate features.

| Connection | Implemented capability and validation boundary |
| --- | --- |
| Creality local | Printer/job telemetry and compatible CFS context. K1 and K2 connection/monitoring have been owner-tested. |
| Moonraker / Klipper | Printer/job telemetry, standard numbered extruders and active-tool reporting. K1 monitoring has been owner-tested. |
| OctoPrint | Local printer/job monitoring; representative hardware validation remains open. |
| Bambu Lab local | Experimental monitoring and AMS/AMS Lite observations; hardware validation pending. |
| PrusaLink | Experimental local printer/job monitoring; hardware validation pending. |
| Anycubic LAN | Experimental Kobra 3/S1-generation monitoring and ACE observations; hardware validation pending. |
| FlashForge local | Experimental compatible local API monitoring and material-station observations; hardware validation pending. |
| Elegoo, QIDI, Sovol, Snapmaker U1 and Voron | Moonraker-based profiles for compatible firmware, not blanket support for every model from those manufacturers. |
| Spoolman / SimplyPrint | Optional inventory synchronisation or read-only service imports; SimplyPrint requires suitable account/API access. |

Pause, Resume and confirmed Cancel are available as **per-source opt-in controls** for Creality, Moonraker and OctoPrint. Monitoring success does not validate controls; hardware checks remain separate. Start print, motion, heating and raw G-code control are outside this implementation.

Configured cameras appear automatically on visible dashboard and printer cards. The last configured camera is the default; the compact viewer provides fullscreen access, while setup stays in a separate dialog. Hidden/off-screen feeds pause. **K1 and K2 playback and the compact layout have been owner-confirmed.**

HTTP snapshot/MJPEG sources provide refreshed images at approximately one frame per second. Creality WebRTC uses direct browser-to-printer media and requires LAN/VPN reachability. Discovery supports Moonraker, OctoPrint, applicable PrusaLink APIs and recognised manufacturer HTTP URLs. Native Bambu camera transport, cloud camera access, generic RTSP/HLS relaying and separate camera hosts are not implemented.

[Camera setup and limitations](docs/guide/integrations/printer-cameras.md) · [Printer controls](docs/guide/integrations/printer-controls.md) · [Hardware validation](docs/guide/integrations/printer-adapter-validation.md) · [Outstanding tests](https://github.com/gavrd7/MakerVault/issues/37)

## Filament accounting and printed parts

Print history and filament accounting do not require saving a model or retaining a printed part. **Part creation is explicit and is never automatic by default.**

MakerVault can use supported plain-G-code gram metadata and Moonraker extrusion/metadata estimates. Estimates retain their source; manual usage rows take precedence. Missing measurements remain **Not recorded**, rather than being invented from print duration or CFS percentages. Whole-file estimates count only after successful completion.

Recorded material rows can estimate cost from spool purchase data, with manual overrides and separate currency totals. Automatic job estimates do **not** deduct physical-spool inventory or invent per-spool allocation, purge/waste amounts or material cost.

[Print history and usage](docs/guide/using/print-history.md) · [Printed parts](docs/guide/using/printed-parts.md)

## Install

The supported deployment path uses Linux, Docker Engine and Docker Compose. The [step-by-step guide](docs/guide/getting-started/install.md) assumes no previous Docker experience.

```bash
git clone https://github.com/gavrd7/MakerVault.git
cd MakerVault
cp .env.example .env
chmod 600 .env
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

For a **new installation**, edit `.env` before starting:

- Set a newly generated `DJANGO_SECRET_KEY` and a separate strong `POSTGRES_PASSWORD`.
- Add your server hostname/IP to `DJANGO_ALLOWED_HOSTS` and its full URL to `DJANGO_CSRF_TRUSTED_ORIGINS`.
- Select timezone, currency and persistent storage locations.
- For direct LAN access, use `TRUST_PROXY_HEADERS=false` and `ALLAUTH_TRUSTED_PROXY_COUNT=0`.
- Keep local registration disabled unless you deliberately need it.

Repository access is required while the source repository is private. Use your normal GitHub authentication; do not embed tokens in clone URLs.

```bash
sudo docker compose config --quiet
sudo docker compose up -d --build
sudo docker compose ps
sudo docker compose exec makervault python manage.py createsuperuser
```

Open `http://SERVER-IP:8765`. The host port is configurable through `MAKERVAULT_PORT`; the container listens on port 8000. There is no universal default login.

**Existing installation?** Preserve your current `.env`, secrets and storage. Follow the [update guide](docs/guide/administration/updates.md), not the new-install steps.

[Environment settings](docs/guide/getting-started/environment.md) · [Storage choices](docs/guide/getting-started/storage.md) · [HTTPS/reverse proxy](docs/guide/advanced/reverse-proxy.md) · [OIDC](docs/guide/advanced/oidc.md)

## Deployment and data

The default Compose stack has three persistent containers:

- **makervault:** Django/Gunicorn, the compiled React frontend and Celery worker/beat.
- **postgres:** PostgreSQL application data.
- **redis:** queue/cache and background-work state.


PostgreSQL and Redis do not publish host ports by default. Managed backup creation runs inside the existing MakerVault worker; restore uses guarded one-off commands from the same MakerVault image. Application code is built into the image. Named volumes and absolute-path bind mounts are supported for media, encryption keys, PostgreSQL, Redis and managed backups.

Private uploaded files use authenticated AES-256-GCM encryption at rest with opaque object names. The default key is stored separately from media. This does not mean the database, deployment configuration or every secret is encrypted by the private-file storage feature.

**Back up the database, media, matching encryption key and deployment configuration together.** Media without its key cannot recover encrypted uploads. Superusers can create, verify, download and manage a single recovery bundle from **Settings → Backup & restore**. A guarded restore helper handles same-server recovery and downloaded bundles on a replacement host without giving the web process Docker control. Synthetic recovery is exercised in CI, and a representative real-installation backup was restored successfully on a separate clean host during the v1.0 release rehearsal.

[Backup and recovery](docs/guide/administration/backup.md) · [Accounts and quotas](docs/guide/administration/accounts.md)

## Update an existing deployment

Back up first, then run these commands from your MakerVault checkout:

```bash
git fetch --prune origin
git switch main
git pull --ff-only origin main
sudo docker compose up -d --build
sudo docker compose ps
```

Startup applies migrations and idempotent setup tasks. Read the changelog and update guide before changing versions. A database migration is not guaranteed to be reversible by simply switching to an older image.

For the existing development-server layout, the checkout is `/mnt/Server/MakerVault/app`. Other installations can use their own location.

## Reference data and background work

Administrator settings provide scheduled catalogue maintenance and manual refresh, plus separate integration synchronisation controls. Board/component data, OrcaSlicer printer profiles and SpoolmanDB filament definitions carry provenance and may have incomplete fields. Missing values are not proof that a capability is unsupported.

Catalogue media can be locally cached or retained as external references where redistribution is inappropriate. Third-party images keep their original source, licence and attribution; they are not relicensed as MakerVault software.

[Catalogue guide](docs/guide/using/catalogue.md) · [Maintenance](docs/guide/administration/catalogue-updates.md) · [Third-party notices](THIRD_PARTY_NOTICES.md)

## Project status and development

**v1.0.0-rc.1** is the first stable-release candidate. Real backup/restore recovery, upgrade preflight, security/reliability checks and the final UI/accessibility pass are complete; the remaining owner-run release gate is a clean-install smoke test. Unvalidated printer hardware remains explicitly experimental.

Pull-request CI checks backend tests, frontend tests/build, migrations, dependency/static security and the production Docker image. The guide has its own strict build/link checks. CI passing does not substitute for hardware, deployment or restore testing.

[Roadmap and release gates](docs/ROADMAP.md) · [Git workflow](docs/GIT_WORKFLOW.md) · [Guide maintenance](docs/GUIDE_MAINTENANCE.md)

## Licence

MakerVault software is **AGPL-3.0-or-later**. See [LICENSE](LICENSE). Third-party media retains its own licence and attribution, also available in the application's About page.
