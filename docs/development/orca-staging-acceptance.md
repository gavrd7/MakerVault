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


## Real GitHub Actions acceptance (7 November 2026)

The [real-engine CI workflow](../../.github/workflows/orca-real-smoke.yml) downloads
the pinned official OrcaSlicer v2.4.2 AppImage, verifies its upstream release
SHA-256, builds the restricted image and executes real extrusion-bearing
tetrahedron slices using a K1 and a K2 reference fixture.

**K1:** the fully resolved native machine/process/Generic PLA profile fixture
slices successfully with the unmodified native printing settings (except the
explicit removal of unsafe print-host/post-processing fields).

**K2:** the upstream official Orca v2.4.2 K2 0.4 nozzle machine preset sets
`retraction_distances_when_cut` to `30`, but the engine rejects that setting
because its accepted range is `10..18`. The unmodified K2 fixture **failed**
and must not be represented as approved. The *test-only* fixture builder
checks that the original value is exactly `30`, logs the substitution and
sets it to `18` for an isolated slicing compatibility experiment. That
modified fixture **passed**, producing verified G-code with extrusion.
**This substitution is not production approval and must never be applied
silently to an imported K2 printer profile**. The K2 machine profile needs
a reviewed compatible upstream preset or an independently verified
administrator-approved override before it is used for actual K2 prints.

The application execution switch and all per-profile approval gates remain
independent; a passing CI reference fixture does not unlock printing, prove
printer-ready G-code or validate multi-material/CFS and 3MF bed workflows.

## Verified two-model OrcaSlicer execution (7 November 2026)

Real official OrcaSlicer v2.4.2 runs in a nonprivileged, no-network CI
container using the actual MakerVault backend
`build_compound_plate_3mf` implementation. Two source tetrahedra, positioned
70 mm apart with independent transforms, are converted into one **single-
material** compound 3MF mesh. The real CLI produced G-code with extrusion
movements separated by more than 35 mm across X. The test also verifies the
same exact bounded worker input validator and profile/binary identity gates.

A conventional 3MF holding two separate `<build><item>` objects did *not*
produce extrusion for both objects with this Orca CLI. Its CI diagnostic is
non-blocking only because that **unsupported** format is never used for a
production job. The production Orca path instead selects compound geometry
and rejects non-Orca multi-model execution. Separate printable materials and
tool assignments remain unverified and unavailable. The native K2 profile
override remains **test-only**, not approved for K2 hardware.

These are offline software acceptance tests, not hardware print certification
or evidence that a staging user's specific native profiles have been approved.
Profile approval must still run an administrator-controlled real fixture on
the installed, pinned worker before any staging slice can be queued.
