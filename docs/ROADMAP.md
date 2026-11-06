# MakerVault roadmap

_Last reconciled: 5 November 2026_

**Current milestone: v1.6.0 — G-code Library and explicit printer submission (#155).** The v1.0 acceptance gates remain complete. This roadmap describes features in the coordinated upcoming application and guide release; it does not imply every adapter is hardware-verified.

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

Creality, Moonraker and OctoPrint expose optional Pause, Resume and confirmed Cancel with per-source opt-in, ownership/editor checks and dispatch protections. Control hardware validation is separate from monitoring. G-code start and upload are now available as separately permissioned, explicit workflows for implemented printer-file adapters; this does not enable arbitrary movement, heating or raw G-code commands. Unsupported adapters remain monitoring-only.

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
- HTTP snapshots and MJPEG-derived frames refresh at approximately 1 fps. Creality's native K1/K2 WebRTC is ingested by MakerVault's compatibility relay and served as authenticated same-origin HLS/fMP4. Browser LAN/VPN access to the MakerVault application is sufficient; the printer video port need not be exposed to the browser.
- Discovery covers stock K1/K2 WebRTC and legacy K1 direct/Helper Script MJPEG presets, Moonraker, OctoPrint, applicable PrusaLink APIs and recognised Anycubic/FlashForge HTTP URLs.
- Owner-scoped media access, same-host validation, DNS pinning, TLS/redirect controls, bounded reads and URL/token redaction are implemented.

The owner confirmed simultaneous stock K1/K2 same-origin WebRTC previews on 5 November 2026 and accepted the compact layout. This does not close every firmware, route, reconnect, security or browser check. Those remain in [hardware validation issue #37](https://github.com/gavrd7/MakerVault/issues/37).

## v1.0 — released

v1.0 consolidates the existing feature set. The release gates were completed on 3 October 2026, including representative off-server recovery and a clean install on a separate Debian/Docker host.

| Order | Workstream | Completion evidence |
| --- | --- | --- |
| 1 — complete | Backup and recovery | Managed backup creation/validation/download, guarded restore, CI recovery rehearsals and a representative real-installation restore on a separate host have passed. |
| 2 — complete | Installation and upgrades | Deployment preflight, representative real upgrade and clean beginner install smoke test have passed. |
| 3 — complete | Reliability and security | Authentication/permissions, uploads/quotas, diagnostics, destructive actions, dependency audits, static security checks and container scanning are covered by the v1 hardening pass and CI. |
| 4 — complete | UI, accessibility and documentation | Mobile/desktop consistency, keyboard focus handling, reduced-motion support, auth branding and current documentation have received the final v1 pass. |
| 5 — complete | Stable release | [The v1 acceptance checklist](V1_ACCEPTANCE.md) is complete; Docker/dependency/security and guide builds are green and the stable release is ready to tag/publish. |

Recovery verification now includes the read-only private-file audit, synthetic Docker dump/archive/restore rehearsal for named volumes and bind mounts, and the managed backup path that runs inside the existing MakerVault worker. The standard workflow creates one managed `.mvbackup` bundle, re-validates it before recovery and provides a guarded restore helper for both same-server rollback and off-server disaster recovery. The web process never receives the Docker socket.

A representative real-installation restore on a separate host passed on 3 October 2026, including deployment-configuration review and private-storage/ownership audits. The clean-install smoke test passed on 3 October 2026 and completed the final owner-run v1.0 gate.

Supported deployment guidance centres on the supplied Linux Docker Compose stack: application/worker, PostgreSQL and Redis. Broader NAS/ARM/desktop compatibility and minimum resource claims need evidence before being advertised.

Experimental adapters may remain explicitly experimental at v1.0. Absence of development hardware does not justify claiming full support or blocking unrelated stable functionality indefinitely.

## v1.6.0 — G-code library and explicit printer submission

- Owner-scoped plain-text G-code assets in Files and Model Library, bounded code inspection, XY toolpath sample visualisation and save-as-new-version editing; G-code can link to a project and model revision.
- **3D Printing** includes a shared G-code library and per-printer **Start print / G-code** workflow: save a new upload, choose an existing MakerVault file, or browse files already stored on a printer. Upload-only never starts a print. Start requires separate confirmation and live printer readiness.
- Native K1/K2 LAN G-code file handling, generic Moonraker and OctoPrint storage/start, and experimental PrusaLink/FlashForge routes are implemented with per-adapter checks. Bambu is read-only FTPS browsing with explicit pinned certificate; proprietary upload/start remains disabled. Other manufacturer protocols stay unsupported until verified.
- K1 native file discovery and print start were observed on clean stock firmware, after modified K1 firmware repeatedly rebooted using both MakerVault and the printer itself. This isolates an environment-dependent printer issue but is not a universal firmware compatibility guarantee. K2 native upload and Moonraker start are physically tested; proprietary K2 mapped CFS start needs controlled verification.
- K1/K2 native cameras use the same MakerVault WebRTC/HLS relay. Older K1 Helper Script MJPEG presets remain available. One-shot print journal, state rechecks, unknown-outcome handling, owner permissions and model-identity mismatch checks apply.
- **Not delivered:** self-hosted slicing engine, arbitrary G-code execution, automatic spool deduction, binary BGCODE text tooling or universal firmware/printer coverage.

See [G-code implementation and testing](development/gcode-library-and-print-submission.md) and [printer storage routing](development/printer-storage-routing.md).

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
- **Customisable theming and appearance** ([issue #124](https://github.com/gavrd7/MakerVault/issues/124)): user-selectable System/Light/Dark modes, curated colour palettes and modest interface styles via Settings → Appearance; live preview, reset to default, persisted user preferences and accessibility/contrast safeguards. Audit and centralise styling tokens first; preserve the current look as default. Future optional enhancement after filament-drying and reusable-spool work, not part of the active drying-data PR.

Printer maintenance logs, schedules and reminders were removed from the planned milestone at the owner's request. Camera development replaced that scope; maintenance is not silently reintroduced here.

## Future FDM workflow — G-code and local slicing (unscheduled)

The v1.6.0 G-code milestone is delivered. **Current next priority: #156, the self-hosted multi-engine MakerVault Slicer**, followed by the connected **MakerVault Weigh Station**. Other planned QoL enhancements rank lower unless reliability/security requires them. The slicer is a separate major milestone and remains incomplete until an end-to-end isolated worker is validated:

1. **[G-code Library and explicit Print Submission (#155)](https://github.com/gavrd7/MakerVault/issues/155):** **Delivered in v1.6.0.** Shared private G-code assets, project/model-revision links, bounded source/XY inspection, immutable edited versions, compatible printer file browsing and upload-only or explicitly confirmed print-start. The release includes printer identity/metadata preflight, readiness checks, a durable command journal and uncertain-outcome handling. Stock K1 native print-start completed a hardware print on clean firmware; K2 mapped-CFS native start and several experimental manufacturers still need hardware validation. No automatic spool-stock deduction or slicing engine. See [implementation and compatibility boundaries](development/gcode-library-and-print-submission.md).
2. **[Self-Hosted Multi-Engine FDM Slicer (#156)](https://github.com/gavrd7/MakerVault/issues/156):** One responsive MakerVault Slicer UI and one optional local slicing service with individually installable, pinned and isolated engine versions. Prioritise an independently verified OrcaSlicer worker (the default), followed by Creality Print, Bambu Studio, PrusaSlicer, Snapmaker Orca, and then CuraEngine, ElegooSlicer, Anycubic Slicer Next and other useful engines, subject to validated headless CLI operation, licensing and profile support. Support printer/plate/nozzle, engine-specific filament/process profiles linked to physical MakerVault inventory, and searchable Basic/Simple/Advanced settings; model manipulation and multimaterial incrementally.

**Design principles:** Slicing computation runs only on the self-hoster's own infrastructure, not MakerVault-hosted cloud infrastructure; the main application remains operable without the optional restricted worker. Reuse existing file, model, filament and printer infrastructure. The SimplyPrint mobile multi-engine UX is a functional reference, not a request to reproduce its UI. G-code work is complete in v1.6.0; slicer development starts in the isolated [foundation branch](https://github.com/gavrd7/MakerVault/tree/feature/self-hosted-slicer-foundation), with the worker and UI enabled only after acceptance gates. See [slicer architecture and acceptance plan](development/self-hosted-slicer.md).

## Post-v1 exploration — optional hardware tag reader

Explore an ESP32-based NFC/RFID companion using common reader hardware, resolving existing Maker Tags over the LAN. Device enrolment, least-privilege authentication and revocation must precede reader-initiated changes. Consider an enclosure/reference build and Home Assistant interoperability without making dedicated hardware compulsory.

Phone QR/NFC workflows and USB/OTG readers remain valid ways to use Maker Tags. The hardware companion is exploratory work after v1, not an active pre-v1 dependency.

## Release discipline

- Keep main deployable and use short-lived reviewed branches.
- Run applicable backend/frontend, migration, security, Docker and documentation checks before merging.
- Update affected user documentation and validation records with behaviour changes.
- Remove branches after confirming their work is merged, including content-equivalent squash merges.
- Keep genuine validation and implementation TODOs open; repository cleanup does not mean declaring untested features complete.
