# G-code library, visual inspection and explicit printer submission

Milestone: [G-code Library & Print Submission #155](https://github.com/gavrd7/MakerVault/issues/155)

## Core architecture

**One canonical asset, three entry points.** G-code is an owner-scoped, private `FileAsset` in MakerVault Files. It may be standalone, assigned to a project, or attached to a specific `ModelRevision` as an optional G-code toolpath; an STL/3MF remains the primary editable model geometry. Print history can link to G-code without duplicating the underlying file. A saved code edit creates a **new file version**, never modifies the original bytes.

User-facing entry points:
- **Files:** upload, search, download, edit-as-new-version, inspect toolpath and metadata.
- **Model Library:** attach existing G-code, upload it with a new STL/3MF or to an existing revision, preview the G-code alongside the 3D model.
- **3D Printing → Models & print history:** open the same G-code library in a modal, with standalone/project-linked uploads.

The initial implementation supports plain-text `.gcode` only. Binary `.bgcode` is not fed to the text parser or editor.

## Parser and visualisation — phase 1

- A permission-checked GET endpoint reads at most 32 MiB for advisory analysis and returns at most 256 KiB of source preview plus 3,000 XY motion samples.
- The UI provides a top-down XY path and text source. It is **not** a complete 3D print simulation, extrusion preview, or executable validation.
- An explicit printer-name/machine header is a **hint**, not a confirmed printer identity. Unknown or ambiguous source remains **unverified**, not compatible.
- Edited source is saved only as a new file revision; editing is disabled where the source preview is truncated.
- No analysis, saving, browsing or viewing action sends a printer command.

## Printer-target validation — phase 2, required before enabling submission

Every submission requires a fresh, specific target printer connection (the selected printer, adapter, active endpoint, capability and status), owner-scoped assets, and explicit user permissions. Validation must compare:

1. **Printer model identity:** exact known slicer-printer-profile IDs when available, normalized model-name aliases as advisory evidence, and unknown values treated as unknown — never auto-accept a filename or header substring.
2. **Machine limits:** build volume/origin/bed shape, Z ceiling, required nozzle size, tools/extruders, toolchange commands and any incompatible firmware dialect, only when reliable values exist.
3. **File safety:** complete file available, checksum/size, parser confidence, unsupported binary format, and potentially destructive/unsupported commands.
4. **Current connection:** online/recent snapshot, enabled upload and start-print capabilities, authenticated endpoint and target selection.

For example, G-code explicitly sliced for a **Creality K2** and selected for a **Creality K1** must raise a model-mismatch error and **block automatic start**. An upload-only option can be separately considered only if the adapter safely supports storage without execution and the user explicitly acknowledges the mismatch. If printer origin is missing, compatibility remains **unknown** and direct print cannot be silently enabled. Do not infer a positive match from a shared brand or generic Marlin/Klipper commands.

## Printer upload and print — experimental implementation in PR #169

A **Start print / G-code** button has been added per live-monitoring connection. It offers three sources: **upload a new G-code to MakerVault**, **choose an existing MakerVault G-code**, and **browse files already on that printer**. A new ad-hoc file is saved as a private MakerVault FileAsset first, rather than bypassing the common storage/permissions system.

Experimental adapter implementation:
- **Moonraker/Klipper:** G-code list, verified upload-only and explicit print start, including adapters routed to Moonraker for Elegoo, QIDI, Sovol, Snapmaker and Voron. Specific manufacturer-firmware routing still requires validation.
- **OctoPrint:** local file listing, multipart upload with both select/print false, and explicitly confirmed file select-and-print using the documented REST API.
- **PrusaLink (experimental):** native v1 file listing, authenticated upload-by-PUT with Print-After-Upload disabled, and a separate start POST; firmware or storage variants without matching APIs fail closed.
- **Bambu Lab LAN:** experimental **read-only FTPS browsing**, with manually configured SHA-256 certificate pinning for both control and data-channel TLS. No automatic trust on first use. It requires the configured LAN access code. Device firmware differences may still reject the listing. FTPS upload and MQTT print-start remain disabled; many Bambu models expect print-ready `.gcode.3mf` rather than arbitrary text G-code.
- **Creality K1/K2 stock LAN:** native WebSocket telemetry/CFS, HTTP port 80 G-code upload and native print commands. Where a separately configured, recently online Moonraker source exists on the **same** printer, MakerVault uses it for read-only file listing and verification of native HTTP uploads; the stock `reqGcodeFile` response has not been verified against the development K2 firmware. Native upload succeeded on the development K2, and the Moonraker file upload/original sliced mapping start completed a physical print test.
- **K2 CFS print preparation:** MakerVault reads native CFS slots, displays real material and colour, extracts advisory slicer-declared filament requirements (including `filament_type`, `filament_colour` and Creality Print `Material Type` when present), and proposes matching slots. Each slicer tool can be assigned a loaded CFS slot. For a mapped start, it re-polls native CFS immediately before dispatch, rejects changed/unknown or material-mismatched slots, verifies the uploaded file, and sends `colorMatch` followed by `multiColorPrint` over the native WebSocket exactly once. Do **not** also call Moonraker print-start for this mode. The original-slicer-mapping path remains an alternative for a Moonraker connection. Both require an explicit final user confirmation and display the actual selected materials. The proprietary WebSocket has no dependable command acknowledgement, so mapped starts remain `unknown` until verified on the printer; do not automatically retry. Only up to four declared slicer filaments are supported for the current mapping implementation. No arbitrary material substitution, CFS database writes or silent mapping fallback.
- **User interface:** printer capability/owner role and explicit final confirmation replace G-code-specific experimental enable/acknowledgement checkboxes. The documentation—not repetitive modal warnings—describes the unverified printer/firmware combinations. A regular disabled/permission setting on the connection still applies where appropriate. The compatibility report remains advisory, and unsupported printer profile/file metadata are never represented as verified. **K2 mapped CFS print-start remains to be hardware-tested on the development printer.**

- **FlashForge Adventurer 5M / 5M Pro:** experimental native HTTP `:8898` file listing, upload-only with `printNow: false`, and separate `printGcode` after an idle recheck, subject to printer permissions and protocol capabilities. AD5X and Creator multi-material start remain disabled until per-tool material mappings and firmware-specific protocols are validated. Only plain `.gcode` files appear in the actionable list.
- **PrusaLink:** native file browsing and two-step transfer/start for versions supporting the v1 API. Upload requires `/api/version` advertising `upload-by-put` and a writable `LOCAL` storage record from `/api/v1/storage`; unsupported firmware fails closed without undocumented fallbacks.
- **Anycubic and other manufacturer-local adapters:** native printer-file transfer/start is unsupported pending documented APIs and hardware validation. A separately configured Moonraker-compatible bridge may be used where the owner verifies the bridge endpoint and actual printer identity; monitoring alone never authorises cross-protocol file submissions.

These paths are being validated incrementally, and the PR remains draft. File browsing is read-only. Only a user with existing printer control permission and an enabled connection can submit; supported endpoints require an online, recently observed printer. A fresh status check and one-shot, persistent request journal apply before potentially irreversible commands. A mismatch is rejected; unknown profiles require the final file/printer/action confirmation and remain marked unverified. G-code containing flagged firmware-control commands or a partially inspected large file is blocked from MakerVault file submission.

Existing Pause/Resume/Cancel controls do not imply file upload or start capabilities. Do not enable commands for proprietary adapters merely because monitoring succeeds. See [hardware validation issue #37](https://github.com/gavrd7/MakerVault/issues/37).

- **Upload only** transfers the selected immutable file to the printer; it must not start a job.
- **Upload & start print** is a separate, explicit confirmed action, with a fresh printer-state check immediately before dispatch.
- The server retains an immutable audit/attempt record with selected file SHA-256, destination printer/connection, capability verdict, operator and status; unknown outcomes are never silently retried.
- The service must guard against endpoint substitution, SSRF, stale printer identity, duplicate submissions, disconnection and partial transfers; follow existing owner/role checks.
- Never execute arbitrary uploaded G-code inside the MakerVault container and never deduct inventory simply because a file was uploaded or a print started.
- Protect against concurrent starts, busy printers and cross-model incompatibility; default to fail closed if the adapter cannot prove a safe state.

## Acceptance tests

Verify multi-user file isolation; standalone/project references; optional G-code on model revisions; editor immutability; binary/truncated file behaviour; valid/invalid G-code metadata; source/target K2 vs K1 mismatch; no-model metadata; unsafe commands; active/busy/stale/disconnected printer states; permission/HTTPS/adapters; upload-only not starting; print only after explicit confirmation; idempotency and partial failures. Physical upload/start testing requires real printer hardware and should not rely only on mocked API calls.

**Release gate:** The common library, Moonraker/OctoPrint/Prusa file commands, Bambu pinned read-only storage browser and Creality Moonraker setup are implemented only in draft form. Never describe printer upload/start as fully supported until automated tests, owner acceptance and real hardware validation of the exact printer and adapter have passed. Bambu upload/print, FlashForge multi-material start and Anycubic native transfer/start remain unimplemented. Creality K2 CFS mapped print-start is implemented in the draft branch but has not yet passed physical hardware acceptance.


## K1 firmware 1.3.5.22 diagnostic evidence (2026-11-05)

Two supervised, pre-safeguard native K1 start attempts were followed by an OS
reboot at approximately 14:35 and 14:49 (printer-local clock). The current K1
native start guard must **remain enabled**; do not send another print-start
command for this investigation.

The private K1 diagnostics show that its web server received `opGcodeFile`
for existing `/usr/data/printer_data/gcodes/*.gcode` files, accompanied by
`enableSelfTest: 0` in the older request. The master service selected those
files and itself sent `BOX_ENABLE_CFS_PRINT ENABLE=0` to Klipper, which
reported an unknown command. Creality continued into `CX_ROUGH_G28` and
heater preparation. Approximately 28 seconds later, the Klipper socket was
unavailable; the system uptime independently indicates a reboot. This narrows
the failure window but does **not** prove the unknown CFS command, homing
macro, or optional self-test flag caused the reboot. No definitive kernel
panic/watchdog signature survives in the provided persistent logs.

A read-only `reqGcodeFile` request generated `retGcodeFileInfo2` file-list
data with `name`, absolute `path`, `file_size` and `create_time` fields
on this firmware. K1 listing now uses a plain WebSocket session, accepts
intervening telemetry/heartbeats, and validates the returned absolute path.
K2 WebSocket settings remain independent. Regression fixtures use a minimal
sanitised representation; **never commit the full diagnostic archive**, which
contains potentially sensitive Creality service and network data.

Follow-up validation:
1. Run backend tests and staging checks. Confirm that the K1 reports
   `blocked=True`, `can_start=False` while upload-only remains available.
2. Perform a **read-only** K1 file browser check against existing files;
   compare names and sizes to Creality's own file view. No print-start.
3. Separately investigate whether the firmware's preparation thread,
   Klipper/MCU, or supervisor triggers the reboot. Preserve crash evidence.
4. Revisit native start only with a reviewed, supervised hardware test plan;
   never enable it merely because file browsing works.


## K1 native start — ordinary owner-controlled testing (2026-11-05)

The temporary staging-only `k1_native_start_test_enabled` switch and
separate crash-risk checkbox have been retired. K1 native print-start now
follows the same explicit file selection, readiness checks and final
confirmation as other single-spool printer starts. Existing legacy test
switch values are ignored.

The stock K1 start uses the minimal `opGcodeFile` command, without
`enableSelfTest`, using the K1 `/usr/data/printer_data/gcodes/` path.
K2 CFS protocols remain independent. Printing requires a current online,
idle native snapshot, fresh no-CFS status, no recovery condition, and
confirmation that the selected file exists. Pending or uncertain submissions
are tracked to avoid duplicate command dispatch. A send is never treated
as print success without correlated live printer telemetry.

**Hardware warning:** Two earlier K1 print starts caused operating-system
reboots during Creality print preparation. Removing the redundant test
configuration does not establish that the firmware issue is fixed.
Supervise any further K1 test and preserve logs if the printer restarts.
