# PrusaSlicer 2.9.7 integration — draft PR #199

**Status (24 November 2026):** PR #199 is reconciled with released MakerVault v1.7.2. PrusaSlicer remains **disabled and uninstalled** in MakerVault. No released OrcaSlicer, Creality Print, Bambu Studio, staging, or production engine has been modified.

## 24 November follow-up: true native compiler and smoke qualification

- Previous genuine source-build run [45477598819](https://github.com/gavrd7/MakerVault/actions/runs/45477598819) **failed** in wxWidgets: CMake selected GTK2 (`DEP_WX_GTK3=OFF`) while the runner installed only `libgtk-3-dev`; `gtk/gtk.h` was missing. Isolated branch commit `465aa7f` now selects GTK3 (`DEP_WX_GTK3=ON`) without changing any released engine or native upstream source. Real compiler run [45501899820](https://github.com/gavrd7/MakerVault/actions/runs/45501899820) was still building dependencies at last inspection; its eventual result must be read before any approval.
- Discovered a separate deterministic final-step failure: the candidate workflow referred to `$GITHUB_WORKSPACE/scripts/prusa_real_binary_smoke.py` without checking out MakerVault. Commit `919a5da` adds read-only `actions/checkout@v4` before upstream clone. **The in-flight older SHA build does not contain this follow-up change**; retest the final head with an explicitly tagged build once compilation is proven.
- The five regular CI workflows passed on `465aa7f`: MakerVault CI, worker contract, Prusa contract, combined isolation, Orca real-binary smoke. They must all be rechecked on the final head. Neither source compilation nor actual single-material runtime is approved from these passes alone.
- Runtime admission remains disabled. No Prusa installer, worker activation, native 3MF, MMU/XL, painting, or modifiers should be advertised as implemented until separately demonstrated; staging/production and all working engines remain untouched.

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
