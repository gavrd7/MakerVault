# PrusaSlicer 2.9.7 integration — draft PR #199

**Status (25 November 2026):** PR #199 is reconciled with released v1.7.2 and remains **DRAFT**. The genuine source-built PrusaSlicer 2.9.7 binary, resource package, and exact-hash native installer have passed a real Docker-based, nonproduction worker slicing acceptance. The exact reviewed Prusa runtime is now permanently published as a **separate** GitHub release, but PR #199 remains unmerged and has not been deployed to staging/production. GitHub's latest MakerVault **application** release remains **v1.7.2**. Existing OrcaSlicer, Creality Print and Bambu Studio executables and runners are untouched.

## 25 November 2026 — genuine CLI and isolated installer acceptance (current)

- **Pinned real upstream build successful:** [GitHub Actions run 45509961312](https://github.com/gavrd7/MakerVault/actions/runs/45509961312) compiled exact PrusaSlicer 2.9.7 Linux AMD64 source (`450d70dd81c9b8990bc6bc8e690e31f82ddceb11`), verified headless CLI and native official Prusa profile bundle, and generated **208,936 bytes of genuine G-code with 3,737 positive-E extrusion moves** for a 20mm cube using real MK2S / Generic PLA / 0.20mm NORMAL presets. The earlier `--version` probe failed because Prusa's CLI does not support that flag; `--help`, pinned Git SHA and real slicing are used instead. Binary SHA-256: `4488d5b6ed97c818c4c19bef58b51704726e7a20407a8eda986bc88b3b13aa18`.
- **Verified exact package:** archival tar `prusa-2.9.7-headless-linux-amd64.tar.gz`, size **96,094,489 bytes**, SHA-256 `963eb81fd972d50c5f8fe54c3adb6dce2eab39c9ab223534b917eae76973d913`. Contains native executable, pinned `PrusaResearch.ini` vendor resources and upstream `LICENSE` with review-only per-file SHA manifest. GitHub Actions artifact ID **14977758244** expires **2 December 2026**. Never treat this short-lived artifact as a production installer source.
- **Implemented fixed-source native installer** (Prusa-only additions to `slicer_worker/engine_installer_service.py` and new `slicer_worker/prusa_runtime_install.py`): approved release discovery requires an exact **permanent public GitHub release tag**, asset size, browser URL and GitHub's published SHA-256. The download is independently pinned to the exact archived tar digest. An isolated, bounded tar reader rejects traversal/symlinks/devices/duplicates/extra files and verifies every file's manifest digest, known CLI/vendor hashes, source identity, and AMD64 ELF machine. The staged CLI is probed, installed atomically to `versions/prusaslicer/2.9.7`, made worker-readable, and activated without removing existing engines. Existing AppImage installer paths remain unchanged. Reinstall/uninstall use the existing version lifecycle.
- **Genuine combined-container runtime acceptance**: [run 45522066883](https://github.com/gavrd7/MakerVault/actions/runs/45522066883) **passed** exact tar download/check, Docker build of the unchanged generic slicer image, installer activation alongside reviewed Orca, unprivileged UID 10001 engine SHA checks, and real native Prusa cube slicing. Follow-up [run 45522293738](https://github.com/gavrd7/MakerVault/actions/runs/45522293738) additionally checks uninstall/reinstall preserving Orca, **pending at last documentation edit**. Full latest-head CI must be checked.
- **Permanent distribution requires a separate explicit promotion:** `.github/workflows/publish-prusa-runtime.yml` has a confirmation-gated manual workflow to promote **only** the already-verified archive to GitHub release tag `prusa-runtime-v2.9.7-450d70d`, asset `prusa-2.9.7-headless-linux-amd64.tar.gz`. The normal MakerVault v* release and GHCR publishing are unaffected. GitHub generally requires workflow dispatch files to be present on the default branch; publish only after that workflow is available or via another reviewed explicit mechanism. **No permanent runtime release has been published or server installed as part of PR development.**
- The existing UI engine selection/installation system already consumes the authenticated release catalogue and worker health. Prusa's advanced 3MF, transformed/multiple-model plates, MMU/XL, painting and modifiers are still **not** supported by verified native Prusa execution; fail closed rather than silently downgrading user designs. Verify actual profile/search selection and desktop/mobile end-to-end staging after a stable engine release is available.

### Verified permanent distribution (25 November)

- The explicit, Prusa-only promotion [run 45522711141](https://github.com/gavrd7/MakerVault/actions/runs/45522711141) passed the exact artifact SHA, all 1,179 native resource files, ELF, source identity and real native cube slicing again and **published** [`prusa-runtime-v2.9.7-450d70d`](https://github.com/gavrd7/MakerVault/releases/tag/prusa-runtime-v2.9.7-450d70d) with permanent archive size **96,094,489 bytes** and digest `963eb81fd972d50c5f8fe54c3adb6dce2eab39c9ab223534b917eae76973d913` (confirmed independently from GitHub Release API). This is not a MakerVault application release or staging deployment.
- Standalone runtime initially appeared as GitHub's latest release; repaired metadata so **v1.7.2** again remains the latest MakerVault application release (confirmed via API). Promotion workflow now sets `--latest=false` for future Prusa runtime assets.
- [Run 45522464723](https://github.com/gavrd7/MakerVault/actions/runs/45522464723) **passed** exact archive import, owner-independent worker UID check, genuine HTTP `/health` + authenticated `/v1/slice` with Prusa official presets and positive G-code auditing, refusal of unauthorised requests, and uninstall/reinstall preserving OrcaSlicer.
- Added `.github/workflows/prusa-released-runtime-smoke.yml` to exercise **real public release catalogue metadata, HTTPS asset retrieval and hash-pinned normal installer flow**, followed by isolated real cube worker slicing; a first run failed due a Python fixture quoting typo and was corrected in commit `5d65e289`, with [new run 45523043140](https://github.com/gavrd7/MakerVault/actions/runs/45523043140) launched. **Do not claim it passed before checking that run.**
- Prusa-only scheduling safeguard rejects unverified global process overrides, multi-material requests and transformed/multi-model 3MF execution rather than ignoring controls; specific backend regression tests added. Existing three engine branches remain unchanged.

### Remaining gates before review and merge

1. Confirm the latest combined-container **uninstall/reinstall** workflow and full ordinary CI/regressions at final PR head.
2. Publish the exact reviewed archive through the explicit standalone runtime promotion workflow, and prove normal installer **catalogue download, digest checking, activation and restart** through authenticated MakerVault UI (the candidate CI intentionally injected the same tar into the isolated installer without publishing).
3. Validate owner-scoped native preset search/import and single-material STL slicing from the actual MakerVault frontend on desktop and mobile, printer/build-plate handling, output download, errors and active job behaviour on staging. Avoid enabling unsupported Prusa 3MF or advanced features.
4. Review license/supply-chain publication metadata and regression evidence for all three released engines. Keep PR #199 draft, `main`, production and staging unchanged until the verified merge gates are met.

---

## 24 November follow-up: true native compiler and smoke qualification

- Previous genuine source-build run [45477598819](https://github.com/gavrd7/MakerVault/actions/runs/45477598819) **failed** in wxWidgets: CMake selected GTK2 (`DEP_WX_GTK3=OFF`) while the runner installed only `libgtk-3-dev`; `gtk/gtk.h` was missing. Isolated branch commit `465aa7f` now selects GTK3 (`DEP_WX_GTK3=ON`) without changing any released engine or native upstream source. Real compiler run [45501899820](https://github.com/gavrd7/MakerVault/actions/runs/45501899820) was still building dependencies at last inspection; its eventual result must be read before any approval.
- Discovered a separate deterministic final-step failure: the candidate workflow referred to `$GITHUB_WORKSPACE/scripts/prusa_real_binary_smoke.py` without checking out MakerVault. Commit `919a5da` adds read-only `actions/checkout@v4` before upstream clone. **The in-flight older SHA build does not contain this follow-up change**; retest the final head with an explicitly tagged build once compilation is proven.
- The five regular CI workflows passed on `465aa7f`: MakerVault CI, worker contract, Prusa contract, combined isolation, Orca real-binary smoke. They must all be rechecked on the final head. Neither source compilation nor actual single-material runtime is approved from these passes alone.
- Runtime admission remains disabled. No Prusa installer, worker activation, native 3MF, MMU/XL, painting, or modifiers should be advertised as implemented until separately demonstrated; staging/production and all working engines remain untouched.

### Candidate packaging safety (additional commits)

- Added `scripts/prusa_candidate_manifest.py` (`8164a11`): review-only bounded manifest of exact SHA-256 checksums of the Prusa binary, native vendor resources and licence. Includes exact `version_2.9.7` source commit provenance; rejects symlinks, special files, missing profile bundle, invalid ELF and oversized candidate payloads. Its `install_approved` property is deliberately `false`.
- Updated only the Prusa candidate workflow (`412335e`) to include upstream `LICENSE` and generated `review-manifest.json` inside the separate archive **after** a genuine CLI smoke; no automatic installer, GHCR publication or active-engine entry. Added tests (`780ef43`) and included them in focused Prusa workflow (`d62dbeb`).
- These are packaging safeguards, **not evidence of completed upstream compilation or installer/runtime acceptance**. Check the ongoing pinned build and re-run from the final PR head after it completes. Existing engines remain unchanged.

## Implemented on the isolated Prusa branch

- Prusa-only **native INI** parser and flattening of exact named `[printer:...]`, `[filament:...]`, `[print:...]` upstream sections; supports official `;`-delimited **ordered multiple inheritance**, shared ancestor DAGs, and hard-fails on cycles, missing parents, wrong preset kind, excessive depth and size, unsafe directives, or nonempty post-processing commands.
- `slicer_worker/runner.py` validates real bounded STL geometry and all three **flattened** native Prusa CLI profiles, including FFF constraints and text G-code. It retains fixed command-line arguments, timeout, input/output size limits and scrubbed failures. Only `prusaslicer` has the new explicit **3MF fail-closed** worker guard; 3MF, MMU/XL, painting and modifier support are **not claimed**.
- Prusa candidate-only official catalogue now targets **`version_2.9.7`** and exposes individual printer/filament/print presets, not just printer-model artwork. `backend/core/slicer_api.py` imports owner-scoped, flat `.ini` files without approving execution. Independent official profile source and version identity are retained.
- Automated Prusa contract test: strict regression tests plus download of the authentic `PrusaResearch.ini` by **immutable upstream source commit SHA** `450d70dd81c9b8990bc6bc8e690e31f82ddceb11`; tests flattened MK2S, Generic PLA and 0.20mm NORMAL settings. This tests native profile parsing, **not real slicing**.
- Dedicated `prusa-pinned-headless-candidate.yml` compiles exact tagged upstream Linux/amd64 PrusaSlicer headlessly and independently verifies version, packaged resource layout, and real G-code extrusion from a 20mm cube with the authentic flattened profiles. The candidate is an isolated short-lived review artifact; it cannot be installed through MakerVault or automatically published to GHCR.
- Upstream source build discovered a dead GMP **6.2.1** URL (`gmplib.org` returned HTTP 404). The isolated candidate workflow substitutes the official `ftp.gnu.org` download URL while preserving upstream's exact required SHA256 `eae9326beb4158c386e39a356818031bd28f3124cf915f8c5b1dc4c7a36b4d7c`; no source hash or source code is modified beyond that reviewed dependency URL.
- All new tests/guards target Prusa; existing engines keep their binary, profiles, active volumes, and request formats.

## Explicit remaining release and merge gates

1. **Run and pass** the pinned Linux AMD64 source build, real `--version`/`--help`, true native INI + STL slice, positive-extrusion G-code and packaged binary checksum; investigate any further upstream dependency 404/compile errors. Do not infer actual acceptance from CI fixture-only checks.
2. Verify production worker image architecture and isolated runtime packaging/license compliance; bind an installable immutable SHA256 build and native executable to the existing administrator-only installer catalogue, with uninstall/reinstall and health-check tests. No automatic engine admission.
3. Confirm exact-version, owner-resolved Prusa profile selection/compatibility, printer presets and genuine real slicer output versus baseline, including print area/motion and unsafe script/macro handling. Native 3MF/multicolour/negative regions remain disabled unless independently accepted.
4. Add bounded production G-code safety audit and install lifecycle tests, owner-scoped HTTP contract and end-to-end desktop/mobile UI/staging validation.
5. Require full latest-head main CI, Prusa contract, existing three-engine regression workflows and a successful real source-binary smoke; then submit for review. **Do not merge solely on mocked commands, archived toolchain artifacts or vendor metadata.**

---

## Version and Linux distribution (23 November 2026)

- Upstream stable release: `prusa3d/PrusaSlicer` tag `version_2.9.7`, published 2 November 2026.
- Its GitHub stable release includes Windows and macOS assets but **no official Linux AppImage**. Linux distribution is Flatpak. Do not falsely label a third-party binary "official", invent an AppImage URL, or relax the authenticated and version-pinned installer contract.
- Candidate Linux paths to evaluate: reproducible headless source build of the exact tagged upstream source within the isolated slicer build, with a digest/manifest and architecture-specific tests; or an explicitly pinned trusted Flatpak runtime safely extracted/packaged into the worker image. These require independent supply-chain and licensing review.
- PrusaSlicer 3.x is presently prerelease; do not select a 3.x alpha as the stable engine without distinct qualification.

## Existing foundations

The repository already includes `prusaslicer` in the worker's approved engine-key schema and contains a restricted `run_prusa` CLI adapter based on native INI presets (`--load` printer/filament/process, `--export-gcode`, `--output`). This does **not** make the engine installable or production-ready.

The first branch hardens native INI binary NUL rejection, adds security regression tests and a focused CI job. These tests do not execute a real PrusaSlicer binary.

## Original qualification plan (historical)

1. Pin and independently verify a licensed Linux/amd64 PrusaSlicer **2.9.7** runtime. Run `--help`, `--version`, plain STL + three full native INI presets in a restricted worker; record actual positive-E G-code and model positioning.
2. Build owner-resolved native Prusa profile discovery/import and profile inheritance flattening (machine, print/process, filament), preserving original provenance and without allowing arbitrary scripts, network endpoints or external file paths.
3. Validate genuine Prusa 3MF projects using **Prusa** metadata/part semantics, not Orca/Bambu/Creality assumptions. Verify printer plate, object tools, infill/per-object settings, support, seams, brim, cooling and variable layers against the real CLI. Fail closed for unsupported features.
4. Establish single-material slicing before optional multi-material, colour painting or modifiers. Prusa's MMU/XL tool paths and single-nozzle changer semantics must be independently verified; passing Orca/Bambu G-code does not establish Prusa parity.
5. Add deterministic and bounded production result audit; ensure printer/tool ownership, worker isolation, G-code safety, uninstall/reinstall and architecture compatibility. Only then introduce catalogue/installer admission, normal UI selection and release docs.
6. Reconcile this feature with released v1.7.2 main (completed). Re-run all real binaries plus the three existing engines' regression suite. Never couple unfinished Prusa engine admission to PR #196.

## Safety invariants

No uploaded binary executes from a request; no unapproved version/digest, untrusted script or network target is allowed. The worker must not silently drop features or modifier volumes. No server or printer deployment occurs from this planning branch. No `main` changes or release publication until the gates above are demonstrably green.

> Source-build CI control: the pinned headless runtime workflow may also run from an explicitly marked branch push (`[prusa-build]`). Ordinary PR commits do not rebuild upstream dependencies, and the release/installer paths remain disabled.
