## Enable OrcaSlicer on a dedicated staging installation (experimental)

This is the **first installable staging engine**, not a supported production release or the planned in-app engine installer. It obtains the exact OrcaSlicer **v2.4.2 Ubuntu 24.04 x86_64 AppImage** from the official GitHub release, requires a matching `sha256:` digest in GitHub's release metadata, builds a local worker container, and produces a private file containing an immutable image ID, binary hash and strong worker token.

On the Debian staging host (Docker access required):

```bash
cd ~/MakerVault-Staging
git pull --ff-only origin feature/self-hosted-slicer-foundation
sudo python3 scripts/install_slicer_staging.py prepare-orca
sudo python3 scripts/install_slicer_staging.py enable
sudo python3 scripts/install_slicer_staging.py status
```

### Build files and Compose overlays

All worker packaging files are maintained on this development branch:

| File | Purpose |
| --- | --- |
| `slicer_worker/Dockerfile.bundle` | Build the rootless, isolated worker with separately verified official slicer binaries |
| `slicer_worker/Dockerfile.bundle.dockerignore` | Only copy worker code and explicitly staged binary assets into the worker build |
| `slicer_worker/stage_engines.py` | Validate official AppImage digests and create a local engine manifest |
| `scripts/install_slicer_staging.py` | Prepare, build, enable, update, inspect or disable the staging worker |
| `compose.slicer.staging.yaml` | Connect the pinned worker to MakerVault without exposed ports or extra app privileges |
| `compose.slicer.yaml` | Explicit optional production-style overlay; requires an independently approved image |

The regular `compose.yaml` intentionally has no enabled slicer service.
The optional staging overlay is **required** alongside the ordinary app
Compose files. The standard three-file app rebuild alone cannot preserve
the slicer worker's environment and internal network connection.

**After the slicer has already been installed and enabled**, use the
following command for ordinary MakerVault updates (not `prepare-orca`
or `refresh-worker`):

```bash
cd ~/MakerVault-Staging
git pull --ff-only origin feature/self-hosted-slicer-foundation
sudo python3 scripts/install_slicer_staging.py update
sudo python3 scripts/install_slicer_staging.py status
```

The `update` action validates the full Compose configuration, rebuilds
the MakerVault application and keeps the existing pinned worker image,
binary approval hashes and private token unchanged. Use
`sudo python3 scripts/install_slicer_staging.py refresh-worker` only when
the worker code itself needs rebuilding. It checks the staged binary
digest, builds a new immutable worker image and updates the private image
ID before recreating the service.

**For a first-time installation**, the exact three commands shown above
under 'Enable OrcaSlicer' (`prepare-orca`, `enable`, `status`) are
still required. App updates do not automatically download or install
third-party slicing engines.

The `enable` command uses the regular `compose.yaml`, `compose.build.yaml` and (when present) `compose.staging.yaml` plus the isolated `compose.slicer.staging.yaml` overlay. It updates the staging app and brings up the optional worker together. **Subsequent staging rebuilds must use this same overlay and environment file** or the worker settings will be omitted from the application container:

```bash
sudo docker compose --env-file .env --env-file .slicer-staging.env \
  -f compose.yaml -f compose.build.yaml -f compose.staging.yaml \
  -f compose.slicer.staging.yaml up -d --build
```

The installer also works when `compose.staging.yaml` is absent, but that example assumes your existing staging overrides. Never commit or share `.slicer-staging.env`; it contains a secret worker token. The downloaded engine assets are kept outside the standard app Docker build context. The worker has no exposed network port, no host file mounts and no access to printer credentials, PostgreSQL or Redis.

**After installation**, sign in as a MakerVault administrator, select OrcaSlicer v2.4.2, import compatible K1/K2 printer, filament and process profiles (including their native parent presets), and use **Test slice and approve**. Only a real fixture that produces valid G-code can approve that exact profile set. Then use **Save and slice** on a model. No printer starts automatically. The official AppImage itself is still unverified until this end-to-end test succeeds; a healthy worker is only a binary-identity check, not a promise that slicing will work.

To turn the staging engine off without removing its files:

```bash
sudo python3 scripts/install_slicer_staging.py disable
```

This staged installer currently targets **OrcaSlicer only**. Creality Print remains supported by the worker adapter and candidate image tooling, but does not yet have a verified official headless Linux release to offer for one-command installation. No installation is initiated from a browser because the web application intentionally does not have Docker host privileges.

# MakerVault Slicer — implementation architecture and acceptance plan

Milestone: [Self-hosted multi-engine FDM slicer #156](https://github.com/gavrd7/MakerVault/issues/156).
Prerequisite: v1.6.0 [G-code Library & Print Submission #155](https://github.com/gavrd7/MakerVault/issues/155), merged and completed.

## Product boundaries

Provide **one MakerVault Slicer UI** for an explicitly selected engine and pinned version. Keep the toolchain **entirely self-hosted**. MakerVault owns the UI, authorization, job state, profiles and links to existing private assets. The optional slicing service executes in its **own isolated worker**, not in the web/Gunicorn or existing Celery process. No MakerVault cloud service or external slicer account is necessary.

The G-code output must return through the existing owner-scoped FileAsset versioning pipeline and can then be inspected, saved/downloaded or submitted to a compatible printer using the existing **explicit start** workflow. Completing a slice **never starts a print** or deducts spool inventory.

## Staging-only workbench preview (no slicer container)

For UI testing **before** a verified slicer engine has been packaged, a deployment can opt into the preparation interface without installing the slicer service. Set `MAKERVAULT_SLICER_PREVIEW_ENABLED=1` in the staging `.env`, rebuild/recreate the main MakerVault service, and sign in with a **superuser** account. This flag defaults to `0` and only affects the authenticated frontend's workbench access; it does not enable the worker, engine installation or slicing.

The UI explicitly identifies **Workbench preview — no slicer engine installed**. It allows inspection of the plate, model imports and draft/profile preparation, but no job can be queued without the existing approved worker and native profile gates. Do not confuse a successfully saved draft with a completed slice. The normal no-slicer fallback remains in effect for non-superusers and whenever the flag is disabled.

To return to normal optional-installation behaviour, remove the environment setting (or set it to `0`) and recreate the app service. This preview flag is for staging, not a production installation route.

## Optional installation and navigation fallback

MakerVault's slicer container(s) are **optional**. The main 3D Printing page and G-code workflows remain usable without any slicer worker.

The authenticated engine discovery API reports two separate signals: `deployment_enabled` means an administrator explicitly enabled slicing execution, while `worker_configured` means an approved, verified worker currently passes admission and health checks. The frontend uses these signals to disable **MakerVault Slicer** in the main navigation and to show an explanatory unavailable panel in 3D Printing:

- Execution not enabled: **No slicer installed or enabled**; the workspace cannot be opened.
- Enabled but not verified/healthy: **Slicer service unavailable**; check worker, binary identity and profile configuration rather than implying the user declined installation.
- API unreachable or status unknown: fail closed, without suggesting the engine is installed.
- Healthy and approved worker: navigation and preparation workbench become accessible; per-job profile verification and permissions still control execution.

The status is checked at page load and every 60 seconds. An already-open slicer workspace also falls back to an unavailable message if a subsequent status refresh reports loss of the worker. This is a UI affordance only; backend job admission remains fail closed independently.

## Candidate worker image from reviewed Linux AppImages

This is a **developer-only, local acceptance-test image**, not the finished GUI engine installer. Download an exact Linux AppImage directly from the official <https://github.com/OrcaSlicer/OrcaSlicer/releases> and/or <https://github.com/CrealityOfficial/CrealityPrint/releases>, and independently verify the expected SHA-256. Do not copy third-party executables into the Git repository.

From the MakerVault source checkout, with the local approved files available:

```bash
python3 -m slicer_worker.stage_engines \
  --engine orcaslicer 2.4.2 /path/to/OrcaSlicer.AppImage VERIFIED_64_CHARACTER_SHA256
# Alternatively: --engine crealityprint <tested-version> /path/to/CrealityPrint.AppImage VERIFIED_SHA256
# Or supply both --engine groups together in one command.

docker build -f slicer_worker/Dockerfile.bundle \
  -t makervault-slicer-candidate:local .
```

The optional Dockerfile has its own restricted build-context rules, and the root Docker ignore rules exclude `slicer-engine-assets/` from ordinary MakerVault application builds. This prevents third-party executables from being accidentally sent with the main application's build context.

The staging tool verifies all requested hashes **before copying**, refuses symlinks, duplicates and nonempty output directories, then writes a locally ignored `slicer-engine-assets/` directory and two suggested JSON configuration maps (one for the worker and one for app-side approval). Its status is **staged_not_tested**, not approved. Both engines are independent; no Orca installation is required for a Creality-only test.

To test without joining the MakerVault network, place three verified, self-contained native engine profiles (printer, filament and process JSON) in an isolated fixture directory on the test host. Then run:

```bash
docker run --rm --network none --read-only \
  --cap-drop ALL --security-opt no-new-privileges \
  --pids-limit 96 --memory 3g --cpus 2 \
  --tmpfs /tmp:rw,nosuid,size=1g \
  --mount type=bind,src=/absolute/path/to/fixtures,dst=/fixtures,readonly \
  makervault-slicer-candidate:local \
  python3 -m slicer_worker.probe \
    --engine orcaslicer --version 2.4.2 \
    --binary /opt/engines/orcaslicer.AppImage \
    --printer /fixtures/printer.json \
    --filament /fixtures/filament.json \
    --process /fixtures/process.json
```

Use matching `crealityprint` flags, binary and Creality-native profiles when testing Creality. A successful receipt verifies one engine/version/profile set in that specific environment, but **does not validate all printer types**. A nonzero exit may indicate an upstream GUI/CLI regression, missing Qt/GL runtime dependency, unsupported AppImage extraction, an inherited/invalid profile, or no generated extrusion. Never relax isolation or enable printing automatically just to make the command pass. Build/runtime dependencies and licence obligations must be reviewed before producing a redistributable image. This path does not automatically integrate a local image into MakerVault's pinned production image approval gate.

## Real engine binary acceptance test (no activation)

Before an engine is made available in the slicer settings, use the **offline acceptance probe** inside a disposable, restricted Linux test container that already contains an independently reviewed OrcaSlicer or Creality Print executable and its **resolved**, matching K1/K2 printer, filament and process JSON profiles. Nothing is downloaded or installed by the probe.

Example with an independently obtained engine and profile files:

```bash
python3 -m slicer_worker.probe \
  --engine orcaslicer --version 2.4.2 \
  --binary /opt/engines/orcaslicer \
  --printer /fixtures/printer.json \
  --filament /fixtures/filament.json \
  --process /fixtures/process.json
```

Run the same test with `--engine crealityprint`, its own version/binary and **Creality-native** JSON profiles. The command uses the exact production runner, a small tetrahedron STL, a hard timeout and G-code validation. On success it prints a JSON receipt containing the binary SHA-256, three input profile SHA-256s, G-code SHA-256, output size and fixture identity. The process exits nonzero if the binary cannot launch, the CLI stalls, a profile is rejected, no G-code is created or no extrusion moves are found. Because a source executable is untrusted until audited, this test must **not** run on the MakerVault web host or with printer credentials.

Both GUI-derived engines are started with an isolated, fixed **Qt offscreen** environment, Mesa software rendering, temporary private XDG paths and AppImage extraction enabled (so FUSE is not assumed). The worker deliberately does not inherit the host desktop session, proxy environment, dynamic-loader injection variables or application credentials. This improves the chance of headless operation but **is not proof** that a particular upstream release works inside the chosen Linux image; the real fixture remains mandatory. Linux build images must include the required GUI/Qt runtime libraries without exposing a desktop session or the MakerVault container to the engine.

**A passing probe is evidence, not an automatic engine approval.** Verify the binary came from the official upstream distribution; review the relevant licence, dependencies and container isolation. Record the image digest, exact binary hash, profile identities and test receipt. Do not equate the worker's binary-hash health check with successful slicing or activate the production configuration until the administrator fixture approval and release acceptance checks pass. Production deployment must ultimately provide this same preflight through the MakerVault administrator GUI.

## OrcaSlicer + Creality Print shared-worker prototype

The first two target engines are now **OrcaSlicer and Creality Print** (PrusaSlicer remains an engine candidate and legacy worker adapter). A **single worker process** can enumerate independently pinned executables and select the requested engine at job dispatch time.

At worker startup, the administrator can provide `SLICER_ENGINES_JSON`, a JSON object keyed by engine ID. Each entry requires only `binary` (absolute path inside the worker), `version` and `binary_sha256`. The application-side admission gate independently requires `MAKERVAULT_SLICER_ENGINES_JSON` mapping each approved engine to its exact `version` and `binary_sha256`, along with the existing **single pinned container image digest** and explicit execution enablement. Worker health reports each verified engine separately, and invalid or absent engines never become executable.

These environment variables are **low-level experimental security controls, not installation instructions**. The finished single-container installation, administrator-managed engine installer, provenance catalogue, persistent engine storage, and version-specific binary/fixture receipts remain outstanding. Do not enable the worker with arbitrary executables, checksum-only fixtures, unverified images or manually guessed presets. Engine health validates identity, **not slicing correctness**.

The Creality adapter uses upstream Creality Print's documented `--slice 0`, `--outputdir`, `--load_settings` and `--load_filaments` arguments. Its CLI is **not** treated as an alias for OrcaSlicer. Upstream Creality Print 7.3.0 issue #634 reports that command-line slicing can open the GUI and never return G-code on Windows. No version is declared production-verified until a real Linux headless fixture successfully emits bounded G-code and its printer/material/process profiles are approved. This is especially important for K1/K2/CFS compatibility.

Both engine runners forbid post-processing hooks and unbundled parent profiles; preserve per-engine native files; run without shell execution or arbitrary user flags; enforce timeouts; require one bounded G-code output; and never issue printer commands or change filament inventory.

The GUI must remain **fully usable without running the original slicer desktop GUI**: engine install/update management, searchable/editable native profiles, multi-object build plate, slicing controls, toolpath preview, slice progress, output and explicit print submission. The current preparation interface and worker adapters do **not** yet meet this complete acceptance criterion.

## Agreed release deployment design (supersedes prototype overlay)

The supported release target is **one optional slicing-service container defined within the normal `compose.yaml`**, commented out by default. Do not require Docker Compose profiles or a separate `compose.slicer.yaml` in the finished release. The current overlay remains a developer-only prototype until replaced.

Slicing engines are independently installable and independently verified **inside that one service**. A Creality Print-only installation must not depend on OrcaSlicer being installed. The service must discover installed engine/version identities, route each job to its explicitly selected approved engine, and prevent a missing or failing engine from disabling unrelated verified engines. The prototype's single `MAKERVAULT_SLICER_ENGINE` setting is **not** the final multi-engine solution.

Implement explicit administrator-managed engine install, upgrade, removal and rollback with reviewed distributions, licences, pinned binary hashes, worker image identity, persistence and audited per-engine fixtures. No automatic installation or blind updates. Per-engine independent process isolation within a shared container needs dedicated security review.

User-facing guidance: [Slicer installation and engine management](../guide/3d-printing/slicer.md). Do not present the future commands as available before an approved release.

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
5. **ElegooSlicer** — independently validated ELEGOO-native profiles and slicing behaviour, even where the codebase shares OrcaSlicer ancestry.
6. **UltiMaker Cura / CuraEngine** — integrate the Cura slicing backend and compatible native definitions without assuming the full GUI can run headlessly.
7. **Anycubic Slicer Next** — independent engine-native printer/material presets and headless runtime validation, despite its OrcaSlicer lineage.
8. **Other candidates** — additional manufacturer slicers and sensible integrations for supported printer adapters, each conditional on real CLI/profile/licence validation.

### E. Enhanced plate, profiles and multi-material
- Model placement and transforms with server-validated build-volume bounds, units and plate orientation.
- Multiple objects, multiple material/extruder assignments, supports and user-editable searchable groups: Quality, Strength, Speed, Support and Multimaterial. Keep process and profile provenance explicit.
- Link selected MakerVault physical spools to engine-native filament definitions. **Spool identity is not a slicer preset**; an exact material profile is chosen separately.
- Preserve source/derived G-code provenance and support re-slice without modifying prior assets.
- Reuse v1.6.0 K2 CFS mapping on *subsequent explicit print submission*, never as a hidden slicing side effect.

### F. Additional engines only after genuine CLI/licence verification
Creality Print, Bambu Studio, PrusaSlicer, Snapmaker Orca, ElegooSlicer, UltiMaker Cura (via independently verified CuraEngine integration) and Anycubic Slicer Next are ordered candidates rather than automatically active or installed integrations. Validate distribution terms, headless CLI availability, profile compatibility and model-specific behaviour independently.

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

**Engine order:** OrcaSlicer (default) → Creality Print → Bambu Studio → PrusaSlicer → Snapmaker Orca → ElegooSlicer → UltiMaker Cura / CuraEngine → Anycubic Slicer Next → other printer-relevant engines. The Orca-specific runner has native JSON/CLI staging and file checks, but real CLI slicing remains unverified until a pinned worker image and native profiles complete a fixture run. Neither a mocked runner test nor a profile import demonstrates a working slicer.

The branch now includes `slicer_worker/verify_orca.py`, which runs one real Orca CLI fixture **only inside an approved isolated container**. Feed it a known STL and complete engine-native machine, filament and process profile files; it returns SHA-256 checksums and bounded output metadata while explicitly setting `approved_for_production=false`. This receipt must be reviewed against the actual expected printer/material settings before installation can be approved.

**Native Orca inheritance:** profile JSON may specify `inherits`, which can refer to a vendor/system preset not present in the isolated worker. Import preserves this metadata as an unverified candidate; the current worker rejects such unresolved children rather than silently slicing with wrong defaults. Implement a trusted, versioned native parent-bundle resolver and test with real vendor profiles before enabling inherited presets. Avoid lossy automatic conversion to Prusa INI.

**Worker recovery:** draft and queued jobs can be cancelled before a worker claims them (separate permission required); running jobs cannot yet be cancelled because a safe remote process-termination protocol is not installed. The administrative command `python manage.py reconcile_slice_jobs` marks queue entries older than 30 minutes and running entries older than 25 minutes as **stale** without retrying them. A late worker output cannot replace a stale job. The optional worker now answers health checks independently but limits execution to one concurrent slice.

**Binary verification:** worker readiness now verifies an exact `SLICER_ENGINE_BINARY_SHA256` against the actual installed executable rather than invoking an unverified Orca `--version` flag. This checksum is an integrity check, **not independent proof of the binary's claimed version, licence or safe behaviour**. Approval requires a reviewed release/build identity and successful real fixture receipt. The opt-in Compose overlay requires `MAKERVAULT_SLICER_ENGINE_BINARY_SHA256`; no default checksum is supplied.

**Deployment status:** No engine image or profiles are automatically downloaded, installed or enabled by normal MakerVault updates. Worker execution remains opt-in and depends on exact pinned image/version, matched runtime health and admin-approved native profile records. Real Orca fixture execution, worker container integrity, licence/SBOM review and profile-approval tooling remain prerequisites before user testing.

### Repeatable real-engine fixture

The source includes `slicer_worker/fixtures/tetrahedron.stl`, a small four-triangle, 10 mm tetrahedron with no vendor or printer dependencies. Inside a **reviewed, isolated and pinned** Orca worker image, pair it with the *exact matching version's* trusted complete native machine, filament and process exports:

```sh
python3 -m slicer_worker.verify_orca \
  --binary /path/to/verified/orca-slicer \
  --model slicer_worker/fixtures/tetrahedron.stl \
  --printer /verified-profiles/machine.json \
  --filament /verified-profiles/filament.json \
  --process /verified-profiles/process.json
```

The command records input/profile/output checksums and leaves `approved_for_production=false`. Review generated time/material/temperature/geometry metadata against the expected native presets; do **not** declare an engine validated from fixture completion alone. A multi-level vendor profile requires its complete, verified parent bundle before that fixture can run.

## Reviewed Orca worker and native-preset activation (not yet performed)

The implementation now includes an explicit, **dry-run-first** administrative approval path. It does not create or trust engine installations automatically. Do not attempt these steps on production without a separately reviewed, digest-pinned image and a real fixture-generated receipt.

1. Build/review the official Orca engine for the isolated worker, pin the container image `@sha256:` and the exact executable SHA-256, and verify its release identity, licence and dependencies.
2. Inside that isolated worker, run the existing `slicer_worker/verify_orca.py` utility with `--engine-version`, the committed tetrahedron STL and complete native machine/filament/process exports. Save its JSON receipt and **separately review actual emitted G-code and slicer settings**. A mock result does not count.
3. Import those three exact native profiles into the MakerVault owner's Files and Slicer profile catalogue. Their stored content hashes must equal the fixture receipt. Inherited profiles are not eligible until native parent-bundle execution is implemented and independently verified.
4. On the **trusted administrative host/container**, with the reviewed digest and binary hash configured, run:

```sh
python manage.py approve_slicer_fixture \
  --receipt /secure/reviewed-orca-fixture.json \
  --printer-profile UUID \
  --filament-profile UUID \
  --process-profile UUID
```

This checks all three profiles but makes **no changes**. Only after verifying the image, the complete generated G-code, the fixture receipt and the intended printer settings may the administrator rerun with `--approve`, `--acknowledge-image-reviewed`, `--acknowledge-gcode-reviewed` and `--expected-gcode-sha256` set to the independently reviewed output hash. The command refuses a different image digest, executable hash or engine version. Approval records an audit receipt on each profile; the runtime additionally rejects profile evidence belonging to another worker image.

The app remains disabled without `MAKERVAULT_SLICER_EXECUTION_ENABLED=1`. That flag **does not bypass** native-profile verification, exact hash checks or the normal separate printer-submission confirmation. This procedure is an acceptance specification, not a claim that a real engine run or security review has passed.

## Preparation UI: source geometry and native machine volume

The first workbench inspection stage is now implemented without installing a slicer:
- Selecting a private STL scans at most 32 MiB, validates binary or ASCII facet structure and displays measured X/Y/Z bounds and triangle count beside MakerVault's existing 3D model preview. An invalid file reports an inspection error; it is not silently accepted as printable.
- Selecting an imported Orca machine profile displays the `printable_area` polygon's bounding extent and `printable_height` when those fields are present in the original, checksum-verified native JSON. Missing or inherited machine presets are labelled incomplete/unavailable until their authentic parent chain is provided.
- These are **two independent read-only measurements**. They do not modify geometry, position an object on the plate, account for bed exclusions, detect nozzle crashes or certify that a slice/print can succeed. Real placement, orientation, volume compatibility and support generation remain tasks for the verified Orca engine and forthcoming interactive plate editor.
- Both inspection endpoints enforce FileAsset or SlicerProfile owner isolation, bound input sizes, and avoid passing arbitrary paths or execution options to a slicer.

## Native K1/K2 profile bundle audit — additional offline preparation

The upstream Orca profile candidates are recorded in `slicer_worker/fixtures/creality-orca-v2.4.2.json`. To check that a locally obtained **reviewed and pinned** Orca v2.4.2 resources tree contains the required original Creality machine, process and filament files and all their parent names, run:

```sh
python3 -m slicer_worker.verify_orca_bundle \
  --resources /trusted/orca/resources/profiles \
  --manifest slicer_worker/fixtures/creality-orca-v2.4.2.json \
  --output /tmp/orca-native-profile-audit.json
```

The read-only audit reports exact file hashes, missing or ambiguous parents and cycles. It searches the intended Creality category and the shared `OrcaFilamentLibrary` for filament ancestors, not unrelated vendor directories. It fails with a nonzero exit code when native parents are unresolved, and **never flattens profiles or marks them verified**. The audit is complementary to, not a substitute for, validating a real Orca CLI fixture and native engine/profile compatibility. The worker continues to reject inherited profiles until a separately verified bundle execution mechanism exists.

The fixed single-STL Orca invocation now includes `--load-defaultfila` for an unassigned single model and explicit `--mtcpp 500000` / `--mstpp 300` bounds, in addition to worker-level CPU, memory and wall-time limits. The HTTP worker bounds both active slicing (one job) and active request threads (eight), so probes cannot spawn unbounded threads.

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


## Printer-independent compatibility contract

**Printer support is not an allowlist of the developer's K1/K2 hardware.**
The K1 and K2 are CI acceptance fixtures only. MakerVault must allow a user
to configure any FDM printer supported by the chosen native slicing engine,
including user-defined and community machine profiles. It must not equate a
printer brand with an engine or require that MakerVault can connect to the
physical printer merely to generate G-code.

The compatibility contract has separate gates:

1. **Engine runtime:** install an individually version-pinned engine into the
   isolated worker; do not grant Docker socket access to the MakerVault app.
2. **Machine profile:** select or import an engine-native machine preset with
   the actual bed geometry, axes, firmware flavour, nozzle, start/end G-code,
   extruder setup and capabilities. Official, user and community profiles
   remain separate from execution approval and retain provenance.
3. **Material/process:** choose compatible native filament and process presets,
   resolving each engine's inheritance without mixing engine versions.
4. **Native verification:** evaluate limits for the exact engine version,
   irrespective of manufacturer or model; verify a real fixture slice and
   review its G-code. Known rule failures must never be auto-clamped.
5. **Optional print submission:** independently determine printer connectivity
   and upload/start capabilities via the selected printer adapter. A printer
   may be perfectly slicable while lacking an automated send/print adapter.

Vendor catalogue coverage, specialty build shapes, multi-extruder/toolchanger
settings, non-FDM technologies, safety-critical start G-code and firmware
dialects require further adapter/profile work and physical validation. A
successful K1/K2 test does not certify them. User-defined profiles must remain
possible, with explicit unsupported-capability feedback rather than silent
fallbacks. Machine-specific overrides must be saved as separately named,
unverified candidates; never edit an official profile in place.


## Cross-manufacturer parity across all slicer engines

**Scope:** all FDM slicing engines must accept manufacturer-neutral printer
selection and independently imported, engine-native printer/filament/process
profiles. Supported printer models are never a MakerVault brand allowlist.
Engine capability determines whether a particular native profile can actually
slice. Printer communication is a separate optional adapter.

| Slicer engine | Native profile format | Pinned official catalogue browser | Runtime acceptance |
| --- | --- | --- | --- |
| OrcaSlicer | Orca JSON | 65 upstream profile families, v2.4.2 | Real K1, K2 (K2 test-only setting), and Prusa MK4 fixture slices passed |
| Creality Print | Creality JSON | 36 upstream profile families, v7.3.0, including third-party/custom machines | Native discovery/import tests; physical and executable acceptance pending |
| Bambu Studio | Bambu JSON | Not yet integrated; manual native import available | Not validated |
| PrusaSlicer | Prusa INI | Not yet integrated; manual native import available | Not validated |
| Snapmaker Orca | Snapmaker Orca JSON | Not yet integrated; manual native import available | Not validated |
| ElegooSlicer | Engine-native profile handling requires verification | Planned; runtime and official profile catalogue not integrated | Not validated |
| UltiMaker Cura | Cura definitions / intent / quality settings require independent mapping | Planned; CuraEngine integration and official profile catalogue not integrated | Not validated |
| Anycubic Slicer Next | Engine-native profile handling requires verification | Planned; runtime and official profile catalogue not integrated | Not validated |

Source counts represent pinned upstream **catalogue families**, not printer
models, certified output, or execution-ready support. MakerVault advertises
native-file import capability for every known engine but does not invent a
catalogue or substitute a different engine's profiles when no official source
is available. Import remains candidate-only until the exact engine version,
worker image/binary and profile trio generate reviewed, bounded G-code.

Future engine adapters must expose their own pinned source identities, native
profile parsing and parent resolution, machine/firmware capability gates,
engine-version compatibility limits, and real CLI fixture tests with at least
two unrelated printer manufacturers. A new engine **must not** be declared
generally test-ready solely because an existing Orca profile worked. User
provided native profiles remain a supported alternative to catalogue search.

## Auto-orient goals and validation stages

The interactive editor offers three orientation priorities for each selected
STL object, without changing the other objects on the plate:

- **Balanced:** weighted comparison of estimated print-time burden (25%),
  extra material risk (15%), required support risk (20%) and stability/failure
  risk (40%). This mode strongly penalises narrow bed contact.
- **Minimum supports:** prioritises downward-facing unsupported surface area
  with height weighting (78%), with secondary material, time and stability
  considerations.
- **Fastest print:** prioritises shorter estimated print height and the burden
  of supporting overhangs (82%), with smaller stability and waste penalties.

The initial implementation uses bounded triangle-mesh surface sampling,
candidate alignment from major facet normals and six principal directions,
geometry-derived overhang/contact proxies and conservative footprint/collision
checking. The current orientation is also a candidate. Results show **relative
indices, 0 best to 100 worst within that candidate set** and never claim minutes,
grams, a print-success probability or actual slicer support volumes. The user
must explicitly apply a candidate, which is stored as a normal XYZ model
rotation and goes through the existing 3MF orientation/bed-contact path.

**Next validation stage:** optionally run a bounded native test slice for each
shortlisted candidate against the exact installed engine/version and selected
printer, filament and process profiles. Compare real G-code time, consumed
material, generated support volume and warnings; retain user-approval before
modifying orientation. These actual metrics should replace proxy ordering where
available. Native validation also needs to account for first-layer adhesion,
collision/keep-out regions, supports, thin walls, cooling and material-specific
failure modes. Until then, geometry-based rank is a suggestion, not a guarantee
that a print will succeed.
