<p align="center">
  <img src="docs/guide/assets/makervault-logo.jpg" alt="MakerVault logo" width="180">
</p>

<h1 align="center">MakerVault</h1>
<p align="center"><strong>Your workshop, organised.</strong></p>
<p align="center">A self-hosted workspace for electronics, making and 3D printing — from the parts you own to the things you build.</p>
<p align="center"><strong>Application source version: v1.5.0 (release candidate)</strong></p>
<p align="center">
  <a href="https://gavrd7.github.io/MakerVault-docs/">User guide</a> ·
  <a href="docs/guide/getting-started/install.md">Install</a> ·
  <a href="docs/ROADMAP.md">Detailed roadmap</a> ·
  <a href="CHANGELOG.md">Changelog</a> ·
  <a href="https://github.com/gavrd7/MakerVault-Hardware">Hardware</a>
</p>

## Why MakerVault?

Maker projects rarely live in one place. Components end up in boxes and spreadsheets, model revisions in folders, filament in a separate tracker and build notes scattered across apps. **MakerVault connects your physical workshop with its digital records** so you can find what you own, see what a project needs, and keep track of what you made.

- **Self-hosted and private:** run on your own Docker server, with your database and files under your control; no MakerVault cloud subscription required.
- **One connected workflow:** link components, inventory, projects, bills of materials, models, prints and finished parts rather than maintaining separate lists.
- **Useful on the workbench:** responsive desktop/mobile UI, QR/RFID/NFC MakerTags and optional connected hardware.
- **Built for real stock:** track physical quantities, locations and allocations separately from reference catalogues.

<p align="center">
  <img src="https://raw.githubusercontent.com/gavrd7/MakerVault-docs/main/docs/guide/assets/screenshots/dashboard-overview.png" alt="MakerVault dashboard overview" width="92%">
</p>

## Features available now

| Area | What MakerVault offers |
| --- | --- |
| **Inventory and catalogues** | Electronic boards and components, searchable reference specifications and images, physical item IDs, quantities, locations, condition and provenance-aware catalogue enrichment |
| **Projects and bills of materials** | Project workspaces, notes, files, build information, BOMs, quantity-aware stock allocation and cost tracking |
| **Wiring Lab** | Interactive wiring diagrams, catalogue-aware pin selection, basic electrical checks and JSON/SVG export |
| **Files and 3D models** | Private files with version history, STL/3MF viewing and analysis, model revisions, printer-fit and orientation assistance |
| **3D printers and materials** | Printer inventory, filament products, physical spools, reusable spool hardware, printed parts, print history and material/cost reporting |
| **Live integrations** | Optional local printer monitoring and compatible camera feeds, supported printer controls, Spoolman review and Creality CFS material-database read-only snapshots |
| **MakerTags** | Printable QR labels, stable `MV-XXXXXXXX` identities, RFID/NFC UID association, reassignment history and verified NTAG215 URLs |
| **Connected Devices** | Certificate-verified HTTPS pairing, device permissions and heartbeats; with **MakerVault Terminal v1.0**, browse records, create MakerTags, scan filament RFID tags and identify physical spools from the handheld |
| **Search and administration** | Universal search, role-based access, optional OIDC/MFA, account quotas, backups, guarded restore and catalogue-maintenance tools |

**Compatibility notes:** Printer support and available controls vary by manufacturer, firmware and connection method. Some adapters are monitoring-only or have limited real-hardware validation; see the [user guide](https://gavrd7.github.io/MakerVault-docs/) and [hardware-validation issue](https://github.com/gavrd7/MakerVault/issues/37). MakerVault does not automatically deduct physical spool stock from every estimated print.

### Where the pieces connect

An inventory item can be allocated to a project BOM. A model and its revisions can be associated with a build; a recorded print can produce a tracked physical part. A MakerTag on a box, spool or printed object can bring you back to its current record. These links make the system more useful than isolated inventory or printer dashboards.

**Terminal interoperability (v1.5.0):** a paired terminal can resolve CFS material identifiers against cached Creality printer databases, identify physical spools by RFID UID, and scan a spool tag on request from the Physical Identity form. Manufacturer material names require online MakerVault access; offline tag data remains readable. Third-party RFID support depends on compatible tags and available documentation, not universal compatibility.\n\n## Get started

MakerVault runs as a Docker Compose stack with the application, PostgreSQL and Redis. The normal installation pulls a prebuilt image from **GHCR**, so you do not need to compile the application yourself. Start with the complete [Linux installation guide](docs/guide/getting-started/install.md) or [Windows / Docker Desktop / WSL2 guide](docs/guide/getting-started/windows.md).

For a new Linux installation:

```bash
git clone https://github.com/gavrd7/MakerVault.git
cd MakerVault
python3 scripts/generate_env_secrets.py
# Review .env: allowed hosts, trusted origins, storage, timezone and currency
sudo docker compose config --quiet
sudo docker compose pull
sudo docker compose up -d
sudo docker compose ps
```

The supplied Compose configuration normally uses `ghcr.io/gavrd7/makervault:latest`. For first-time setup, open the server's configured address (default `http://SERVER-IP:8765`) and follow the administrator wizard. Retrieve the one-time setup token with:

```bash
sudo docker compose exec -u makervault makervault python manage.py first_run_token
```

Follow the [first sign-in guide](docs/guide/getting-started/first-sign-in.md) for the full process. **Configure and protect HTTPS** before connecting hardware, especially with a private CA. [Connected Devices guide](docs/guide/using/connected-devices.md)

For existing installations, **back up first**, then update your checkout and Compose images as documented in the [installation guide](docs/guide/getting-started/install.md) and [backup guide](docs/guide/administration/backup.md). A version rollback may require restoring data, not simply changing the image tag.

## Roadmap

A concise view of what's delivered and where MakerVault may go next. Checkmarks refer to implemented functionality, **not** universal compatibility with every printer or hardware model. The [detailed roadmap](docs/ROADMAP.md), [issues](https://github.com/gavrd7/MakerVault/issues) and [changelog](CHANGELOG.md) provide scope, validation notes and release history.

### Available

- [x] Self-hosted Docker deployment, first-run setup, account security and managed backup/restore
- [x] Electronic component/board catalogues, physical inventory and storage locations
- [x] Projects, BOMs, stock allocation, files and version history
- [x] Interactive Wiring Lab and searchable workshop records
- [x] 3D model library, STL/3MF previews, analysis and print history
- [x] Filament products, physical/reusable spools, printed parts and cost tracking
- [x] Optional live printer integrations, monitoring, cameras and supported controls
- [x] MakerTags with QR, RFID/NFC association and verified NTAG215 URL writing
- [x] Connected Devices pairing and terminal-first MakerTag creation and physical spool RFID identification (Terminal v1.0)

### Planned / under evaluation

- [ ] **G-code Library and explicit print submission:** organise and preview uploaded G-code and send supported jobs to compatible printers with explicit user control ([issue #155](https://github.com/gavrd7/MakerVault/issues/155))
- [ ] **Self-hosted multi-engine FDM slicing:** optional local slicing service and one MakerVault UI, subject to engine, CLI and licence evaluation
- [ ] **MakerVault Weigh Station:** connected scale/RFID hardware with a removable printable platform (hardware development)
- [x] **Read-only CFS material-tag decoding**, K2 printer material-database snapshots, scoped online material lookup and explicit physical spool UID association; no CFS tag writing or printer database push
- [ ] Expanded real-hardware validation and compatibility for printer/camera adapters ([issue #37](https://github.com/gavrd7/MakerVault/issues/37))
- [ ] User-selectable appearance themes and palettes ([issue #124](https://github.com/gavrd7/MakerVault/issues/124))

These are roadmap intentions, not promises for the next release.

## Project and documentation

- **[MakerVault User Guide](https://gavrd7.github.io/MakerVault-docs/)** ([source](https://github.com/gavrd7/MakerVault-docs)) — installation, daily use, administration and troubleshooting.
- **[MakerVault-Hardware](https://github.com/gavrd7/MakerVault-Hardware)** — terminal firmware, 3D-printable enclosure, wiring and future connected hardware.
- **[Changelog](CHANGELOG.md)** — release-by-release features and fixes.
- **[Detailed roadmap](docs/ROADMAP.md)** — delivered milestones, implementation constraints and outstanding validation.
- **[Contributing](CONTRIBUTING.md)** · **[Security](SECURITY.md)** — project contribution and vulnerability guidance.

**Development approach:** MakerVault is an AI-coded project developed under human direction. The maintainer owns product decisions and physical acceptance testing; automated checks and AI-generated code are not substitutes for real-world validation.

**Data and security:** Database, media, encryption keys and configuration require coordinated backups. Private-file encryption does not encrypt the entire database or every secret. Do not expose a development environment, untrusted printer integration or provisioning portal directly to the internet.

**Licence:** MakerVault-authored code is licensed under the [GNU Affero General Public License v3](LICENSE); third-party content retains its own licensing and attribution.
