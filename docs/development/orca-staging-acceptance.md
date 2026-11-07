# Offline OrcaSlicer staging acceptance test

This is a developer-only test, **not a release approval**. It runs the real
OrcaSlicer v2.4.2 executable in the locally built staging worker image and
returns a receipt showing whether it produced extrusion-bearing G-code.

## Before running

1. From the MakerVault staging checkout, run
   `python3 scripts/install_slicer_staging.py prepare-orca`. This downloads
   the exact upstream release asset, checks its SHA-256 against the official
   GitHub release digest and builds a local image pinned by image ID.
2. Obtain **three fully resolved, independently reviewed native Orca JSON
   profiles** for the same printer and engine version: printer, filament and
   process. Raw upstream K1/K2 profile files commonly contain `inherits` and
   are **not** valid inputs to this standalone probe. The normal MakerVault
   application has separate owner-scoped native-parent resolution.
3. Invoke the offline test without enabling application execution:

```sh
python3 scripts/probe_slicer_staging.py \
  --printer /path/to/resolved-printer.json \
  --filament /path/to/resolved-filament.json \
  --process /path/to/resolved-process.json
```

The probe copies the bounded JSON inputs to an ephemeral read-only mount, runs
the real binary using the project's tetrahedron STL, validates that G-code
contains extrusion, and writes a JSON receipt to standard output. The container
runs without networking, privileged mode, Docker socket access, other host
mounts, or printer connectivity. The local host's Docker CLI is used only to
launch the disposable container.

Exit code **0** with `"status": "passed"` is evidence of a successful fixture.
Any other result is a failure: do not approve the engine or profiles. Keep the
receipt and review the G-code itself before any production enablement.

This script deliberately **does not** import profiles into MakerVault, mark
profiles verified, unlock the GUI's Slice action, or send anything to a printer.
Those are separate acceptance and administrator-approval steps. A successful
single-STL probe also does not validate multi-object 3MF or CFS mapping.
