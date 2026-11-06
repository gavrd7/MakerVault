# MakerVault Slicer — implementation architecture and acceptance plan

Milestone: [Self-hosted multi-engine FDM slicer #156](https://github.com/gavrd7/MakerVault/issues/156).
Prerequisite: v1.6.0 [G-code Library & Print Submission #155](https://github.com/gavrd7/MakerVault/issues/155), merged and completed.

## Product boundaries

Provide **one MakerVault Slicer UI** for an explicitly selected engine and pinned version. Keep the toolchain **entirely self-hosted**. MakerVault owns the UI, authorization, job state, profiles and links to existing private assets. The optional slicing service executes in its **own isolated worker**, not in the web/Gunicorn or existing Celery process. No MakerVault cloud service or external slicer account is necessary.

The G-code output must return through the existing owner-scoped FileAsset versioning pipeline and can then be inspected, saved/downloaded or submitted to a compatible printer using the existing **explicit start** workflow. Completing a slice **never starts a print** or deducts spool inventory.

## Delivery order

### A. Provider-neutral contract, engine inventory and permission model
- Register engine identities independently from the executable path or CLI flags.
- Expose candidates without claiming an installation or engine version is available. Administrative approval requires a **tested, exact version and container image digest**, then marking the engine enabled.
- Keep engine-native machine/process/filament profiles distinct. Preserve original files, inheritance relationships, and upstream provenance.
- Model an owner-scoped SliceJob with immutable input model revision/asset references; selected engine/version, printer/nozzle/plate, process preset, physical spool selections *separate from* per-engine filament profiles; progress, state, output G-code FileAsset, warnings and redacted failure category.
- Restrict job creation, changes and file downloads by owner/role/quotas. Disallow input URLs and arbitrary host filesystem paths.

### B. Optional isolated slicing service
- Independent Compose **profile**: normal app deployments remain unchanged until the administrator opts in.
- Worker receives only scoped, immutable input artifacts and validated profile files; avoid database credentials, Docker socket, host root, or general MakerVault file mounts. Use limited authenticated service-to-service exchange or a short-lived one-job staging mount.
- Container isolation: unprivileged user, read-only filesystem except bounded scratch, no new privileges/capabilities, non-root, per-engine CPU/RAM/PID/disk/time caps, egress denied where feasible, and pinned image digests.
- Stage input locally with fixed filenames under a unique job directory; invoke an approved preconfigured executable with an **argument list, never a shell command**, and only allowlisted flags. Prevent arbitrary profile paths/flags and cap stdout/stderr. Terminate the entire process group on timeout/cancellation.
- Validate the produced G-code as an expected bounded file, scan using the existing G-code inspector, and import to the private FileAsset store. No background auto-dispatch to printers.
- Jobs must survive worker restart: queued/running/completed/failed/cancelled/stale; abandoned running jobs are reconciled without duplicate execution.

### C. First end-to-end slicer: OrcaSlicer (default)
- Verify an exact digest-pinned OrcaSlicer headless build and its native printer/process/filament JSON settings against a controlled STL fixture.
- Keep the worker command path and profiles independent from Prusa. Validate actual output G-code and ensure required settings are present.
- Build the initial single-plate MakerVault UI with printer/nozzle, physical spool linked to separate native filament preset, process controls and a Slice button.
- Complete queue/progress/error handling, private G-code import, and **Print from slicer** through the existing explicit printer-submission modal.

### D. Additional engine order and distinct verification
1. **Creality Print** — second priority, verified headless CLI and native JSON presets; integrate K1/K2 profile options where appropriate.
2. **Bambu Studio** — third, separate native JSON/profile and license checks.
3. **PrusaSlicer** — fourth. Existing isolated runner prototype stays as reusable development groundwork, but is not the primary engine or an automatically installed service.
4. **Snapmaker Orca** — fifth, validated independently rather than assumed compatible with OrcaSlicer.
5. **Others** — CuraEngine, ElegooSlicer, Anycubic Slicer Next and sensible integrations for supported printer adapters, each conditional on real CLI/profile/license validation.

### E. Enhanced plate, profiles and multi-material
- Model placement and transforms with server-validated build-volume bounds, units and plate orientation.
- Multiple objects, multiple material/extruder assignments, supports and user-editable searchable groups: Quality, Strength, Speed, Support and Multimaterial. Keep process and profile provenance explicit.
- Link selected MakerVault physical spools to engine-native filament definitions. **Spool identity is not a slicer preset**; an exact material profile is chosen separately.
- Preserve source/derived G-code provenance and support re-slice without modifying prior assets.
- Reuse v1.6.0 K2 CFS mapping on *subsequent explicit print submission*, never as a hidden slicing side effect.

### F. Additional engines only after genuine CLI/licence verification
Creality Print, Bambu Studio, PrusaSlicer, Snapmaker Orca, CuraEngine, ElegooSlicer and Anycubic Slicer Next are ordered candidates rather than automatically active or installed integrations. Validate distribution terms, headless CLI availability, profile compatibility and model-specific behaviour independently.

## Initial work in this branch

- `core.slicer_engines` defines the ordered **candidate** engines. The registry is deliberately non-executable and returns `available=false`; it does not install a slicer or advertise a usable slicing service.
- `validate_engine_selection` requires an externally provided administrator-verified worker inventory containing an exact engine version, explicit enablement, successful verification and pinned SHA-256 image digest. The inventory must come from trusted server state, never from a browser request.
- Contract unit tests assert unsupported inputs fail closed and Orca/Prusa profile formats remain distinct.

## Implementation status — private drafts, native profiles and gated slicing

The draft branch now contains a preparation workbench in **3D Printing → MakerVault Slicer**, owner-scoped SliceJob records (migration 0076), native SlicerProfile records (0077) and exact engine/version/profile references (0078). It supports existing STL and printer selections, optional physical spool references, import of original Prusa INI or Orca JSON presets, persisted draft configurations and job status. Imported profiles remain **candidate/unverified**.

The Orca-first optional isolated worker adapter, alongside the retained lower-priority PrusaSlicer prototype, one-shot authenticated dispatch, fixed CLI invocation, bounded input/output, no-root capabilities and private G-code FileAsset import are implemented in source. A **Slice now** action is enabled only when an explicitly installed, approved worker and all three verified native profiles pass server-side admission. Print submission and spool deduction remain wholly separate operations.

### Print directly from the slicer

Once a slice completes and its output has been saved privately in the G-code Library, the completed job offers **Print from slicer** (subject to the existing printer-control permission). The shortcut selects the original slice job's owned printer and exact output FileAsset, and opens the existing `PrinterStartGcodeModal` in **Upload and start print** review mode. If more than one enabled printer connection exists, the user chooses which adapter to use. Unsupported adapter capabilities, model/material mismatches, unreadiness, permissions and K2 CFS mapping are handled by the unchanged v1.6.0 printer-submission workflow.

**There is no silent start** after Slice, and no separate slicer-specific printer command or upload implementation. The existing submission modal still requires an explicit final confirmation and records the normal durable submission receipt. Users may instead open the generated G-code in the library. The G-code asset is retained even if printing is cancelled or the connection is unavailable.

The opt-in Compose overlay requires a strong internal worker token and exact engine version. The MakerVault service also requires an explicit execution flag, a worker image reference containing `@sha256:` and an exact matching digest. The backend rejects mismatches or an unready worker. These settings do **not** substitute for independent binary security and real fixture validation.

**OrcaSlicer is the default and highest execution priority; the real slicer is not yet ready to run:** no tested digest-pinned slicer engine image or approved machine/filament/process fixture library is bundled. The user cannot approve profiles from the browser. Before enabling execution we must verify the exact CLI build and licences, run a known STL fixture end-to-end inside the isolated worker, audit sandbox limits and recovery, and validate the generated G-code against the slicer settings.

Orca real-engine fixture validation, interactive build plate manipulation, searchable Basic/Simple/Advanced controls and multi-material support remain pending. The Orca CLI adapter has been implemented in source; this is not proof of a successful real-engine slice. The [dedicated worker contract CI](../../.github/workflows/slicer-contract.yml) and Django/frontend checks cover code contracts, not real slicing.

## Orca-first verification and recovery checkpoint (6 November 2026)

**Engine order:** OrcaSlicer (default) → Creality Print → Bambu Studio → PrusaSlicer → Snapmaker Orca → other printer-relevant engines. The Orca-specific runner has native JSON/CLI staging and file checks, but real CLI slicing remains unverified until a pinned worker image and native profiles complete a fixture run. Neither a mocked runner test nor a profile import demonstrates a working slicer.

The branch now includes `slicer_worker/verify_orca.py`, which runs one real Orca CLI fixture **only inside an approved isolated container**. Feed it a known STL and complete engine-native machine, filament and process profile files; it returns SHA-256 checksums and bounded output metadata while explicitly setting `approved_for_production=false`. This receipt must be reviewed against the actual expected printer/material settings before installation can be approved.

**Native Orca inheritance:** profile JSON may specify `inherits`, which can refer to a vendor/system preset not present in the isolated worker. Import preserves this metadata as an unverified candidate; the current worker rejects such unresolved children rather than silently slicing with wrong defaults. Implement a trusted, versioned native parent-bundle resolver and test with real vendor profiles before enabling inherited presets. Avoid lossy automatic conversion to Prusa INI.

**Worker recovery:** draft and queued jobs can be cancelled before a worker claims them (separate permission required); running jobs cannot yet be cancelled because a safe remote process-termination protocol is not installed. The administrative command `python manage.py reconcile_slice_jobs` marks queue entries older than 30 minutes and running entries older than 25 minutes as **stale** without retrying them. A late worker output cannot replace a stale job. The optional worker now answers health checks independently but limits execution to one concurrent slice.

**Deployment status:** No engine image or profiles are automatically downloaded, installed or enabled by normal MakerVault updates. Worker execution remains opt-in and depends on exact pinned image/version, matched runtime health and admin-approved native profile records. Real Orca fixture execution, worker container integrity, licence/SBOM review and profile-approval tooling remain prerequisites before user testing.

## Safety and release gates

1. Verify service isolation and no untrusted model/profile can escape a job sandbox, access the network/secret mounts or run arbitrary CLI flags.
2. Per-owner access checks for inputs, outputs, worker/job status, and selected printer/spool IDs.
3. Size/triangle/file-count quotas; input parsing timeouts; archive and decompression protections; no direct URL import into a worker.
4. Explicit cancellation; bounded runtime; jobs recover after crash without duplicate or accidental print actions.
5. Reproducible pinned-engine build/installation documentation, licensing and dependency/SBOM checks.
6. Physical printer testing for optional submission is separate from slicer-output validity. No automatic printing or automatic spool deduction.
7. Container creation and installed engine downloads are **explicit admin actions only**; ordinary MakerVault updates must not silently install engines.

## Implementation notes / research

- [OrcaSlicer CLI actions](https://github.com/OrcaSlicer/OrcaSlicer/wiki/cli_actions) and [loading machine/filament profiles](https://github.com/OrcaSlicer/OrcaSlicer/wiki/cli_misc).
- [PrusaSlicer CLI](https://github.com/prusa3d/PrusaSlicer/wiki/Command-Line-Interface), including `--export-gcode`. Linux distribution/build approach needs validation for the selected pinned version.
- Upstream licence for PrusaSlicer and OrcaSlicer must be checked **per distributed binary/source/version**, not inferred only from the public repository homepage.

The full slicer is a new major milestone and is not included in v1.6.0. Keep the milestone open until an end-to-end, isolated, hardware-appropriate slice workflow is verified.
