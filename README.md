<p align="center">
  <img src="docs/guide/assets/makervault-logo.jpg" alt="MakerVault logo" width="180">
</p>

<h1 align="center">MakerVault</h1>

<p align="center"><strong>Your workshop, organised.</strong></p>

<p align="center">
  A self-hosted workspace for electronics inventory, projects, files and 3D printing.
</p>

<p align="center">
  <strong>Current stable release: v1.1.0</strong>
</p>

<p align="center">
  <a href="https://gavrd7.github.io/MakerVault-docs/">User guide</a> ·
  <a href="docs/guide/getting-started/install.md">Installation</a> ·
  <a href="https://github.com/gavrd7/MakerVault-docs">Guide source</a> ·
  <a href="docs/ROADMAP.md">Roadmap</a> ·
  <a href="CHANGELOG.md">Changelog</a>
</p>

**What's new in v1.1.0:** reliable background catalogue maintenance with restart-safe board/component/filament/image checkpoints, improved manufacturer-backed technical data, clearer image diagnostics and resilient OrcaSlicer vendor retries. Previous account, security and first-run improvements remain included.

MakerVault keeps the practical parts of a workshop connected: what you own, what a build needs, which files and wiring belong to it, which model revision you printed, and where the finished parts ended up.

## First-run administrator setup (introduced in v1.0.5)

On a **fresh installation with no superuser**, opening MakerVault's normal URL redirects to the first-run setup wizard automatically. The server operator obtains a short-lived token (valid for 30 minutes) from the Docker host, then creates the first administrator in the browser with username, email, password and confirmation. The wizard includes a password-visibility checkbox and matching feedback. It closes automatically once any superuser exists; existing installations continue to the standard sign-in page.

Using standard Compose in your deployment directory, obtain the one-time token with:

```bash
sudo docker compose exec -u makervault makervault python manage.py first_run_token
```

Use the same `-p` and `-f` options as your original `docker compose up` command when using a custom project or build override. **Never publish or share the token.** Leave `MAKERVAULT_ADMIN_PASSWORD` empty if you want to create the administrator in the GUI; the existing environment-based initial admin mechanism and Django's `createsuperuser` remain available as alternatives. The first-run wizard cannot be used to reset an existing administrator's password; instead use `python manage.py changepassword YOUR_ADMIN_USERNAME` in the running container.

The web interface no longer waits for initial catalogue seeding or OrcaSlicer printer-model enrichment to finish. These tasks run under the supervised background process; catalogue entries may populate shortly after the interface becomes available.

## Development and validation model

MakerVault is an **AI-coded project**. The application codebase has been produced entirely through AI systems working under human direction rather than by a human programmer writing the implementation by hand.

The human maintainer is responsible for the product side of the project: feature ideas, priorities and design decisions; hands-on acceptance checks; bug discovery; practical testing; and deciding whether changes are good enough to merge and release.

This also sets an important support expectation: investigation, fixes and future development depend on the capabilities of the available AI tooling, the quality of reproducible reports, and human validation of the resulting changes. AI-generated code and automated CI are not treated as substitutes for real-world testing.


## A look at MakerVault

<p align="center">
  <img src="https://raw.githubusercontent.com/gavrd7/MakerVault-docs/main/docs/guide/assets/screenshots/dashboard-overview.png" alt="MakerVault dashboard" width="92%">
</p>

<p align="center"><em>Dashboard overview — projects, inventory, printing and workshop activity in one place.</em></p>

<table>
  <tr>
    <td width="50%" valign="top">
      <img src="https://raw.githubusercontent.com/gavrd7/MakerVault-docs/main/docs/guide/assets/screenshots/printing-overview.png" alt="MakerVault 3D printing overview">
      <br><strong>3D printing</strong><br>
      Printers, spools, models, live integrations and print history.
    </td>
    <td width="50%" valign="top">
      <img src="https://raw.githubusercontent.com/gavrd7/MakerVault-docs/main/docs/guide/assets/screenshots/interactive-wiring.png" alt="MakerVault Interactive Wiring">
      <br><strong>Interactive Wiring</strong><br>
      Build diagrams with catalogue-aware pins and electrical checks.
    </td>
  </tr>
  <tr>
    <td colspan="2" align="center">
      <a href="https://gavrd7.github.io/MakerVault-docs/">Explore the MakerVault administration and HTTPS documentation</a>
      <br><strong>Self-hosting without hiding the hard parts</strong><br>
      Native HTTPS, Local CA guidance, backups, recovery and security settings are built into the application.
    </td>
  </tr>
</table>

> The screenshots above come from the public, sanitised MakerVault user guide. See the [published guide](https://gavrd7.github.io/MakerVault-docs/) for walkthroughs and more screenshots, or visit the [documentation repository](https://github.com/gavrd7/MakerVault-docs) to contribute guide improvements.

## What you can do

| Workspace | Current capabilities |
| --- | --- |
| Catalogues | Boards, generic components, printers and filament products; technical specifications, images, provenance, matching and scheduled enrichment |
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

The interface works on desktop, tablet and mobile. Local accounts, MFA, optional OpenID Connect, role-based permissions and administrator storage quotas are included.

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

HTTP snapshot/MJPEG sources provide refreshed images at approximately one frame per second. Creality K2 WebRTC is ingested by MakerVault's loopback-only go2rtc helper and exposed to signed-in users as same-origin HLS/fMP4, so no dedicated camera media port or direct browser-to-printer route is required. Discovery supports Moonraker, OctoPrint, applicable PrusaLink APIs and recognised manufacturer HTTP URLs. Native Bambu camera transport, cloud camera access, generic user-configurable RTSP/HLS relaying and separate camera hosts are not implemented.

[Camera setup and limitations](docs/guide/integrations/printer-cameras.md) · [Printer controls](docs/guide/integrations/printer-controls.md) · [Hardware validation](docs/guide/integrations/printer-adapter-validation.md) · [Outstanding tests](https://github.com/gavrd7/MakerVault/issues/37)

## Filament catalogue, accounting and printed parts

MakerVault's filament catalogue is a merged reference layer rather than a copy of one upstream service. SpoolmanDB remains the primary public catalogue, with verified manufacturer-backed supplemental entries and technical data used to fill genuine coverage gaps. Saved filament products can be **matched, rematched or unmatched** from the catalogue; user-entered values remain authoritative, and newer matches keep a pre-match snapshot so an unmatch can restore the previous state. Spool Inventory shows **✓ Matched** or **Unmatched** at a glance for the shared filament product behind each physical spool.

Catalogue matching is optional. An unmatched filament remains a normal usable MakerVault record, and MakerVault does not invent a match merely to remove the badge.

Print history and filament accounting do not require saving a model or retaining a printed part. **Part creation is explicit and is never automatic by default.**

MakerVault can use supported plain-G-code gram metadata and Moonraker extrusion/metadata estimates. Estimates retain their source; manual usage rows take precedence. Missing measurements remain **Not recorded**, rather than being invented from print duration or CFS percentages. Whole-file estimates count only after successful completion.

Recorded material rows can estimate cost from spool purchase data, with manual overrides and separate currency totals. Automatic job estimates do **not** deduct physical-spool inventory or invent per-spool allocation, purge/waste amounts or material cost.

[Print history and usage](docs/guide/using/print-history.md) · [Printed parts](docs/guide/using/printed-parts.md)

## Install

MakerVault uses Docker Compose and the pre-built MakerVault image from **GitHub Container Registry (GHCR)**. A dedicated Linux host remains the preferred always-on server deployment, but Windows users can also install MakerVault with **Docker Desktop**, **Docker Desktop + WSL2 integration**, or **Docker Engine directly inside WSL2**.

[Linux installation](docs/guide/getting-started/install.md) · [Windows / Docker Desktop / WSL2 installation](docs/guide/getting-started/windows.md)

The step-by-step guides assume no previous MakerVault experience and explain the host-specific differences.

```bash
git clone https://github.com/gavrd7/MakerVault.git
cd MakerVault
python3 scripts/generate_env_secrets.py
```

The default Compose file pulls:

```text
ghcr.io/gavrd7/makervault:latest
```

No application compilation is required on the server for the normal install.

For a **new installation**, edit `.env` before starting:

- The setup script generates independent `DJANGO_SECRET_KEY` and `POSTGRES_PASSWORD` values automatically, retaining existing values if run again.
- Add your server hostname/IP to `DJANGO_ALLOWED_HOSTS` and its full URL to `DJANGO_CSRF_TRUSTED_ORIGINS`.
- Select timezone, currency and persistent storage locations.
- For direct LAN access, use `TRUST_PROXY_HEADERS=false` and `ALLAUTH_TRUSTED_PROXY_COUNT=0`.
- Keep local registration disabled unless you deliberately need it.

```bash
sudo docker compose config --quiet
sudo docker compose pull
sudo docker compose up -d
sudo docker compose ps
sudo docker compose exec makervault python manage.py createsuperuser
```

Open `http://SERVER-IP:8765`. The host port is configurable through `MAKERVAULT_PORT`; the container listens on port 8000. There is no universal default login.

**Existing installation?** Preserve your current `.env`, secrets and storage. Follow the [update guide](docs/guide/administration/updates.md), not the new-install steps.

[Windows / Docker Desktop / WSL2](docs/guide/getting-started/windows.md) · [Environment settings](docs/guide/getting-started/environment.md) · [Storage choices](docs/guide/getting-started/storage.md) · [HTTPS/reverse proxy](docs/guide/advanced/reverse-proxy.md) · [OIDC](docs/guide/advanced/oidc.md)

## Deployment and data

The default Compose stack has three persistent containers:

- **makervault:** Django/Gunicorn, the compiled React frontend and Celery worker/beat.
- **postgres:** PostgreSQL application data.
- **redis:** queue/cache and background-work state.


PostgreSQL and Redis do not publish host ports by default. MakerVault serves HTTP on the configured app port and can optionally expose a separate native HTTPS listener (default 8443) with a supplied or MakerVault-managed self-signed certificate; reverse-proxy HTTPS remains the recommended domain/public deployment. Managed backup creation runs inside the existing MakerVault worker; restore uses guarded one-off commands from the same MakerVault image. Application code is built into the image. Named volumes and absolute-path bind mounts are supported for media, encryption keys, PostgreSQL, Redis, managed backups and optional native-TLS identity.

Private uploaded files use authenticated AES-256-GCM encryption at rest with opaque object names. The default key is stored separately from media. This does not mean the database, deployment configuration or every secret is encrypted by the private-file storage feature.

**Back up the database, media, matching encryption key and deployment configuration together.** Media without its key cannot recover encrypted uploads. Superusers can create, verify, download and manage a single recovery bundle from **Settings → Backup & restore**. A guarded restore helper handles same-server recovery and downloaded bundles on a replacement host without giving the web process Docker control. Synthetic recovery is exercised in CI, and a representative real-installation backup was restored successfully on a separate clean host during the v1.0 release rehearsal.

[Backup and recovery](docs/guide/administration/backup.md) · [Accounts and quotas](docs/guide/administration/accounts.md)

## Update an existing deployment

Back up first, then run these commands from your MakerVault checkout:

```bash
git fetch --prune origin
git switch main
git pull --ff-only origin main
sudo docker compose pull
sudo docker compose up -d
sudo docker compose ps
```

The default image is `ghcr.io/gavrd7/makervault:latest`. You can pin a release without editing Compose by setting `MAKERVAULT_IMAGE=ghcr.io/gavrd7/makervault:1.1.0` in `.env`.

Prefer to build the application yourself? The repository retains the Dockerfile and provides `compose.build.yaml`:

```bash
sudo docker compose -f compose.yaml -f compose.build.yaml up -d --build
```

That source-build path uses the same database, Redis, media, key and backup storage as the pre-built image path.

Startup applies migrations and idempotent setup tasks. Read the changelog and update guide before changing versions. A database migration is not guaranteed to be reversible by simply switching to an older image.

Install MakerVault wherever you keep self-hosted application source, for example `~/apps/MakerVault` or `/srv/makervault/app`. Persistent data should use the storage locations configured in `.env`.

## Reference data and background work

Administrator settings provide scheduled catalogue maintenance and manual refresh, plus separate integration synchronisation controls. Board/component data, OrcaSlicer printer profiles and the merged MakerVault filament catalogue carry provenance and may have incomplete fields. Filament enrichment can combine SpoolmanDB, verified supplemental manufacturer records and authoritative product/TDS data while preserving manual corrections. Missing values or an **Unmatched** filament are not proof that the record is unusable.

Catalogue media can be locally cached or retained as external references where redistribution is inappropriate. Third-party images keep their original source, licence and attribution; they are not relicensed as MakerVault software.

[Catalogue guide](docs/guide/using/catalogue.md) · [Maintenance](docs/guide/administration/catalogue-updates.md) · [Third-party notices](THIRD_PARTY_NOTICES.md)

## Project status and development

**v1.1.0** is the current stable MakerVault release. It retains browser-based first-run administrator setup, consolidated account/security management, role-based access controls, safe environment secret generation, and faster access to the web interface while catalogue seeding and OrcaSlicer enrichment continue in the background. The v1.0.4 project priorities and deadline improvements remain included. Experimental printer hardware remains subject to its documented validation boundaries.

Pull-request CI checks backend tests, frontend tests/build, migrations, dependency/static security and the production Docker image. The guide has its own strict build/link checks. CI passing does not substitute for hardware, deployment or restore testing.

[Roadmap and release gates](docs/ROADMAP.md) · [Git workflow](docs/GIT_WORKFLOW.md) · [Guide maintenance](docs/GUIDE_MAINTENANCE.md)

## Licence

MakerVault software is **AGPL-3.0-or-later**. See [LICENSE](LICENSE). Third-party media retains its own licence and attribution, also available in the application's About page.
