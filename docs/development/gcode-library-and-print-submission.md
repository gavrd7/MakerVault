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

## Printer upload and print — phase 3 (not implemented by phase 1)

Use dedicated, per-adapter file-upload APIs (Moonraker/Klipper, OctoPrint, and separately verified Creality local transport). Existing Pause/Resume/Cancel controls do not imply file upload or start capabilities. Other adapters remain disabled until validated.

- **Upload only** transfers the selected immutable file to the printer; it must not start a job.
- **Upload & start print** is a separate, explicit confirmed action, with a fresh printer-state check immediately before dispatch.
- The server retains an immutable audit/attempt record with selected file SHA-256, destination printer/connection, capability verdict, operator and status; unknown outcomes are never silently retried.
- The service must guard against endpoint substitution, SSRF, stale printer identity, duplicate submissions, disconnection and partial transfers; follow existing owner/role checks.
- Never execute arbitrary uploaded G-code inside the MakerVault container and never deduct inventory simply because a file was uploaded or a print started.
- Protect against concurrent starts, busy printers and cross-model incompatibility; default to fail closed if the adapter cannot prove a safe state.

## Acceptance tests

Verify multi-user file isolation; standalone/project references; optional G-code on model revisions; editor immutability; binary/truncated file behaviour; valid/invalid G-code metadata; source/target K2 vs K1 mismatch; no-model metadata; unsafe commands; active/busy/stale/disconnected printer states; permission/HTTPS/adapters; upload-only not starting; print only after explicit confirmation; idempotency and partial failures. Physical upload/start testing requires real printer hardware and should not rely only on mocked API calls.

**Release gate:** Phase 1 is a storage/inspection foundation. Do not describe upload-to-printer, compatibility rejection or direct printing as delivered until the separate submission implementation and hardware tests have passed.
