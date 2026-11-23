# PrusaSlicer integration — first independent engine acceptance gate

Status: **research and worker-contract groundwork only**. No production engine enablement, installation, profile imports, or changes to other engines.

## Version and Linux distribution (23 November 2026)

- Upstream stable release: `prusa3d/PrusaSlicer` tag `version_2.9.7`, published 2 November 2026.
- Its GitHub stable release includes Windows and macOS assets but **no official Linux AppImage**. Linux distribution is Flatpak. Do not falsely label a third-party binary "official", invent an AppImage URL, or relax the authenticated and version-pinned installer contract.
- Candidate Linux paths to evaluate: reproducible headless source build of the exact tagged upstream source within the isolated slicer build, with a digest/manifest and architecture-specific tests; or an explicitly pinned trusted Flatpak runtime safely extracted/packaged into the worker image. These require independent supply-chain and licensing review.
- PrusaSlicer 3.x is presently prerelease; do not select a 3.x alpha as the stable engine without distinct qualification.

## Existing foundations

The repository already includes `prusaslicer` in the worker's approved engine-key schema and contains a restricted `run_prusa` CLI adapter based on native INI presets (`--load` printer/filament/process, `--export-gcode`, `--output`). This does **not** make the engine installable or production-ready.

The first branch hardens native INI binary NUL rejection, adds security regression tests and a focused CI job. These tests do not execute a real PrusaSlicer binary.

## Required implementation steps

1. Pin and independently verify a licensed Linux/amd64 PrusaSlicer **2.9.7** runtime. Run `--help`, `--version`, plain STL + three full native INI presets in a restricted worker; record actual positive-E G-code and model positioning.
2. Build owner-resolved native Prusa profile discovery/import and profile inheritance flattening (machine, print/process, filament), preserving original provenance and without allowing arbitrary scripts, network endpoints or external file paths.
3. Validate genuine Prusa 3MF projects using **Prusa** metadata/part semantics, not Orca/Bambu/Creality assumptions. Verify printer plate, object tools, infill/per-object settings, support, seams, brim, cooling and variable layers against the real CLI. Fail closed for unsupported features.
4. Establish single-material slicing before optional multi-material, colour painting or modifiers. Prusa's MMU/XL tool paths and single-nozzle changer semantics must be independently verified; passing Orca/Bambu G-code does not establish Prusa parity.
5. Add deterministic and bounded production result audit; ensure printer/tool ownership, worker isolation, G-code safety, uninstall/reinstall and architecture compatibility. Only then introduce catalogue/installer admission, normal UI selection and release docs.
6. Rebase this feature onto main **after PR #196 is merged**. Re-run all real binaries plus the three existing engines' regression suite. Never couple unfinished Prusa engine admission to PR #196.

## Safety invariants

No uploaded binary executes from a request; no unapproved version/digest, untrusted script or network target is allowed. The worker must not silently drop features or modifier volumes. No server or printer deployment occurs from this planning branch. No `main` changes or release publication until the gates above are demonstrably green.
