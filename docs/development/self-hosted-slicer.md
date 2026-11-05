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

### C. First end-to-end slicer: PrusaSlicer
- Test a **specific version** of PrusaSlicer headless CLI and native INI profiles, verify licences/distribution, and record an automated fixture: known small STL + machine/process/filament presets → bounded G-code with expected metadata.
- Show a model and single plate, printer and nozzle, one actual spool reference paired to one native filament profile, process preset, Basic/Simple/Advanced settings and a Slice button.
- Report queue/progress/errors, create a new private G-code asset, and open the existing viewer. Separate download / Save / Submit-to-printer actions.

### D. Second engine: OrcaSlicer
- Verify a pinned headless build and its specific CLI invocation with native machine/process and filament JSON profiles. Do not translate Prusa INI to Orca JSON by approximation.
- Reuse the same UI contract with engine-specific preset choice and settings. Validate an actual Orca test fixture before enabling.

### E. Enhanced plate, profiles and multi-material
- Model placement and transforms with server-validated build-volume bounds, units and plate orientation.
- Multiple objects, multiple material/extruder assignments, supports and user-editable searchable groups: Quality, Strength, Speed, Support and Multimaterial. Keep process and profile provenance explicit.
- Link selected MakerVault physical spools to engine-native filament definitions. **Spool identity is not a slicer preset**; an exact material profile is chosen separately.
- Preserve source/derived G-code provenance and support re-slice without modifying prior assets.
- Reuse v1.6.0 K2 CFS mapping on *subsequent explicit print submission*, never as a hidden slicing side effect.

### F. Additional engines only after genuine CLI/licence verification
Creality Print, Bambu Studio, CuraEngine, ElegooSlicer, Snapmaker Orca and Anycubic Slicer Next are future candidates, **not** active integrations. Validate distribution terms, headless CLI availability, profile compatibility and model-specific behaviour independently.

## Initial work in this branch

- `core.slicer_engines` defines the first two **candidate** engines. The registry is deliberately non-executable and returns `available=false`; it does not install a slicer or advertise a usable slicing service.
- `validate_engine_selection` requires an externally provided administrator-verified worker inventory containing an exact engine version, explicit enablement, successful verification and pinned SHA-256 image digest. The inventory must come from trusted server state, never from a browser request.
- Contract unit tests assert unsupported inputs fail closed and Orca/Prusa profile formats remain distinct.

## Implemented checkpoint — draft jobs and restricted worker contract

- SliceJob model and migration 0076: owner-scoped input FileAsset, printer, optional physical spool, independent printer/process/filament preset references and durable state fields.
- Authenticated `/api/printing/slicer/engines/` (informational) and `/api/printing/slicer/jobs/` (drafts only) plus owner-scoped job detail and deletion. Drafts do not execute, schedule, send commands or deduct spool stock. Engine availability is false until verified worker inventory exists.
- `slicer_worker/runner.py` is an **unconnected worker-side Prusa CLI contract** with fixed file names, allowlisted arguments, post-processing script rejection, timeout/process-group cleanup, bounded output, and suppressed raw engine logs. No web or Celery code launches this runner.
- Worker contract tests run in dedicated CI. Engine/version/profile compatibility and the optional restricted container remain **not yet validated**.

**Do not run untrusted slicer input on the host.** The runner is not a security sandbox; a separate unprivileged, network-restricted, resource-limited container and trusted native profile installation are required before an actual Slice button is enabled.

## Native-profile checkpoint

The draft-only Slicer Workbench is available from **3D Printing → MakerVault Slicer** on the feature branch. It uses existing owned STL files, printers and physical spools and stores private draft configurations through `/api/printing/slicer/jobs/`. Slicing itself is deliberately unavailable.

The backend now has `SlicerProfile` (migration `0077`) and per-job native profile references (migration `0078`) in addition to the `SliceJob` migration `0076`. Profiles are linked to existing owner-scoped FileAsset versions, preserve engine, version, printer/filament/process role, source label and checksum, and default to **candidate/unverified**.

The `/api/printing/slicer/profiles/` endpoint registers and lists native PrusaSlicer `.ini` and OrcaSlicer `.json` assets. Import performs bounded UTF-8/JSON checks, ownership checks and post-processing command rejection. Registration does **not** verify actual slicer compatibility or permit execution. When a draft selects a profile, its owner, engine, version, kind and name must all match.

The separate `slicer_worker/runner.py` prototype uses fixed, bounded files and a hard timeout for a Prusa CLI invocation, with post-processing disabled and raw engine logs suppressed. A dedicated GitHub Actions workflow runs its Python contract tests. It is not connected to the web app or Celery and must **not** be used on an unisolated host with untrusted input.

**Engine version research (5 November 2026):** PrusaSlicer 2.9.7 is the preferred *candidate* because upstream published security fixes on 2 November; the Debian trixie package is still older. Neither source nor runtime has been vetted as a redistributable, pinned sandbox image. Do not use a mutable latest tag or silently fall back to the distro package.

**Missing before real execution:** separately installable restricted container, version+digest verified engine, admin-approved native profile inventory, safe per-job staging, authentication/queue dispatch, output validation/import to private G-code assets and end-to-end slicer UI/acceptance tests. No printer action or physical spool deduction is coupled to slicing.

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
