# Printer storage routing

The G-code preparation layer deals with **logical printer files**, not Linux
filesystem locations. Each printer adapter owns file discovery, upload,
verification and start commands. No generic TCP or HTTP ping can discover a
filesystem path, and no other adapter may inherit a Creality path.

## Model-family strategies

| Printer family | Current routing | Storage / command notes | Validation |
| --- | --- | --- | --- |
| Creality K1, K1C, K1 Max, K1 SE | Native Creality file path | `/usr/data/printer_data/gcodes/` | Source-supported; K1 hardware start not yet tested by MakerVault |
| Creality K2 family | Native Creality file path | `/mnt/UDISK/printer_data/gcodes/` | K2 single-filament CFS override physically demonstrated |
| Creality Hi, SPARKX i7/i8, Ender-3 V3 family | Per-firmware native probe required | Do not inherit K1/K2 storage path; Ender-3 V3 SE can be Marlin/USB rather than stock LAN | Not verified |
| Bambu Lab X1/P1/A1 families | Native LAN FTPS model profile | FTPS on port 990; cache/SD layout and print commands differ by model. Verify storage listing before any write | Vendor protocol documented, upload/start not enabled in MakerVault |
| Bambu Lab H2/P2/X2 and later | Native LAN model-specific storage API | Removable USB/SD storage and firmware-specific transport or bridge; do not assume legacy `/cache` | Model/firmware verification required |
| Prusa MK-series, MINI, XL, CORE One | PrusaLink storage API | Query `/api/v1/storage` and advertised capabilities; use returned logical storage, not OS paths. Old models may need a PrusaLink host | API-managed |
| Anycubic Kobra family 2024 onward | Model-specific LAN API | Some expose `/info` with a short-lived `gcode_upload` URL (port 18910); never cache a temporary URL or guess a local path | Adapter firmware validation required |
| FlashForge | Model-specific FlashForge API | Adventurer 5M/5M Pro currently use `/uploadGcode`; do not assume all Creator/Guider/Adventurer generations share it | Only 5M family enabled for transfer |
| Snapmaker U1 | Moonraker storage API (U1-specific integration) | Standard logical `gcodes` file root; no absolute filesystem path needed | Printer firmware testing required |
| Generic Moonraker | Moonraker file manager | `/server/files/list`, `/server/files/upload`, `/printer/print/start` | Existing supported printer connection |
| Generic OctoPrint | OctoPrint file API | `/api/files/local` and job commands | Existing supported printer connection |

## Safe future discovery

At setup, probe the **actual file-management service** through a known,
authenticated API. Prefer a provider-advertised storage root; otherwise use a
verified model/firmware profile. A path override may be considered in advanced
connection settings but must be validated and scoped to that printer only.
Use read-only probes first and never submit a G-code or start a print as a
connectivity test. Unsupported families remain browse/monitor-only, or require
an already-supported generic connector, until their storage protocol is verified.

Generic Moonraker and OctoPrint are shown in Settings → 3D Printing as
connection entry points. They are **per-printer** configurations, not global
Spoolman/SimplyPrint-style scheduled integrations; navigate to 3D Printing,
choose the physical printer and add a live source there.

References:
- Bambu security white paper (LAN MQTTs and FTPS):
  https://cdn1.bambulab.com/trust-center/file/bambulab-security-whitepaper-en.pdf
- Bambu model-specific paths:
  https://dmontgomery40.github.io/bambu-printer-mcp/guide/slicing
- PrusaLink capabilities and logical storage:
  https://github.com/prusa3d/Prusa-Link-Web/blob/master/spec/openapi.yaml
- Anycubic current upload URL:
  https://github.com/cuihuir/anycubic_bridge/blob/main/README.md
- Snapmaker U1 Moonraker:
  https://github.com/Snapmaker/u1-moonraker


## Uniform G-code file browsing contract

A printer's **configured adapter**, not its manufacturer name, chooses the
actual read-only file-listing protocol. The public printer-files endpoint calls
`list_printer_gcodes(connection)`; each implemented adapter returns records
with `path`, `size_bytes`, `modified`, and `permissions` (where the
upstream provides those values).

- **Stock Creality OS**: proprietary WebSocket `reqGcodeFile`; recognises
  `retGcodeFileInfo2` on newer firmware and packed `retGcodeFileInfo` on
  older firmware, with bounded, path-validated decoding. If the *same
  MakerVault printer record* has an enabled and online generic Moonraker
  connection, try its `/server/files/list` first. If that API fails,
  automatically try the stock Creality listing. A valid empty list is
  authoritative and does not trigger another request.
- **Moonraker**: generic or verified manufacturer Moonraker-compatible
  integrations (Elegoo, Qidi, Sovol, Snapmaker and Voron), using the `gcodes`
  logical root. No OS path assumptions.
- **OctoPrint**: `/api/files/local`, recursive; no OS path assumptions.
- **PrusaLink**: version-specific `/api/v1/files/local/`; unsupported
  firmware responses are reported as such, not guessed.
- **Bambu Lab LAN**: pinned-certificate read-only FTPS browser; requires
  configured certificate fingerprint. Not every model/firmware is supported.
- **FlashForge**: the existing supported FlashForge file-management endpoint.
- **Unimplemented family protocols**: return a clear unsupported-listing
  response. Never probe random ports or fall back to Moonraker simply because
  a printer is Klipper-based.

Read-only fallback means *requesting another already-configured, identity-bound
file interface* after a listing failure. It never installs Moonraker, changes
firmware, uploads G-code or starts a print. Future vendors must add a verified
listing handler, response normaliser and tests **before** advertising browsing
capability. A discovered empty list is not the same as a failed protocol.
