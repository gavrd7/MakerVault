# Bambu Studio 02.09.01.70 — MakerVault engine integration

This document tracks the exact upstream build, integration evidence and remaining
technical validation. It is **guidance**, not an extra activation screen. Bambu
Studio uses the same engine picker, Install/Update/Uninstall modal, profile search,
build-plate selector and slice/print review controls as OrcaSlicer and Creality Print.
No Bambu-specific opt-in environment variable, Beta switch or confirmation checkbox
is required. It appears in the normal install catalogue whenever the approved
official release is available.

## Exact approved Linux executable

- Official release: https://github.com/bambulab/BambuStudio/releases/tag/v02.09.01.70
- Linux AppImage: `BambuStudio_ubu24-v02.09.01.70-20261103183404.AppImage`
- Official AppImage SHA-256: `668dabb1be53c758189ed6bc89935285dea5e0af46216546b1bafd6882e9aff0`
- Extracted AppRun executable SHA-256: `eaf5a1c6ff4f0d49d6e0c0bacf106309daa2c822ca1ebe8739067699e6cdaef4`
- Runtime: Ubuntu WebKit/GStreamer native packages on the existing pinned
  Orca-based, combined `makervault-slicer` image.

The existing installer (not the web application) downloads and SHA-verifies the
exact official release, extracts the AppImage without FUSE, probes headless
startup and atomically activates it in the versioned store. It preserves the
other installed engines and permits normal per-engine uninstall and switching.
No separate Bambu container is added.

## Operator setup on staging

Use the normal `scripts/install_slicer_staging.py` workflow after full PR CI
has passed and a staging deployment has been chosen. **Refresh the combined
worker image when `slicer_worker/` changes.** In MakerVault, select
**Bambu Studio → Install**, then search/import its actual native machine,
process and filament presets. Manually imported complete native profiles also
work, subject to the normal owner/version/source and checksum checks.

There is no `MAKERVAULT_SLICER_BAMBU_BETA_ENABLED` or
`SLICER_BAMBU_BETA_ENABLED` setting to enable, disable or remember.
A version is available only when the existing worker reports that exact
installed, SHA-verified runtime as ready. Never substitute stock Orca 2.5.0
for MakerVault's separate, reviewed K2-compatible Orca build.

## Evidence from the real Bambu Studio CLI

CI validates the exact official AppImage, then builds a fixed X1 Carbon
0.4-mm / Standard 0.20-mm / Bambu PLA Basic fixture from the executable's
bundled official BBL profiles. Native inheritance and included G-code
templates are fully resolved; no invented configuration is passed to the CLI.

- A tetrahedron STL was sliced to **137,742 bytes** of extrusion-validated G-code
  (SHA-256 `9436bc7314d765588ca4cb7f450b16a422e7f2ec014b9b1659e4cf6b4d4d42ec`).
- A MakerVault core single-object 3MF was sliced to **137,694 bytes** of
  extrusion-validated G-code
  (SHA-256 `3eb12097cafd0a7864e4110431091ebd37b4aba0aadea72db52437655e0286e9`).
- Both passed inside a disposable non-root, read-only, networkless Docker
  candidate: [CI 44983450397](https://github.com/gavrd7/MakerVault/actions/runs/44983450397).
- Both passed again against the exact immutable Orca base used by the
  combined slicer, with the existing worker network syscall restriction:
  [CI 44983920228](https://github.com/gavrd7/MakerVault/actions/runs/44983920228).

These successful smoke tests validate this *single-material native fixture*.
They do not themselves prove every machine/firmware combination, or real
multi-tool/AMS/CFS changeovers. They do not authorize automatic printer starts.

## Engine/profile behaviour

Bambu has the same ordinary UI controls as the other engines. It can import
official BBL machine/process/filament presets including all indexed
dependencies. Complete user-imported native Bambu profiles are accepted under
the existing private-asset and bounded inheritance rules; no BBL-only policy.

The native Bambu CLI accepts STL and core 3MF. The MakerVault plate interface
exposes resolved build geometry and standard surface choices. Selected bed
types are applied only to the job's *temporary native process-profile copy*,
and the native filament temperature vector is checked before slicing. The
actual Bambu CLI remains responsible for honoring any excluded bed regions.

Multi-material tool/palette instructions and custom per-object
painting/modifier metadata need additional native serialization and
real-binary regression coverage. Until those particular paths are correctly
implemented, they are reported as unsupported rather than silently omitted
from G-code. This is an execution capability limitation, **not** a hidden
Beta setting or a feature you will later need to turn on.

Generated Bambu G-code follows the ordinary MakerVault output lifecycle and
the same **explicit, confirmed** printer upload/start API as other engines.
There is no Bambu-only global upload ban. A user must still review printer
compatibility and G-code; MakerVault never uploads or starts a print merely
because a slice completed.

## Remaining acceptance for PR #191

- [x] Reconcile branch ancestry against merged #192; preserve four-container
      lifecycle and Orca/Creality code.
- [x] Remove Bambu-only opt-in flags, Beta UI/print-action restrictions and
      official-BBL-only manual profile gate.
- [x] Verify real native STL/core-3MF CLI and isolated combined-image proof.
- [x] Integrate normal installer catalogue, worker registry, API profiles,
      build-plate controls and printer review.
- [ ] Obtain full current-head backend/frontend/worker and real-image CI success.
- [ ] Verify Bambu install/activate/uninstall and an end-to-end saved slice on
      the actual Debian staging system, without affecting Orca and Creality.
- [ ] Independently validate multi-material and model-paint semantics before
      relying on generated toolchanges.
- [ ] Complete the operator's staging review before merging or tagging v1.7.0.

Do not merge PR #191 merely because a candidate fixture sliced successfully.
No user's running containers, databases, volumes or printers were modified
during this PR development work.
