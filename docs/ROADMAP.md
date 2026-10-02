# MakerVault roadmap

_Last reconciled: 2 October 2026_

**Current release: v0.9.0.2, merged into main. Next milestone: v1.0 release hardening and documentation.**

This roadmap separates delivered functionality, outstanding validation and future implementation. The [README](../README.md) describes the current application; [CHANGELOG.md](../CHANGELOG.md) records changes.

## Delivered milestones

| Version | Delivered scope |
| --- | --- |
| v0.4.x | Project workspaces, persistent maintenance scheduling, project files/repositories and standalone Files |
| v0.5.0 | Bills of materials, quantity-aware inventory allocation and allocation history |
| v0.6.0 | Printers, physical spools, filament products, model revisions, print history, Spoolman and Creality CFS |
| v0.6.1 | Local STL/3MF analysis, interactive 3D viewer and printer-fit checks |
| v0.6.2 | Optional read-only SimplyPrint imports, requiring suitable account/API access |
| v0.6.3 | Responsive UI, manufacturer-neutral generic components and application branding |
| v0.6.4 | Immutable file versions, model revision uploads, thumbnails, mesh checks and orientation guidance |
| v0.6.5 | Material-cost estimates and print-history analytics |
| v0.6.6 | Slicer metadata, multi-file/material-aware 3MF rendering and plate selection |
| v0.7.0.1 | Owner isolation, administrator quotas, private-file encryption and legacy migration |
| v0.7.1 | Universal search, catalogue coverage, enrichment and image/provenance improvements |
| v0.7.2 | QR/NFC/RFID Maker Tags, Wiring Lab and catalogue-quality work |
| v0.7.3–v0.7.3.2 | Local printer adapters, multi-tool monitoring, opt-in controls, live summaries and sourced filament estimates |
| v0.8.0 | Explicit retained printed-part batches, projects/locations/states, replacements and Maker Tags |
| v0.9.0–v0.9.0.2 | Camera discovery/setup, HTTP images, Creality WebRTC, automatic compact dashboard/printer feeds and fullscreen |

### Live printer monitoring

Implemented sources include Creality local, Moonraker/Klipper, OctoPrint, Bambu Lab local, PrusaLink, Anycubic LAN and FlashForge local. Elegoo, QIDI, Sovol, Snapmaker U1 and Voron profiles reuse Moonraker where compatible firmware exposes it.

K2 monitoring and K1 monitoring through both Creality and Moonraker have owner confirmation. Other manufacturer/model combinations remain experimental, even where fixtures and automated tests pass. Standard numbered extruders and active-tool reporting are implemented in the shared Moonraker adapter; this does not imply every toolchanger or multi-material system is supported.

Creality, Moonraker and OctoPrint expose optional Pause, Resume and confirmed Cancel with per-source opt-in, ownership/editor checks and dispatch protections. Control hardware validation is separate from monitoring. Other adapters remain monitoring-only; Start print, movement, heating and raw G-code are outside the current control scope.

### Filament accounting and printed parts

- Print history and accounting operate independently of saved models and retained parts.
- Printed parts are created explicitly; automatic part creation is not enabled.
- Supported plain-G-code gram metadata and Moonraker extrusion/metadata estimates retain provenance. Manual usage takes precedence; missing information remains unrecorded.
- Full-file estimates apply only to successful prints. Polling does not repeatedly accumulate the same usage.
- Automatic estimates do not deduct spool stock or infer per-spool allocation, purge/waste or cost.

### Camera milestone — complete for the agreed v0.9 scope

- Camera setup is separate from live telemetry and is offered as an optional second step after adding a live source.
- Visible dashboard and 3D Printing cards automatically show the most recently configured enabled camera. Selection is stored on the server and changed in setup.
- Normal viewing shows the feed and Fullscreen. Off-screen/hidden-page feeds pause; browser media requests are queued to support multiple visible previews.
- HTTP snapshots and MJPEG-derived frames refresh at approximately 1 fps. Creality WebRTC media requires browser LAN/VPN reachability; MakerVault does not relay that media.
- Discovery covers K1 direct/Helper Script presets, Moonraker, OctoPrint, applicable PrusaLink APIs and recognised Anycubic/FlashForge HTTP URLs.
- Owner-scoped media access, same-host validation, DNS pinning, TLS/redirect controls, bounded reads and URL/token redaction are implemented.

The owner confirmed K1/K2 playback and accepted the compact layout on 2 October 2026. This does not close every firmware, route, reconnect, security or browser check. Those remain in [hardware validation issue #37](https://github.com/gavrd7/MakerVault/issues/37).

## Next milestone — v1.0

The focus is a dependable first stable release of the existing feature set. The following work is planned, not yet verified complete.

| Order | Workstream | Completion evidence |
| --- | --- | --- |
| 1 — next | Backup and recovery | Restore a consistent database/media/key/configuration set into an isolated installation; verify login, private-file decryption, projects, models and relationships. Exercise documented named-volume and bind-mount paths and missing-key failures. |
| 2 | Installation and upgrades | Rehearse the beginner installation and representative upgrades; verify migrations, ownership, encryption and existing data. Document supported upgrade and recovery paths without promising arbitrary downgrades. |
| 3 | Reliability and security | Review authentication/permissions, uploads and quotas, integrations, network failure/reconnect handling, duplicate-history prevention, diagnostics and destructive actions. Record fixes and regression evidence. |
| 4 | UI, accessibility and documentation | Review mobile/desktop layouts, keyboard/focus behaviour, error/empty states and consistent wording. Complete current feature chapters, screenshots, configuration guidance and support matrices. |
| 5 | Release candidate and stable release | Run the acceptance checklist, resolve release blockers, verify Docker/dependency/security and guide builds, record tested deployment assumptions, then define/tag the stable release and upgrade policy. |

Recovery verification work now includes a read-only private-file audit and a synthetic Docker dump/archive/restore rehearsal for named volumes and bind mounts, exercised by PR CI. A representative real-installation restore, deployment configuration review and manual UI acceptance remain release gates.

Backup/recovery documentation and an initial guide already exist. The next pass verifies them end-to-end and improves them from the results; it is not a claim that recovery has already been rehearsed.

Supported deployment guidance centres on the supplied Linux Docker Compose stack: application/worker, PostgreSQL and Redis. Broader NAS/ARM/desktop compatibility and minimum resource claims need evidence before being advertised.

Experimental adapters may remain explicitly experimental at v1.0. Absence of development hardware does not justify claiming full support or blocking unrelated stable functionality indefinitely.

## Outstanding validation

[Issue #37](https://github.com/gavrd7/MakerVault/issues/37) remains open for:

- Representative Bambu/AMS, PrusaLink, Anycubic/ACE, FlashForge and Moonraker manufacturer hardware.
- Optional Pause/Resume/Cancel independently of monitoring.
- Multi-tool and material-slot correctness, reconnect/stale behaviour and duplicate-history prevention.
- Filament estimate accuracy and provenance on actual jobs.
- Camera route/firmware/browser coverage, authentication, reconnect/cleanup and HTTPS access.

Confirmed K1/K2 results stay recorded separately from unchecked tests. Automatic tests validate contracts and regressions, not all hardware behaviour.

## Future implementation backlog

These are not delivered capabilities or mandatory additions to the v1.0 scope:

- Native Bambu camera transport, cloud camera APIs, full-rate streaming, generic RTSP/HLS/WebRTC relaying and separate camera hosts.
- Additional reliable manufacturer-reported filament weights, archived/binary G-code and explicit per-tool/spool allocation.
- Prusa MMU telemetry and manufacturer-specific material/toolchanger systems not exposed by current adapters; custom-named Klipper tools and older/non-compatible protocols.
- Further model/file intelligence, catalogue enrichment and workflow improvements where real use establishes value.
- Import/export and data portability improvements identified during the v1 review.

Printer maintenance logs, schedules and reminders were removed from the planned milestone at the owner's request. Camera development replaced that scope; maintenance is not silently reintroduced here.

## Post-v1 exploration — optional hardware tag reader

Explore an ESP32-based NFC/RFID companion using common reader hardware, resolving existing Maker Tags over the LAN. Device enrolment, least-privilege authentication and revocation must precede reader-initiated changes. Consider an enclosure/reference build and Home Assistant interoperability without making dedicated hardware compulsory.

Phone QR/NFC workflows and USB/OTG readers remain valid ways to use Maker Tags. The hardware companion is exploratory work after v1, not an active pre-v1 dependency.

## Release discipline

- Keep main deployable and use short-lived reviewed branches.
- Run applicable backend/frontend, migration, security, Docker and documentation checks before merging.
- Update affected user documentation and validation records with behaviour changes.
- Remove branches after confirming their work is merged, including content-equivalent squash merges.
- Keep genuine validation and implementation TODOs open; repository cleanup does not mean declaring untested features complete.
