# Creality Print 7.3.x native 3MF diagnostic matrix (staging)

Use this to investigate recurring native CLI **205 / CLI_VALIDATE_ERROR (-51)**
without repeatedly rebuilding MakerVault or manually editing the two-Benchy
draft. This is an **offline diagnostic**, not a printer test or print approval.

## Prerequisites

- MakerVault staging with the existing `makervault` and
  `makervault-slicer-worker-1` containers running.
- Creality Print 7.3.x installed and approved in the worker engine registry.
- A previously failed **two-material Creality** saved slicing job with its
  original meshes and native presets available in MakerVault.
- Run the current staging app and worker updates (the tool is installed by both).

## Run

From `~/MakerVault-Staging`:

```bash
git pull --ff-only origin feature/self-hosted-slicer-foundation
sudo python3 scripts/install_slicer_staging.py update
sudo python3 scripts/install_slicer_staging.py refresh-worker
sudo python3 scripts/diagnose_creality_staging.py
```

A successful diagnostic execution **does not mean that all cases passed**.
The wrapper prints each case's status, code and bounded validation category,
and writes a private `creality-diagnostic-report.json` to the staging checkout.

The wrapper intentionally returns **exit 2** if none of the seven CLI scenarios
slices successfully; that is useful diagnostic output, not a wrapper crash.

Options:

```bash
sudo python3 scripts/diagnose_creality_staging.py --timeout 120 \
  --output /tmp/my-creality-report.json
sudo python3 scripts/diagnose_creality_staging.py --job-id JOB_UUID \
  --output /tmp/specific-creality-report.json
sudo python3 scripts/diagnose_creality_staging.py \
  --reference /path/to/genuine-creality-7.3.1-project.3mf \
  --output /tmp/reference-comparison.json
```

The optional reference 3MF is **never sliced**; only its project-settings
key presence and value types are compared. Never share a native reference file
unless you have reviewed it for private paths, network settings and model data.

## Matrix

0. **single-model-single-material** — true one-object, one-material control derived from the first prepared model; distinguishes multi-material validation from a generally invalid native project.\n1. **baseline** — exact latest failed MakerVault candidate.
2. **no-explicit-filament-map** — Creality chooses the physical nozzle map.
3. **explicit-single-nozzle** — map both materials to nozzle 1.
4. **tower-disabled** — isolate prime-tower influence; *not safe to print*.
5. **normalised-filament-scalars** — detect scalar-vs-string vector problems.\n6. **identical-filament-parameters** — isolate differences between the two native material profiles.

Each test runs the pinned engine, without the browser, inside the existing
isolated worker. Candidate project and generated G-code stay in ephemeral
scratch and are deleted. The returned report includes exit codes, elapsed
times, safe error categories, configuration SHA-256 and optional lists of
missing/different setting names, but **not** profile JSON, G-code, native
engine logs, model coordinates, personal paths or printer credentials.

The matrix isolates known causes but is **not exhaustive** and may still
yield seven failures. If it does, compare a genuine native 3MF using
`--reference` rather than guessing additional settings. Before any print,
restore normal worker validation and independently confirm the generated
tool paths, colour mapping, exact model positions and prime-tower bounds.

## No additional containers

This runs via `docker exec` against the existing two containers. It does
not deploy a diagnostic daemon, add services to Compose, contact printers,
or change saved jobs or imported profiles.

## Unit tests (no Creality binary required)

```bash
python3 -m unittest slicer_worker.tests.test_creality_diagnostics
```

The unit tests verify deterministic matrix variants and sanitisation. The
staging matrix is the real-binary integration test.

## Native K2 reference comparison (November 2026)

A Creality Print **7.3.2.6412** exported two-Benchy project was
inspected as a *structural reference* for MakerVault's **7.3.1** engine.
The uploaded 3MF itself, local paths, embedded G-code scripts, mesh data,
filament colours and source profile values are NOT committed.

The reference establishes these native contract properties:

- Four material entries, even though only two Benchys were assigned
  (physical slots 3 and 4 in that reference).
- Four-element `filament_map`, `filament_map_2`, temperature and
  filament identity vectors.
- A 16-element flushing matrix and eight-element flushing vector.
- Object-level `part` and plate `assemble` metadata, plus independent
  `Metadata/creality.config` and project settings.

The revised adapter emits these dimensions and adds native-style object
metadata while retaining the safe, baked positions. Unassigned material
entries are placeholders derived from resolved assigned profiles; **they
are not evidence of the real contents of unused CFS bays**. Native
physical-slot-to-firmware mapping and purge adequacy remain unverified.
Multi-material printer submission remains blocked.

The uploaded reference was saved by 7.3.2, so schema similarity must not
be treated as proof of compatibility with 7.3.1. Run the backend unit
regressions and the real-engine diagnostic matrix after updating staging.
A successful `--slice` result must still pass tool usage, extrusion
bounds, purge and layout inspection before any future print approval.



## Control and structural comparison (second diagnostic pass)

The first six variants all retained two models and two active materials, so
six failures with 205 did not isolate single-material project compatibility.

The **single-model-single-material** control now retains only the first
original Benchy, its baked placement and the first resolved filament;
deletes the other object/instances, reduces the native active filament
palette to one, and disables the prime tower. This is a *diagnostic derivative
of a MakerVault project*, not a genuine desktop Creality export; a pass is
useful evidence, but does not prove full CFS support.

Run a reference comparison if the genuine Creality 3MF is available on the
staging server:

```bash
sudo python3 scripts/diagnose_creality_staging.py \
  --reference /path/to/your/3DBenchy.3mf \
  --output /tmp/creality-diagnostic-v5.json
```

The reference is **not installed into MakerVault** and **never executed**.
The report contains only public option key names, data types and list lengths,
archive role counts, geometry/component counts and structural differences;
it intentionally omits preset values, private filenames, printer scripts
and positions.

Results separate three conditions:

- **Single-material fails + multi-material fails:** likely a shared native
  3MF project loader/validation mismatch (or runtime CLI issue).
- **Single-material passes + multi-material fails:** investigate material
  palette, physical nozzle mapping, tower and per-object assignments.
- **Structural differences without a working control:** they identify
  areas for source-level verification, not automatically the root cause.

The reference was made by 7.3.2.6412, so compare it carefully against the
7.3.1 runtime. Continue keeping multi-material printer upload blocked.

## Referencing a 3MF already in MakerVault inventory

If the genuine Creality project has already been uploaded to MakerVault, no
second file upload or copy to Debian is required. Run:

```bash
sudo python3 scripts/diagnose_creality_staging.py \
  --reference-inventory 3DBenchy.3mf \
  --output /tmp/creality-diagnostic-inventory.json
```

The command selects the latest failed multi-material Creality draft and
looks for a matching private FileAsset **owned by that draft's owner**.
It accepts the exact stored filename or an inventory title without the
extension if the metadata confirms it is a 3MF. No arbitrary filesystem
searches or other users' files are allowed.

If multiple candidate assets match, it fails closed. Select the exact
FileAsset UUID instead:

```bash
sudo python3 scripts/diagnose_creality_staging.py \
  --reference-asset-id UUID \
  --output /tmp/creality-diagnostic-inventory-specific.json
```

Optionally combine either reference selector with `--job-id UUID` to select
a particular failed draft and ensure its owner is used for access checking.
The reference file is read through MakerVault's private storage backend,
copied to the existing worker temporarily, used for **structural comparison
only**, and deleted from diagnostic scratch. The original stored file remains
unchanged. The report is safe-to-share structural metadata only.

Important: a source STL renamed `.3mf`, a single exported model-only 3MF,
or a sliced G-code artifact is not interchangeable with a genuine Creality
project carrying `Metadata/project_settings.config`.

## Built-in sanitised desktop 3MF reference (no file transfer)

A genuine two-Benchy Creality Print **7.3.2.6412** K2 project was
inspected directly in the development workspace. Rather than committing the
private project, a value-free structural fixture now ships in
`slicer_worker/creality_reference_schema.py`.

It records only:
- 17 archive members and their role counts; three model documents,
  two component links, one actual mesh, and two build instances
- 672 configuration setting keys in the original, represented in the fixture
  by aggregate type/length counts plus **112 four-slot public key names**
- Shapes of key purge, nozzle and tower options; no actual values

It does **not** include geometry, temperatures, vendor filenames, colour
values, user paths, source G-code, dates, machine identifiers or private
filament IDs. Comparing to the fixture checks **only its stored subset of
option names**; it cannot claim to know every missing one of the 672 keys.

As of this change, the normal command automatically includes the bundled
schema comparison without requiring a `--reference` or
`--reference-inventory` argument:

```bash
sudo python3 scripts/diagnose_creality_staging.py \
  --output /tmp/creality-diagnostic-v8.json
```

The existing explicit reference options remain available to compare against
another original project; they are no longer necessary for the current
uploaded Benchy fixture. This is structural evidence only: 7.3.2 is not
interchangeable with the staging 7.3.1 binary, and the diagnostics do not
authorise CFS printer submission.


## Source-backed painted feature and K2 flushing investigation (7.3.1)

Source references below are pinned to CrealityOfficial/CrealityPrint tag **v7.3.1**.
This section documents a diagnostic hypothesis and does **not** approve printing
or claim that semantic effects are proved by a successful slice.

- [CLI notes / README](https://github.com/CrealityOfficial/CrealityPrint/blob/v7.3.1/README.md#command-line-slicing):
  `--slice 0` means all plates; `--slice 1` means plate one.
  `--outputdir`, `--logfile` and `--debug` are documented.
  The README uses `--load_settings`/`--load_filaments` spelling for raw
  STL/OBJ. MakerVault's pinned adapter uses its **tested hyphenated** flags for
  raw STL; it intentionally omits external preset loading for a native 3MF
  because the 7.3.x native project loader requires embedded settings.
  Do not change established worker CLI flags based on documentation alone.

- [Support facets](https://github.com/CrealityOfficial/CrealityPrint/blob/v7.3.1/src/libslic3r/PrintObject.cpp):
  `generate_support_material()` requires `enable_support`, and the native
  process supports manual enforcers. A tiny paint annotation on a generic cube
  or on a bed-contact face cannot prove support extrusion is generated.
  The diagnostic now audits extrusion XY moves under G-code
  `; FEATURE: Support...`/`;TYPE:Support...` roles. A physically useful test
  still requires an actual unsupported underside or an explicit cantilever
  fixture; zero support-role moves on the original model are inconclusive.

- [Seam placement](https://github.com/CrealityOfficial/CrealityPrint/blob/v7.3.1/src/libslic3r/GCode/SeamPlacer.cpp):
  Creality projects `paint_seam` enforcer and blocker facets into seam
  placement. The identical-triangulation control already changes motion,
  but a spatial seam assertion must use a known outside wall and compare the
  seam-start coordinates to its painted bounds; one changed extrusion line
  is not proof of positional accuracy.

- [Painted fuzzy skin](https://github.com/CrealityOfficial/CrealityPrint/blob/v7.3.1/src/libslic3r/PrintObjectSlice.cpp)
  and [PrintApply.cpp](https://github.com/CrealityOfficial/CrealityPrint/blob/v7.3.1/src/libslic3r/PrintApply.cpp):
  Creality checks `is_fuzzy_skin_painted()`, segments the painted region,
  and sets the new *painted-only* print region to `FuzzySkinType::All`
  independently of its parent `fuzzy_skin=none` process setting.
  **Do not globally force `fuzzy_skin=all`**: that would texture nonpainted
  geometry and mask broken selective painting. Test against an actual outer
  wall and report an unchanged same-geometry control as inconclusive until
  suitable wall geometry is available.

- [Flush-volume calculation](https://github.com/CrealityOfficial/CrealityPrint/blob/v7.3.1/src/libslic3r/GCode/ToolOrdering.cpp),
  [GCode.cpp](https://github.com/CrealityOfficial/CrealityPrint/blob/v7.3.1/src/libslic3r/GCode.cpp),
  [Print.cpp](https://github.com/CrealityOfficial/CrealityPrint/blob/v7.3.1/src/libslic3r/Print.cpp):
  effective purge volume derives from directional matrix entry
  `[old_extruder * filament_count + new_extruder] * flush_multiplier`.
  But the printer-specific route depends on `enable_prime_tower`,
  `purge_in_prime_tower`, `single_extruder_multi_material`, change-filament
  macros and settings such as `prime_volume`. For instance, the generated
  change-filament template receives `flush_length` as a placeholder;
  some tower modes intentionally pass zero wipe volume through that path.
  No assumption that every increased matrix value yields more G1 E commands
  is safe. Existing K2 results changed effective 140/140 to
  462.5/218.75 mm³ but *not* G0/G1/T or M command hashes.

The command `diagnose_creality_paint_features --deep` now also returns
`feature_role_audit.extrusion_xy_moves_by_role.support`,
`geometry_control.support_xy_move_difference`, limited
`gcode_effective_settings` parsed from native config comments,
`gcode_header_flush_matrix_changed` when both headers contain matrices,
and non-sensitive purge-route flags from the project settings. It **never
returns filament-change macro contents**. Missing effective settings are
reported as absent rather than guessed.

To run after an **application-only** staging update:

```bash
sudo docker exec makervault python3 /app/backend/manage.py test \
  core.tests.test_slicer_creality_paint_diagnostics --noinput
sudo docker exec makervault python3 /app/backend/manage.py \
  diagnose_creality_paint_features --deep
```

Do not refresh the isolated worker for these application-only diagnostic
changes. Do not upload G-code to a printer, merge PR #171, or claim flushing,
support or selective fuzzy skin is verified merely because the engine slices.


### Optional, repeatable semantic geometry fixtures

The original painted cube may have no unsupported underside, and the arbitrary
one-triangle paint patch may miss an exterior wall. The app-side diagnostics
now offer geometry-specific controls without saving or importing any new mesh.
They reuse the existing completed Creality two-filament job **only** as the
source of verified, owned process/filament/printer profiles and material-slot
bindings. They generate a deterministic 30 × 12 × 25 mm L-section STL inside
the command, create a newly fingerprinted colour patch assigned to the
verified secondary material, and apply the requested semantic annotation.
The existing worker handles only the usual authenticated offline slice.

```bash
sudo docker exec makervault python3 /app/backend/manage.py \
  diagnose_creality_paint_features --only support --deep --support-fixture

sudo docker exec makervault python3 /app/backend/manage.py \
  diagnose_creality_paint_features --only seam --deep --wall-fixture

sudo docker exec makervault python3 /app/backend/manage.py \
  diagnose_creality_paint_features --only fuzzy --deep --wall-fixture
```

The support fixture paints the **elevated, downward-facing** underside at
Z=20 mm (not the plate-contact underside). The wall fixture paints a broad
external vertical face. Each painted variant is compared to a control with
identical synthetic geometry and identical native settings but with the one
semantic paint attribute removed. `--support-fixture` and `--wall-fixture`
require their relevant `--only` selector and `--deep`, and neither option
changes production slicing configuration. Inspect
`geometry_control.motion_changed_from_same_geometry` and
`feature_role_audit.extrusion_xy_moves_by_role.support`. A successful
fixture slice alone never proves that placement or surface treatment is
correct; explicit spatial toolpath checks remain a subsequent gate.

No worker refresh or approved engine hash update is needed for these
application-only additions. The synthetic fixtures and new checks must still
be validated by the user's staging tests and native CLI; they have **not**
been declared to pass on the pinned worker by this documentation.


### Automatic support positive control (November 2026)

The opt-in `--only support --deep --support-fixture` diagnostic now
performs **three offline native slices** with identical cantilever geometry,
the same two selected materials, unchanged colour painting and unchanged
printer profile:

1. Painted support underside, `enable_support=1`,
   `support_type=normal(manual)`.
2. Same remeshed project with only `paint_supports` facets removed,
   leaving manual support settings unchanged.
3. Exactly the same *unpainted* project as (2), but with only the embedded
   native `support_type` changed to `normal(auto)`.

The additional `automatic_support_control` output includes bounded native
support role-tag counts, support XY move counts, motion changes and extrusion
delta relative to the unpainted manual control.

Interpretation:

- If ordinary auto generates support and painted manual does not, investigate
  `paint_supports` decoding and support-enforcer projection under Creality 7.3.1.
- If neither generates support, inspect fixture topology, profile support
  defaults and G-code role classification before altering native facet encoding.
- A nonzero role-tag count is useful evidence but is not a guarantee of safe
  support contact or final print quality.

This is strictly a diagnostic exercise: no user settings, worker Python,
slicer binaries, printer databases or saved jobs are modified. Run the
Django diagnostic regression tests before the real engine test. Only the
application needs to be refreshed.


### Genuine painted-support project comparison — 20 November 2026

A user-provided **Creality Print 7.3.2.6412** saved 3MF project was
inspected offline (without committing the file, model mesh, printer G-code
macros, profile IDs, paths or native preset values). Its mesh is referenced
from `3D/Objects/object_1.model` via a component in
`3D/3dmodel.model`. It contains **3,630 triangles**, **253 native
`paint_supports="4"` facets** and native `normal(manual)` support mode.
An accompanying desktop sliced-preview image shows actual green supports.
This proves the desktop reference produces supports; it does not prove
the same project is executable with our pinned **7.3.1 CLI**.

Source-level evidence from Creality 7.3.1
[`SupportMaterial.cpp`](https://github.com/CrealityOfficial/CrealityPrint/blob/v7.3.1/src/libslic3r/Support/SupportMaterial.cpp)
and [`PrintObject.cpp`](https://github.com/CrealityOfficial/CrealityPrint/blob/v7.3.1/src/libslic3r/PrintObject.cpp)
confirms facet enforcers are projected through layers with
`slice_mesh_slabs`; testing only a perfectly horizontal painted
underside may yield an uninformative zero-area layer projection. The
reference also paints substantial **sloped** surfaces spanning multiple
Z layers. The referenced-mesh package structure remains a separate
hypothesis; do **not** weaken the existing worker 3MF allowlist or
repackage production geometry without an isolated validation.

The existing `--only support --deep --support-fixture` mode now also
reports a bounded `effective_support_settings` audit, creates the
normal unpainted auto control, and **adds a fourth** diagnostic-only
relaxed automatic control. Only the support-relevant values in that
last 3MF are changed: threshold angle, minimum support area,
bridge filtering and relevant support-only switches. That control
**must never be printed**. It does not copy settings from the private
reference or modify the native worker.

Use an independent sloped-cantilever test while retaining the previous
flat-cantilever comparator:

```bash
sudo docker exec makervault python3 /app/backend/manage.py test \
  core.tests.test_slicer_creality_paint_diagnostics --noinput
sudo docker exec makervault python3 /app/backend/manage.py \
  diagnose_creality_paint_features --only support --deep --support-fixture
sudo docker exec makervault python3 /app/backend/manage.py \
  diagnose_creality_paint_features --only support --deep --support-fixture \
  --sloped-support-fixture
```

Compare `geometry_control`, `automatic_support_control`,
`relaxed_auto_support_control` and `effective_support_settings`.
If relaxed auto generates supports but defaults do not, isolate the
process gate. If sloped painted support becomes effective but flat
does not, investigate slab projection and flat surface handling.
If all are still inactive, review the CLI's effective object-level
configuration and model import path before changing native painting
values. The user has not run these new tests yet.


### Confirmed Creality 7.3.1 support preset restore issue (November 20, 2026)

On Debian staging the **18/18 Django diagnostic tests passed**, but the
sloped cantilever's native 3MF had `enable_support=1` and
`support_type=normal(manual)`, while the **generated G-code settings footer**
reported `enable_support=0` and `support_type=normal(auto)`. The relaxed
automatic control also reverted its threshold **89→30**, minimum support
area **0→5**, and `max_bridge_length` **0→10**. This is direct evidence
the CLI's effective configuration discarded the overridden process values;
it is **not** evidence that native `paint_supports=4` itself is defective.

Pinned upstream 7.3.1
[`SliceCommand.cpp`](https://github.com/CrealityOfficial/CrealityPrint/blob/v7.3.1/src/slic3r/CLI/SliceCommand.cpp)
calls `refresh_creality_project_configuration()`, which reads the imported
3MF configuration into a `PresetBundle` and replaces `m_print_config`
with `project_bundle.full_config()` before slicing. In
[`PresetBundle.cpp`](https://github.com/CrealityOfficial/CrealityPrint/blob/v7.3.1/src/libslic3r/PresetBundle.cpp)
the process preset's overridden keys are obtained from
`different_settings_to_system[0]` and passed as
`print_different_keys_set` to the external-preset loader. The uploaded
genuine **7.3.2** desktop project contains
`different_settings_to_system[0] = "enable_support;support_type"` and
empty remaining slots. The user's 3MF file and G-code macros were not
copied into Git.

The native project generator now explicitly preserves exactly those
two safe support option names through the six-position vector for the
four-slot CFS palette. It preserves other existing vector slots and
rejects malformed vectors/unsafe setting names. Both the ordinary and
relaxed automatic diagnostic controls also mark the support keys they
modify. This change **does not** change other printer, filament, purge
or executable G-code settings, the worker, or the pinned Creality binary.

**Retest required:** deployed native CLI output must demonstrate
`emitted_support_settings.enable_support=1` (and appropriate
`support_type`), with a non-zero support extrusion role for a genuine
unsupported fixture. Until the actual native results verify this, do
not claim support painting is production-ready. Run:

```bash
sudo docker exec makervault python3 /app/backend/manage.py test \
  core.tests.test_slicer_creality_paint_diagnostics \
  core.tests.test_slicer_creality_project --noinput
sudo docker exec makervault python3 /app/backend/manage.py \
  diagnose_creality_paint_features --only support --deep \
  --support-fixture --sloped-support-fixture
```

No `refresh-worker` necessary for these backend-only changes. Existing
worker validation remains strict; no printer uploads or physical printing.
