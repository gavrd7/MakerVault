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


### Cross-engine K2 flushing source audit — 20 November 2026

**Research only. No binary, worker, printer, macro or production flush
code changes.** Sources are pinned to the supported engines:
[Creality Print v7.3.1](https://github.com/CrealityOfficial/CrealityPrint/tree/v7.3.1)
and [OrcaSlicer v2.4.2](https://github.com/OrcaSlicer/OrcaSlicer/tree/v2.4.2).
Do not assume current application defaults match these exact releases.

#### Native data-model comparison

- Both use `flush_volumes_matrix`, directional `old*n+new`, in mm³.
- Creality `PrintConfig.cpp` defines `flush_multiplier` as scalar
  `coFloat`; Orca v2.4.2 defines it as `coFloats` per-nozzle vector.
  This is an engine-specific serializer concern, not a different unit.
- Creality v7.3.1 `FlushVolCalc.cpp` uses the HSV/luminance predictor,
  adds a source filament/nozzle-dependent minimum and caps the result
  at `g_max_flush_volume = 1200` mm³ before any UI multiplier. It
  considers `nozzle_volume`, optional long-retraction details, and
  type changes in `GUI/WipeTowerDialog.cpp` (cross-material warning
  threshold `nozzle_volume*3`).
- Orca v2.4.2 `FlushVolCalc.cpp` also contains the HSV/luminance
  heuristic but supports `GenericFlushPredictor` via
  `nozzle_flush_dataset`, an additional condition-dependent boost,
  and `g_max_flush_volume = 20000`. Orca's UI uses a per-nozzle
  `flush_multiplier` and can select a nozzle-specific matrix.
- The official v7.3.1 Creality K2 0.4 nozzle machine preset and
  official v2.4.2 Orca K2 0.4 nozzle preset both specify
  `nozzle_volume=183`, but differ in `purge_in_prime_tower`:
  Creality `0` vs Orca `1`. Creality's machine
  `change_filament_gcode` is a 325-line native routine (325 lines
  including blank lines); it contains `{if multicolor_method}`,
  `M8200`, and uses `flush_length_1..5`. Orca's machine
  `change_filament_gcode` is a six-line positioning script with no
  `flush_length` or `M8200` placeholders. These routines do **not**
  implement interchangeable physical purge behavior.
- Creality's `GCode.cpp` computes
  `purge_length = purge_volume / filament_cross_section_area`,
  produces `flush_length_1..5` variables and expands the selected
  `change_filament_gcode` template. The native K2 profile consumes
  them in its `multicolor_method` branch. A K2 material-selection
  command (`Tn` or `M8200`) does not by itself establish that
  firmware honoured a specific flush volume.
- Creality `CLI/SliceCommand.cpp::update_filament_colors_and_flush`
  can *recompute the entire matrix and reset multiplier to 1* when
  the CLI receives an explicit `filament_colour` override or when
  the matrix is missing. This is separate from the already-confirmed
  `PresetBundle` restore issue for process keys.
  `Utils/FlushVolume.cpp` checks `flush_volumes_changed` to skip
  automatic UI recalculation. Exact CLI behavior requires evidence.

#### MakerVault implementation audit and caution

- `backend/core/slicer_flush_settings.py` already provides a
  reusable normalized directional transition contract, physical slot
  to verified native tool binding, and native-prime-tower preference.
  It currently permits up to 20,000 mm³ and a single 0.1–3 multiplier;
  engine-native limits, nozzle topology and representation must be
  validated *in the adapter* rather than treated as universal.
- `backend/core/slicer_creality_project.py::_apply_creality_flush_settings`
  writes scalar multiplier, 16-cell matrix (four CFS slots), and
  `flush_volumes_changed=1`. It currently makes no explicit override
  registration of any flush-related config fields in
  `different_settings_to_system`. **Do not assume** adding them is
  universally correct: inspect whether each is project-level vs
  process-preset owned, then test effective CLI output.
- Prior offline flush diagnostic altered T0→T1 / T1→T0 matrix plus
  multiplier. It changed G-code config-footer matrix but **not motion
  or machine command hashes**. Selected test profile reported
  `change_filament_gcode` present but *no flush_length placeholder*,
  and effective `multicolor_method=0`. Contrast this with Creality's
  upstream native K2 macro, which uses `flush_length_1..5` behind
  its `multicolor_method` conditional. Do not infer physical purging
  from footer-only data.
- The project builder also has conservative `140` mm³ fallback
  values for missing native matrix entries: these are staging
  placeholders, **not documented manufacturer K2 purge defaults**.
  Keep any unsupported user configuration fail-closed for print-ready
  claims. Never auto-replace or synthesize a native K2 macro.

#### Next offline diagnostic design (no production change until verified)

1. Audit the **resolved selected machine and process profiles** with
   sensitive macros redacted: report only structural flags such as
   has `flush_length_1..5` placeholders, uses `multicolor_method`,
   contains a `Tn` or vendor command, nozzle volume, firmware-vs-
   slicer-managed topology, `purge_in_prime_tower`. Compare the
   approved profile to the matching versioned official profile by
   structural properties and hashes, not by copying upstream scripts.
2. For one already verified 2-tool CFS colour job, compare baseline
   against two *separate* directional matrix-only modifications and
   multiplier-only modifications. Capture the **embedded 3MF**,
   **G-code emitted config**, **actual tool-change extrusion segments**
   and per-transition macro role/segment summaries (no raw private
   G-code or credentials).
3. Establish whether a change survives Creality `PresetBundle` load,
   whether the installed K2 change macro consumes `flush_length_n`,
   and whether any remaining physical purge is firmware-owned. The
   absence of changed G/M motion may be explained by a firmware
   handoff, but is not proof; physical confirmation is a separate
   safety gate.
4. Preserve the shared adapter-neutral contract
   `{from_slot,to_slot,volume_mm3,multiplier,prime_tower}`.
   Introduce per-engine capabilities describing multiplier shape,
   maximum native volume, matrix topology, auto-prediction source,
   printer-owned vs slicer-owned purge, and evidence level
   (`requested`, `effective_config`, `emitted_commands`,
   `physical_verified`). Display **unverified** rather than
   suggesting a slider definitely changes the K2's physical waste.
5. Generalize the contract to future single-nozzle changers and
   independent toolheads with explicit topology checks. Avoid
   universal G-code injection, altering vendor macros or treating
   visible UI matrix values as guaranteed delivered purging volume.

Useful upstream code:
[Creality FlushVolCalc.cpp](https://github.com/CrealityOfficial/CrealityPrint/blob/v7.3.1/src/libslic3r/FlushVolCalc.cpp),
[Creality CLI SliceCommand.cpp](https://github.com/CrealityOfficial/CrealityPrint/blob/v7.3.1/src/slic3r/CLI/SliceCommand.cpp),
[Creality GCode.cpp](https://github.com/CrealityOfficial/CrealityPrint/blob/v7.3.1/src/libslic3r/GCode.cpp),
[Creality K2 machine JSON](https://github.com/CrealityOfficial/CrealityPrint/blob/v7.3.1/resources/profiles/Creality/machine/Creality%20K2%200.4%20nozzle.json),
[Orca FlushVolCalc.cpp](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.4.2/src/libslic3r/FlushVolCalc.cpp),
[Orca K2 machine JSON](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.4.2/resources/profiles/Creality/machine/Creality%20K2%200.4%20nozzle.json).


### Accepted cross-printer and cross-slicer architecture decision — 20 November 2026

**Mandatory for follow-up flushing work.** One engine-neutral MakerVault
application/API/UI request, independent per-slicer adapters, and
independent per-printer material-change capabilities. No hardcoded K2
behaviour in the common layer.

**Common user request**: verified printer and slicer profile, assigned
physical material slots, directional source-to-destination transition
volumes in mm3, optional multiplier, and a native purge/tower preference
where supported. Distinguish user-entered final volume from engine raw
pre-multiplier matrix values, and both from actual physical purging.
Never accept arbitrary printer scripts via this request.

**Independent capability axes**:

1. **Slicer adapter** describes version, native matrix arrangement,
   scalar versus per-nozzle multiplier representation, calculation and
   defaults, preset restoration, supported destinations, and native
   validation/audit method. Orca and Creality retain independent
   adapters beneath the same contract.
2. **Printer/material topology** describes a single-nozzle changer
   (CFS/AMS/MMU), independent toolheads, ordinary single material, or
   unknown/unsupported arrangement. Resolve nozzle count, material
   indices, physical slot routes and native vs firmware-owned purge
   from verified profiles and bindings; never infer from brand/model
   names alone.

A printer targeted through two engines must receive the same user
request, translated separately. An engine targeting multiple printers
must obey each printer's verified capabilities. Single-nozzle changer
flushing must not be silently enabled for independent toolheads.
Unsupported/unknown combinations fail closed or retain verified
native defaults with an explicit unsupported status; never inject
or invent a machine-specific G-code purge sequence.

**Evidence stages**: input validated/mapped; native project or preset
contains override; emitted effective G-code config retains override;
toolchange/purge commands respond; physical purge verified (if
applicable). Each stage must be reported separately; storing a UI
number must never be presented as evidence of firmware purge control.

**Implementation plan and acceptance tests**:

- Retain the common validated directional-settings contract in
  backend/core/slicer_flush_settings.py, preserving compatible APIs.
  Put the four-slot/scalar/preset behaviour in a Creality adapter and
  the per-nozzle/vector/matrix behaviour in an Orca adapter.
- Resolve each job's printer topology independently from engine
  selection. Confirm filament count is not automatically nozzle
  count, tool count or CFS slot count.
- Test at least a verified single-nozzle multimaterial printer,
  independent multi-toolhead machine, single-material machine, and
  unknown/unsupported profile; include more than the Creality K2.
  Do not claim support for a printer until its native profile and
  toolchange path have actually passed tests.
- Audit directional row/column ordering, slot-to-tool remapping,
  scalar vs per-nozzle multipliers, default retention, invalid
  topology, and native G-code effects separately for each adapter.
- Register future slicers by their adapter and capability descriptor;
  don't extend a global K2-specific conditional chain.
- Keep this a staging-only verification effort until the native
  matrix is shown to change the intended toolchange/purge behaviour
  and necessary physical checks have been completed. No replacement
  of vendor macros, firmware guessing, or new hardware commands.

This decision supports multiple engines and printer categories without
falsely asserting that every printer's physical flushing is already
implemented.


### Common flushing adapter implementation checkpoint — 20 November 2026

The architecture decision above is now implemented in **backend application
code** (not yet exercised on the Debian staging worker):

- `backend/core/slicer_flush_settings.py` remains the authoritative
  engine-neutral validation contract
  (`from_slot_id`, `to_slot_id`, `volume_mm3`, multiplier, tower).
  The public `apply_orca_flush_settings` name remains as a compatibility
  wrapper to avoid changes to existing callers and API payloads.
- New `backend/core/slicer_flush_adapters.py` provides
  `resolve_flush_capability` and `require_flush_capability`,
  independent of printer brand. It distinguishes single-nozzle material
  changer from independent heads, toolchanger, IDEX, manual changes,
  single material and unknown. Currently *only* verified single-nozzle
  material changers with one nozzle and 2–16 logical materials are
  eligible for Orca's directional override; Creality's approved project
  builder only handles **two assigned logical materials**, even though
  its native project declares four CFS filament slots. Other setups
  are **unsupported**, not automatically enabled. New printer support
  must follow approved machine/profile routing tests.
- The new module owns `apply_orca_native_flush` (Orca per-nozzle
  vector multiplier and matrix) and `apply_creality_native_flush`
  (Creality scalar multiplier and native four-slot matrix). Existing
  Creality project generator calls the native adapter through a
  compatibility shim. There is no shared vendor G-code macro.
- Both adapters reuse `map_verified_flush_transitions`, preserving
  source/destination direction and validating physical slot-to-native
  tool mappings including duplicate/colliding routes. Changes are
  derived from validated settings, not UI swatch order.
- `audit_native_flush_profile` reports **only** structural
  capabilities: presence of segmented flush placeholders, optional
  multicolor condition, vendor handoff indicator, bounded nozzle
  volumes and native tower preference. It never returns actual
  machine G-code or proof of physical purging.
- The offline Creality diagnostic now reports the selected project's
  redacted profile capabilities, two raw directional matrix entries
  from the *emitted* G-code footer (when present), and counts/summed
  positive E extrusion **only** inside `FLUSH_START` /
  `FLUSH_END` markers. These markers may be absent in some native
  profiles; zero means not observed, **not** that the printer firmware
  did no purging.
- `--only flushing --deep` now independently slices a
  `matrix_only` control (370/175 mm3 T0/T1) and a
  `multiplier_only` control (1.25), besides the existing combined
  diagnostic, comparing the same base geometry and redacted output.
  These are **offline diagnostic-only** G-code outputs, never printed.
- New tests `core.tests.test_slicer_flush_adapters` cover two
  brand-neutral printer examples, alternate material topologies,
  unsupported/unknown counts, Orca four-material/one-nozzle routing,
  Creality two-assigned-material restriction, directional reversal,
  duplicate/colliding mappings, scalar vs vector encoding, native
  machine macro preservation and redacted macro introspection.
  Expanded `core.tests.test_slicer_creality_paint_diagnostics` tests
  cover the emitted directional matrix and FLUSH block audit.

**Local staging verification** after updating app only (no worker
refresh, pinned engine unchanged):

```bash
cd ~/MakerVault-Staging
git pull --ff-only origin feature/self-hosted-slicer-foundation
sudo python3 scripts/install_slicer_staging.py update
sudo docker exec makervault python3 /app/backend/manage.py test \
  core.tests.test_slicer_flush_settings \
  core.tests.test_slicer_flush_adapters \
  core.tests.test_slicer_creality_project \
  core.tests.test_slicer_creality_paint_diagnostics --noinput
sudo docker exec makervault python3 /app/backend/manage.py \
  diagnose_creality_paint_features --only flushing --deep
```

Until staging validates that custom Creality flush values survive
native preset restoration **and** demonstrably change intended
filament-change purge commands, do not promote any UI claim beyond
config request/storage. A printer- or firmware-owned purge may need
different verification; never silently replace Creality/Orca macros.
Independent toolheads remain unsupported for common single-nozzle
waste-volume controls, rather than receiving inappropriate CFS
behaviour. PR #171 remains draft/unmerged.


### Staging results: native flushing matrix survives, purge still unverified — 20 November 2026

Debian user updated application-only staging from 1b5c56f4 to 6031026a
(pinned Creality 7.3.1 worker unchanged). The four-suite test run
discovered **58 tests**: 54 passed, 4 errored due to a refactor
`NameError: MAX_FLUSH_MM3` in the Orca adapter. This is corrected by
commit **27bd5647**, importing the shared limit from the common
`slicer_flush_settings` module. A fresh staging test run is required;
the fix has not yet been verified on Debian.

`diagnose_creality_paint_features --only flushing --deep` sliced all
four native controls successfully. The following values are the
**G-code-emitted effective configuration**, not hypothetical requests:

| Control | T0 to T1 raw mm3 | T1 to T0 raw mm3 | Multiplier | Motion/M commands vs baseline |
| --- | ---: | ---: | ---: | --- |
| Baseline | 140 | 140 | 1 | baseline |
| Matrix only | 370 | 175 | 1 | unchanged |
| Multiplier only | 140 | 140 | 1.25 | unchanged |
| Combined | 370 | 175 | 1.25 | unchanged |

The edited matrix also survives to G-code with
`flush_volumes_changed=1`. This confirms **native config retention**;
it does **not** establish effective physical purge adjustment. No
diagnostic `FLUSH_START/FLUSH_END` segments or positive extrusion
moves inside those segments were seen in any variant. All emitted
motion and machine-command digests are identical. The selected
machine's actual macro was present but the redacted audit showed
no `flush_length_1..5` placeholders, no `multicolor_method`
conditional and no known vendor `M8200` handoff. The emitted
`multicolor_method=0`. Unlike this selected machine profile, the
official v7.3.1 Creality K2 0.4 machine profile has segmented
flush-length placeholders behind a multicolor condition. This makes
**selected profile provenance and effective printer-specific purge
mechanism** the next decisive question. Do not silently import the
upstream macro or force `multicolor_method`.

The fixed adapter should be retested using:

```bash
cd ~/MakerVault-Staging
git pull --ff-only origin feature/self-hosted-slicer-foundation
sudo python3 scripts/install_slicer_staging.py update
sudo docker exec makervault python3 /app/backend/manage.py test \
  core.tests.test_slicer_flush_settings \
  core.tests.test_slicer_flush_adapters \
  core.tests.test_slicer_creality_project \
  core.tests.test_slicer_creality_paint_diagnostics --noinput
```

Do not treat a successful 58/58 pass as final physical purge validation.
The user already ran the new flushing deep diagnostic successfully, so
there is no need to repeat it merely to test the missing import.


### Read-only Creality K2 profile provenance audit — 20 November 2026

The previously selected Creality preset has a filament-change script but
none of the segmented purge length placeholders present in upstream
Creality's K2 profile. Do not infer that the machine preset is wrong or
replace the vendor G-code. To find the source of the discrepancy,
the existing offline diagnostic now supports **`--profile-audit-only`**.

```bash
sudo docker exec makervault python3 /app/backend/manage.py \
  diagnose_creality_paint_features --profile-audit-only
```

The command selects the same completed single-object painted Creality
test job used by the original diagnostics. With `--job-id <UUID>`,
the test can be pinned to one specific stored job. It reads the *already
verified imported* printer and process profiles; it does **not**
start the worker, upload G-code, create a SliceJob or write any printer
configuration. Profile inheritance is traced only within the same
owner, engine, version, kind and import source scope, with the original
profile content hash checked at each step. Missing/ambiguous parents
fail closed.

Output includes:

- `machine_origin` and `process_origin`: for a fixed allowlist of
  purge-related native keys, whether the selected imported file
  defined the value directly, inherited it from a parent (including
  ancestry depth), or left it absent.
- `native_profile_merge`: the actual selected *resolved* machine
  plus *resolved/overridden* process settings. For each purge key,
  whether the machine defined it, whether process defined it,
  whether process displaced machine's value and whether they differ.
  Native project creation applies machine then process, so the
  process always wins when both provide a key.
- For `change_filament_gcode`, only script-presence, a SHA-256
  fingerprint, character length and boolean structural capabilities,
  including segmented flush placeholders and vendor handoff flags.
  **No printer macro lines, profile file paths, private names,
  credentials or filament scripts are returned.**
- `process_overrides_present` identifies whether saved process
  changes altered the imported resolved process before packaging.

Regression suite:

```bash
sudo docker exec makervault python3 /app/backend/manage.py test \
  core.tests.test_slicer_creality_profile_provenance \
  core.tests.test_slicer_flush_settings \
  core.tests.test_slicer_flush_adapters \
  core.tests.test_slicer_creality_project \
  core.tests.test_slicer_creality_paint_diagnostics --noinput
```

This is a **diagnostic addition**, not a production printer/macro
change. Follow-up: use the report to determine whether the selected
machine preset, an inherited parent, a process override or the
Creality CLI itself accounts for the short macro. If the resolved
profile differs from Creality's versioned official K2 profile, inspect
profile pack selection and source/variant in private rather than
importing/replacing machine commands. Physical purge volumes remain
unverified until an approved native command path is demonstrated.


### Verified staging provenance: selected K2 preset uses a short script (20 Nov 2026, 08:59 GMT)

User deployed `523e8c80` application-only with the pinned native worker
unchanged; the five Django test suites ran **62/62 passed**. Read-only
`diagnose_creality_paint_features --profile-audit-only` succeeded.

Its exact verified imported profile reports:

- Machine preset `change_filament_gcode` defined **in selected preset**,
  not an inherited parent: 212 characters, SHA-256
  `d848d81ee40a47a4483b85e232b4a583afa05fe9663e4272ebfd10b19f16a54b`.
  Machine preset has two levels of inheritance but the selected leaf
  directly replaces the filament-change script.
- Process preset has two inherited levels but never defines that
  script. The selected process did **not** override machine's script,
  and saved `process_overrides_present=false`.
- Resolved effective printer script has no `flush_length` placeholders,
  `multicolor_method` conditional or `M8200` marker, consistent
  with prior native G-code A/B output. Native nozzle volume is 183
  mm³, purge_in_prime_tower=0, and single_extruder_multi_material is
  explicitly defined by selected machine preset.
- Neither machine nor process preset defines
  `flush_volumes_matrix`, `flush_multiplier`,
  `flush_volumes_changed` or `multicolor_method`. The slicer
  defaults/projects supply these values in the final 3MF.

**Additional pinned upstream comparison:** Official Creality Print v7.3.1
machine profiles have the following structural signatures (not
firmware-validating tests):

| Native machine preset | Change script chars | flush_length segmented | M8200 | multicolor_method conditional | nozzle_volume mm³ |
| --- | ---: | --- | --- | --- | ---: |
| K2 0.4 mm | 7183 | yes | yes | yes | 183 |
| K2 Pro 0.4 mm | 7085 | yes | yes | yes | 183 |
| K2 Plus 0.4 mm | 7644 | yes | yes | yes | 268 |
| K2 SE 0.4 mm | 141 | no | no | no | 178 |
| **MakerVault selected imported preset** | **212** | **no** | **no** | **no** | **183** |

Source: official versioned
[Creality K2](https://github.com/CrealityOfficial/CrealityPrint/blob/v7.3.1/resources/profiles/Creality/machine/Creality%20K2%200.4%20nozzle.json),
[K2 Pro](https://github.com/CrealityOfficial/CrealityPrint/blob/v7.3.1/resources/profiles/Creality/machine/Creality%20K2%20Pro%200.4%20nozzle.json),
[K2 Plus](https://github.com/CrealityOfficial/CrealityPrint/blob/v7.3.1/resources/profiles/Creality/machine/Creality%20K2%20Plus%200.4%20nozzle.json),
[K2 SE](https://github.com/CrealityOfficial/CrealityPrint/blob/v7.3.1/resources/profiles/Creality/machine/Creality%20K2%20SE%200.4%20nozzle.json).

The imported 212-character script **does not structurally match**
the known K2-family official v7.3.1 script variants above. We have not
yet identified its original source, chosen profile variant or intended
firmware-owned purge behaviour. Do **not** automatically replace it
with upstream long G-code or infer that this would be printer-safe.
There are community reports of K2 non-Pro firmware not respecting the
Creality flushing table; treat those as *anecdotes only*, not proof
about the user's specific printer or firmware.

Next useful gate: compare the selected imported printer profile's
name/variant and source scope in the authorized local profile UI
against the matching official K2 0.4 mm preset and confirm it is the
intended CFS mode. Keep the user's existing saved machine preset
unchanged. Only if a tested, approved native profile and slicer path
supports directional purge commands should the UI claim its
flushing-volume changes affect actual filament waste. Future printer
types stay behind separate engine and topology capabilities.


### Printer-independent flushing foundation gate — 20 November 2026

**Decision:** the non-Pro K2's unverified physical purge mechanism
must not prevent the shared flushing foundation from supporting other
eligible printers. The common contract remains independent of printer
brand; physical applicability and actual delivered purge are separate
verification questions.

The adapter capability now exposes `supported_for_encoding_only`
and a bounded machine-readable `reason` for unsupported topologies
alongside the existing `supported` field, and continues to report
`purge_validation=native_unverified`. **Neither supported field is
proof that any printer will execute the requested waste volume.**
Existing encoding support is currently limited to a verified
single-nozzle material changer with one nozzle, with 2–16 logical
materials on Orca and 2 assigned logical materials in the present
Creality 3MF builder. Distinct independent-toolhead/toolchanger/IDEX
mechanisms are recognized but deliberately cannot use these
single-nozzle waste-volume adapters; add their own verified adapters
when supported.

The additional regression tests exercise:
- A single verified physical-to-logical map with different physical
  slot order for **2, 3, 4, 8 and 16** Orca logical materials. The
  directional row-major index is correct; opposite-direction and
  untouched transitions remain unchanged.
- Absent native matrices with **3 and 4** logical materials. These
  require every off-diagonal transition to be explicitly supplied,
  rather than inventing zero purge defaults.
- A single printer-neutral directional request encoded independently
  through Orca's per-nozzle multiplier vector and Creality's scalar
  multiplier. Vendor machine scripts remain byte-for-byte unchanged
  by this operation.
- Known unsupported or unknown printer topologies are rejected with
  explicit capability reasons. A supported encoder is always still
  marked `native_unverified` until actual machine-specific G-code
  and firmware evidence is available.

A number of future printer types, such as independent toolheads,
could have little or no nozzle-purge waste, or could use entirely
different head cleaning operations. Their future adapters must expose
the appropriate **per-toolhead** capabilities instead of reusing
single-nozzle changer purge controls. This prevents the K2 firmware
unknown from blocking general architecture evolution **without**
asserting that unverified printer models currently support active
flushing adjustment.

These changes are backend capability and tests only. They do not
modify any machine G-code, native engine binaries, worker code or
printer. Public PR #171 remains draft and requires the new tests to
pass on Debian staging.


### Non-K2 printer-profile native compatibility suite — 20 November 2026

A separate CLI diagnostic is available at
`backend/core/management/commands/diagnose_slicer_printer_profiles.py`.
This is an **offline-only**, user-selected native compatibility fixture
that makes no changes to imported files, the database, worker, printer
profiles, vendor macros, physical printers, or firmware. It never stores
or submits printable G-code.

**Intended first profile families (source-verified, not yet runtime
validated by MakerVault's pinned worker):**

- [OrcaSlicer v2.4.2 Bambu Lab A1 0.4 mm](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.4.2/resources/profiles/BBL/machine/Bambu%20Lab%20A1%200.4%20nozzle.json),
  which declares a single `nozzle_diameter=["0.4"]`. Test two
  distinct logical filament assignments and then three/four with
  separately selected, compatible native filament presets to exercise
  the same one-nozzle directional matrix contract.
- [OrcaSlicer v2.4.2 Snapmaker U1 0.4 mm](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.4.2/resources/profiles/Snapmaker/machine/Snapmaker%20U1%20%280.4%20nozzle%29.json),
  which declares four native `nozzle_diameter` entries. Test the
  independent toolhead boundary with **four** explicitly selected
  native filament assignments. This topology must not receive a
  single-nozzle flushing matrix override.
- A second verified **Creality Print** machine profile (if imported)
  may be smoke-tested with one filament or its existing verified
  two-material single-nozzle project builder. It must never
  inherit a K2-specific purge override merely because the engine
  is Creality.

The command enforces exact owner/engine/version matching, approved
native import resolution/integrity, native nozzle counts, strictly
matching native filament diameters, verified origin-aligned
rectangular beds and 1–4 bounded fixture models.
For a one-nozzle changer it may compare a **single T0→T1** native
directional matrix adjustment of **+25 mm³** *only when the complete
original native matrix exists*. All remaining transitions are
inherited unchanged. No automatic colour-based estimates or zeros are
invented. Existing original printer machine macros remain untouched.

**Step 1: see which profiles actually exist in the user's database.**

```bash
sudo docker exec makervault python3 /app/backend/manage.py \
  diagnose_slicer_printer_profiles --engine orcaslicer --list-profiles
sudo docker exec makervault python3 /app/backend/manage.py \
  diagnose_slicer_printer_profiles --engine crealityprint --list-profiles
```

These list imported profile UUIDs, locally stored preset names,
source scopes, versions, kinds and statuses. Where the database has
many profiles, use `--name-contains "Bambu Lab A1"` or
`--name-contains "Snapmaker U1"` with `--list-profiles` to find the
exact native variant without dumping all imported profiles.
Import the selected **complete, correct-version** manufacturer/native
profile pack and verify parent inheritance before attempting a slice.
Never substitute a profile from another engine or version.

**Step 2: read-only per-printer preflight (no native worker call).**

```bash
sudo docker exec makervault python3 /app/backend/manage.py \
  diagnose_slicer_printer_profiles --engine orcaslicer \
  --topology single_nozzle_changer \
  --printer-profile-id <A1_PRINTER_UUID> \
  --process-profile-id <A1_PROCESS_UUID> \
  --filament-profile-id <FILAMENT_0_UUID> \
  --filament-profile-id <FILAMENT_1_UUID>
```

**Step 3: repeat with `--native` to perform the actual pinned
isolated worker slice.** Append `--test-flush` only for a one-nozzle
Orca changer with a complete native matrix to perform an A/B slice.
The resulting output reports bounded G-code size, SHA-256, canonical
motion digest, machine-command digest and extrusion-count evidence;
it never publishes raw G-code. A changed hash alone does **not**
establish changed purge or physically honoured flushing.

For the four-head U1 preflight, use
`--topology independent_toolheads` with its U1 printer and process
UUIDs plus four compatible filament UUIDs, then optionally
`--native`. Do **not** pass `--test-flush`: its one-nozzle adapter
must reject that topology. A successfully sliced multi-tool 3MF
demonstrates worker/project compatibility only, not an authenticated
printer submission route or physical toolchange safety.

**Unit suite** (run after application-only staging update; no worker
refresh needed):

```bash
sudo docker exec makervault python3 /app/backend/manage.py test \
  core.tests.test_slicer_printer_compatibility \
  core.tests.test_slicer_flush_adapters \
  core.tests.test_slicer_flush_settings \
  core.tests.test_slicer_creality_project \
  core.tests.test_slicer_creality_paint_diagnostics \
  core.tests.test_slicer_creality_profile_provenance --noinput
```

**Evidence boundary:** the unit tests use real 3MF fixture generation
and verified routing but do not run the installed native binaries.
The additional printer-native checks remain **unverified until
executed on Debian against actually imported non-K2 profiles**. An
unavailable profile is a blocked test rather than a compatibility
failure; do not claim the user already has A1 or U1 profiles imported.
No printer macro replacement, engine installation or hardware
communication is authorised.


### Creality Print K1 preflight: correct native filament diameter representation — 20 November 2026

Actual Debian `--engine crealityprint --topology single_material` preflight
for the imported Creality Print 7.3.1 K1 0.4 mm trio initially failed
`Native filament diameter is missing or invalid` **before native slicing**.
The diagnostic mistakenly reused Orca's one-element-array
`filament_diameter` validator for Creality Print's scalar
`filament_diameter="1.75"` native profile format. This was a fixture
validator bug, not a failure in the selected official native K1 preset
or the Creality engine.

The management command now dispatches diameter parsing by slicer
engine: Orca requires the original exactly-one-element array;
Creality Print requires a scalar finite positive diameter within
the accepted filament bounds. Unknown encodings, booleans,
out-of-range values and mixed-diameter multi-filament palettes fail
closed. A dedicated regression test verifies both representations
and that cross-engine interchange is rejected.

**This new correction is not yet exercised in Debian**. After
application-only update, rerun
`core.tests.test_slicer_printer_compatibility` (now seven tests), and
repeat the exact K1 structural preflight:

```bash
sudo docker exec makervault python3 /app/backend/manage.py \
  diagnose_slicer_printer_profiles --engine crealityprint \
  --topology single_material \
  --printer-profile-id f2150019-d42a-478a-aa1a-a7141a340eb5 \
  --process-profile-id dbf937e0-6dfd-4a8a-8549-75449036dee0 \
  --filament-profile-id db839c91-38b7-4d21-9734-f8cf9ea5fdd4
```

If and only if this passes, rerun with `--native` to test
the verified pinned Creality Print 7.3.1 worker. No firmware,
printer transfer, imported profile writes or native worker
rebuild are required. A successful **single-material** K1 native
slice would establish profile acceptance on a second printer but
would not demonstrate multi-material purge control.


### Real non-K2 Creality Print 7.3.1 K1 single-material acceptance — 20 Nov 2026

The user's pinned isolated worker **successfully sliced** the K1
single-material tetrahedron using exact imported Creality Print
7.3.1 native presets. Verified runtime results:

- K1 machine `f2150019-d42a-478a-aa1a-a7141a340eb5`,
  K1 process `dbf937e0-6dfd-4a8a-8549-75449036dee0`,
  K1 Soleyin Ultra PLA filament
  `db839c91-38b7-4d21-9734-f8cf9ea5fdd4`.
- Preflight passed: 1 nozzle, 1.75 mm native Creality
  scalar filament diameter, 220 × 220 mm rectangular bed.
- Native result `native_run=sliced`, 90,687 G-code bytes,
  G-code SHA-256 `d7d4857371700cbd0ee7004f1250d7e3674137adeb80527015a87bdd3c14fc65`,
  motion SHA-256 `faead65169b64d51d7bce279ebde2a773afee191f91daedd588e69625c7859c8`,
  machine-command SHA-256 `9a9e7022ca62c3f18d3ed2d22dca2665318e1c03f191f3004f9bf553319c20ce`.
- The G-code passes the existing native approval/acceptance
  extrusion-presence gate. The diagnostic nevertheless reported
  `g1_with_extrusion=0`. Inspection found inconsistent regex
  definitions: acceptance permits `E.25`/`E-.25`, while the old
  counter required `E0.25`/`E-0.25`. The counter is now aligned
  with the native acceptance syntax and has a focused test; an
  updated K1 native run is required before concluding its actual
  extrusion-move count. Do not infer the original G-code necessarily
  uses any particular decimal format without inspecting it privately.
- `native_flush_encoding_supported=false` is expected for
  `topology=single_material`, and physical purge remains
  `unverified`. Passing K1 is **native non-K2 single-material
  compatibility only**, not proof of K1 multicolour or K2 firmware
  purge adjustment.

Only diagnostic counting/test code changed in this follow-up.
The native engine, approved worker, imported presets and all machine
macros remain untouched.


### Desktop multiplier-reference regression (K2 four-colour example)

Two desktop UI screenshots for the same four swatches show OrcaSlicer
at native multiplier **1.00** and Creality Print at **1.30**.
The observed four-by-four matrices (directional row-major, mm³) are:

```text
Orca 1.00
   0 480 170 509
 212   0 199 301
 170 460   0 482
 291 380 276   0

Creality Print 1.30
   0 624 220 661
 237   0 220 353
 220 598   0 626
 378 493 358   0
```

Many pairs approximately match 1.30× (e.g. Orca T0→T1
480, Creality 624), but **not all pairs match**. Do not hardcode
a 1.3 scaling factor or infer equivalent colour/material settings.
These are UI observations; the screenshot alone does not prove
whether the matrix has already been multiplied or whether firmware
executes these values. Nor should a user-entered 480mm³ be translated
to 624mm³ merely because Creality happens to display 1.30 by default.

Regression coverage in `test_slicer_flush_adapters.py` explicitly
preserves each native matrix and native multiplier when no override is
specified. With an explicit directional override, the adapters write
**the exact requested native matrix cell once** without applying an
extra multiplier; the other directional cells, native multiplier and
manufacturer scripts remain intact. An explicit multiplier edit
writes only the engine's correct native representation (Orca vector
or Creality scalar), without eagerly changing matrix cells.

The final purge amount used by Creality's native slicer/firmware has
**not** been inferred from the UI multiplier; physical effectiveness
remains unverified on the K2. Before making any calculation changes,
perform a separate controlled native app/worker A/B experiment that
distinguishes pre-scaled matrix entries, native multiplier application
and machine-level purge commands. Do not alter native K2 machine
macros or printer databases during these tests.


### Creality Print 7.3.1 native two-filament flushing A/B (offline-only)

The generic `diagnose_slicer_printer_profiles` command now supports
`--native --test-flush` with `--engine crealityprint` and **exactly
two** explicitly selected, matched-version native filament profiles
on a verified **single-nozzle changer**. This is a read-only
native-worker diagnostic: never prints, stores a slice job, changes
a machine macro or modifies the approved worker. Before sending any
worker request it builds a baseline and two *isolated* candidate
self-contained Creality 3MF projects and verifies the same geometry,
metadata and vendor machine scripts.

It runs up to three bounded native slices using the **same geometry**:
baseline, T0→T1 native matrix cell **+25mm³** (T1→T0 and
all other cells unchanged), and a native scalar-multiplier-only
control (1.00 if source is not 1.00, otherwise 1.30). The latter
only runs when the resolved native project actually declares
`flush_multiplier` and passes validation; an absent default is
**not guessed**. Native 3MF control settings are verified before
sending them to the worker.

Run the following with the **already imported** Creality Print
7.3.1 K2 native profile candidates (do not substitute Orca profiles):

```bash
sudo docker exec makervault python3 /app/backend/manage.py \
  diagnose_slicer_printer_profiles \
  --engine crealityprint --topology single_nozzle_changer \
  --printer-profile-id 91b19730-66f5-4b5f-bd7d-b08fbb4ee768 \
  --process-profile-id 0c90fa89-a193-48b6-ac94-a69792230163 \
  --filament-profile-id e9c1274c-d95b-4592-87e5-03a645d699aa \
  --filament-profile-id eb8473e9-f993-4c6e-8cc4-fb357e3ae782 \
  --native --test-flush
```

The selected K2 machine still requires the **separate
provenance/machine-macro audit**: its imported tool-change macro has
previously differed from the official manufacturer variant.
A successful A/B does not approve it for physical printing or
establish effective purge. Both selected filament presets must
resolve with compatible native keys and 1.75mm diameter; fail-closed
error means inspect those preset differences, not bypass validation.

Output provides a baseline and two independent controls including
G-code digest, motion digest, M-command digest, G1 extrusion count,
T0/T1 selection counts and booleans for output versus motion versus
machine-command differences. A changed full G-code hash may mean
*only metadata*. A changed motion hash may include print/tower
motion rather than true purge. T0/T1 selections are not proof of
actual printer material-change operation. Firmware-owned purge
could remain invisible. A baseline without an effective native
multi-material switch is **inconclusive**, not a passing flush test.

**Matrix provenance:** When imported printer/process settings
supply `flush_volumes_matrix`, the report says which source.
If neither supplies one, `matrix_source` is
`candidate_builder_140mm3_fallback_unverified`. This is
MakerVault's conservative project construction fallback, **not**
Creality Print's desktop 1.30× auto-calculation; never present it
as the user's original native settings. Do not infer multiplier
post-processing from these controls until native G-code semantics
are understood; there is no additional 1.30 scaling in the adapters.

Focused new unit tests (no worker needed):

```bash
sudo docker exec makervault python3 /app/backend/manage.py test \
  core.tests.test_slicer_printer_compatibility \
  core.tests.test_slicer_flush_adapters \
  core.tests.test_slicer_creality_project --noinput
```

Do not run `refresh-worker`: this feature only changes Django
diagnostic files and unit tests.


### Two-object CFS worker preflight blocker, resolved in source — 20 Nov 2026

Initial native K2 two-filament A/B fixture passed 45/45 Django
unit tests but failed at **`validating model and profile payloads`**
before launching the binary. The redacted existing worker log
confirmed `WorkerError, validation-error`. Source inspection found
a deterministic validator mismatch: `validate_creality_project()`
unconditionally enabled `allow_creality_combined_paint=True` when
calling `validate_worker_3mf()`, but that option strictly requires
**one painted object**. The diagnostic intentionally builds **two
plain objects** assigned to T0/T1, so its correct model was rejected.

The worker validator now passes
`allow_creality_combined_paint=(object_count == 1)`: it still
validates one painted object via the painting-specific extension and
validates two plain objects via the strict normal tool assignments.
Worker tests now exercise two real unpainted objects and both tool
assignments without mocking the nested geometry validator, plus
explicit checks that painted single-object projects retain their
extension. No unsafe general bypass or vendor machine-script change.

**Worker refresh is required for this particular fix**, unlike
earlier application-only diagnostics:

```bash
cd ~/MakerVault-Staging
git pull --ff-only origin feature/self-hosted-slicer-foundation
sudo python3 scripts/install_slicer_staging.py refresh-worker
```

This refresh rebuilds the **existing isolated worker Python code**;
approved native engine binary hashes must remain unchanged. Run
focused worker `slicer_worker.tests.test_creality_project_validation`
and Django compatibility tests before repeating the K2 native
`--test-flush` command above. A pass of the validation gate
alone is not proof that Creality's native binary accepts the
project or generates meaningful flush G-code.


### Native 1.00 versus 1.30 multiplier and prime-tower X/Y experiment

A confirmed Creality Print 7.3.1 **K2 two-filament offline** run generated
304,288 bytes of G-code, 5,470 G1 extrusion moves and 24 T0 + 24 T1
selections after fixing the worker's two-object validation mode.
Changing its T0→T1 matrix cell **140 → 165mm³** changed the full G-code
SHA256 only; the motion and M-command digests were **identical**.
The selected imported presets lacked both a verified original matrix
(the baseline was MakerVault's **140mm³ diagnostic fallback**) and
a native `flush_multiplier` field. Consequently the first version
skipped multiplier A/B entirely. Those findings do **not** prove that
the K2 physically purges a particular amount.

The offline diagnostic now also constructs **explicit disposable**
scalar multiplier **1.00** and **1.30** controls, regardless of whether
the imported project declared the setting. These are deliberately
labelled `explicit_disposable_1_00_vs_1_30_not_native_default`;
neither is claimed to be the printer's native default. The controls
preserve the same model, resolved native presets, 4×4 matrix, native
tool mappings and every manufacturer machine macro. Their only
effective configuration change is the `flush_multiplier` project
field. Unlike the directional test, these controls do **not** adjust
individual matrix cells. All controls run using the existing pinned
authenticated worker; no printer communication is performed.

A conservative per-G-code tower deposition parser now reports
`native_tower_deposition_baseline` and
`creality_flush_controls.<name>.tower_deposition`. Only positive-E
X/Y movements **explicitly labelled** by native
`;TYPE: Wipe tower` / `;FEATURE: Prime tower` (or equivalent
prime/purge/wipe tower feature label) qualify. For these tagged moves
the report contains X/Y deposition bounding width and depth,
positive E length (raw filament millimetres), XY toolpath length,
number of deposition moves, and whether tower dimensions or extrusion
differ from the baseline. Absolute/relative E, G92 E resets, and
non-tower move sections are handled separately. There is no raw
G-code, machine macro or private path in the report.

**Safety and interpretation:** if the Creality native G-code does not
label tower moves, each tower field is reported as
`unavailable_no_verified_tower_moves` and comparison flags are
`null` — **not** as proof of zero or unchanged tower deposition.
A tower's X/Y footprint may remain fixed while path length or E
changes. Motion digests cover complete G-code and help catch global
changes; neither the tower metrics nor tool selections are physical
CFS purge verification. Do not use these diagnostic G-code outputs
for printing.

After the focused test suite passes, rerun the **same existing**
K2 two-filament `diagnose_slicer_printer_profiles --native --test-flush`
command above. The report will have a baseline, a directional T0→T1
control, and explicit `multiplier_1_0` and `multiplier_1_3`
controls. This change only touches backend Python, tests and docs:
`sudo python3 scripts/install_slicer_staging.py update` is
sufficient; **do not refresh the worker**.


### Follow-up: stronger 1.00 versus 2.00 comparison (20 Nov 2026)

The previous **1.00 versus 1.30** controls both sliced successfully, with
identical measured native tower width/depth (22.898 × 22.898mm),
tower XY path length (28,613.328mm), tower positive-E length
(1,090.971mm), 3,247 tower deposition moves, and identical motion
and machine-command hashes. Those figures are historical results;
they are **not** outcomes of the new comparison.

The current offline A/B control has been increased to
**`flush_multiplier=1.00` versus `2.00`**. This doubles the requested
multiplier while preserving the same geometry, native profile-derived
settings, fallback matrix, filament assignments, and manufacturer
tool-change macros. It remains an explicit *disposable diagnostic
control*, **not** a claim that a selected Creality K2 profile natively
defaults to either value. The output controls are now
`multiplier_1_0` and `multiplier_2_0`. The same
`--native --test-flush` command and existing app-only staging update
are sufficient; no pinned worker change is required.

Compare global motion and machine-command digests, labelled tower
X/Y bounding width/depth, tower XY path distance, tower positive-E
length and tower deposition moves. A larger multiplier does not
necessarily change external tower X/Y dimensions; increased material
could change paths within a fixed footprint or printer-side purge
commands. If even 2.00 generates identical native motions, investigate
whether Creality 7.3.1's project loader honours
`flush_multiplier` / `flush_volumes_changed` and its
`different_settings_to_system` override flags *before* altering
production flushing calculations. Physical K2 flushing remains
unverified; do not print diagnostic G-code.


### Investigating whether native Creality 7.3.1 reload drops flushing overrides

The real K2 1.00 vs 2.00 run also showed identical 22.898mm tower
X/Y dimensions, 28,613.328mm XY tower path, 1,090.971mm positive-E
tower extrusion and exactly the same global motion and machine-command
fingerprints. This supports investigating **config reload semantics**
instead of increasing the multiplier again.

MakerVault already uses `different_settings_to_system[0]` to preserve
explicit **support** overrides during Creality's project preset reload
(`_mark_creality_support_overrides`), while the current production
flushing adapter only writes `flush_multiplier`,
`flush_volumes_matrix`, and `flush_volumes_changed` directly into
`Metadata/project_settings.config`.

The offline `diagnose_slicer_printer_profiles --native --test-flush`
command now adds two **additional, disposable** projects:
`multiplier_1_0_marked` and `multiplier_2_0_marked`. Each matches
its corresponding unmarked multiplier project byte-for-byte in every
other archive member and **every configuration field** except the
native `different_settings_to_system[0]` process-override list,
which gains the three flushing keys above while preserving existing
support overrides and all palette entries.

The new output compares each marked control with its unmarked
counterpart for global motion commands, machine M commands and tagged
tower deposition, as well as with the unchanged baseline. Only
read-only authenticated native slicing is performed. No printing,
saved presets, printer/database updates, vendor machine G-code edits,
worker code or approved engine binaries change.

This experiment is **not yet evidence** that those fields belong in
the native process override list, nor that Creality 7.3.1 honours them.
An unchanged marked A/B would narrow the investigation toward either
native UI matrix recomputation, separate flush-volume routing, CLI
configuration overrides, or firmware-side K2 purging. Avoid a
production change until native A/B behaviour confirms it.

New focused Django suites:

```bash
sudo docker exec makervault python3 /app/backend/manage.py test \
  core.tests.test_slicer_printer_compatibility \
  core.tests.test_slicer_tower_diagnostics \
  core.tests.test_slicer_flush_adapters \
  core.tests.test_slicer_creality_project --noinput
```

Then rerun the same previously successful exact K2 native
`--test-flush` command. This is an **application-only** change;
run `sudo python3 scripts/install_slicer_staging.py update`, not
`refresh-worker`. The output now includes two additional marked
controls; the isolated worker and native engines remain pinned.


## Purge destination isolation (20 November 2026, app-only, offline)

After the original six-way K2 comparison (baseline, +25 mm³ directional,
explicit 1.0/2.0 multiplier, and two native override-marker controls) produced
**identical G0/G1, machine-command and tower-deposition digests**, a further
source-guided experiment was added. Official Creality Print v7.3.1
`Print.cpp::_make_wipe_tower()` uses `prime_volume` / minimum tower volume
in some paths when `purge_in_prime_tower=0`, while the matrix multiplied by
`flush_multiplier` may still feed another purge destination. The exact
effective K2 runtime settings are **not yet proven**.

The existing `--native --test-flush` command now slices **eight** disposable
controls: the previous six slices plus `purge_route_toolchange`
(`purge_in_prime_tower=0`) and `purge_route_tower`
(`purge_in_prime_tower=1`). Both new candidates are based on the same
explicit `multiplier_2_0` project; they change **only** the route flag,
preserving the matrix, multiplier, filament bindings, geometry, vendor printer
scripts, all other native settings, and pinned worker. Comparison booleans
`*_vs_multiplier_2_0` report motion, machine-command and tower E differences
against the identical-multiplier reference. A source-project-only redacted
`creality_purge_route_project_audit` reports flag status, prime-volume
presence/value, matrix presence and scalar multiplier; this is **not** a read
of the effective in-memory native Creality runtime configuration.

Apply the **app-only** staging update (do not refresh the worker):

```bash
cd ~/MakerVault-Staging
git pull --ff-only origin feature/self-hosted-slicer-foundation
sudo python3 scripts/install_slicer_staging.py update
sudo docker exec makervault python3 /app/backend/manage.py test \
  core.tests.test_slicer_printer_compatibility \
  core.tests.test_slicer_tower_diagnostics \
  core.tests.test_slicer_flush_adapters \
  core.tests.test_slicer_creality_project --noinput
sudo docker exec makervault python3 /app/backend/manage.py \
  diagnose_slicer_printer_profiles \
  --engine crealityprint --topology single_nozzle_changer \
  --printer-profile-id 91b19730-66f5-4b5f-bd7d-b08fbb4ee768 \
  --process-profile-id 0c90fa89-a193-48b6-ac94-a69792230163 \
  --filament-profile-id e9c1274c-d95b-4592-87e5-03a645d699aa \
  --filament-profile-id eb8473e9-f993-4c6e-8cc4-fb357e3ae782 \
  --native --test-flush
```

Expected focused Django test count: **56** (previous 53 + 3); the real binary
must still be tested on staging. If switching the route alters tower/toolpath,
investigate native purge routing and effective profile inheritance. If neither
route alters executable output, investigate whether native 3MF configuration is
restored/overridden during CLI loading or whether the selected vendor tool-change
macro produces only printer-firmware-owned purge instructions. Do not infer
physical purge adequacy from any offline result, merge production flushing
changes, submit diagnostic G-code to the printer, or change worker/firmware.


### Follow-up after stale 53-test output

A server log showing `Already up to date`, **53 tests** and no
`creality_purge_route_project_audit` / `purge_route_tower` output is still
running the earlier diagnostics, not the new A/B implementation. Verify the
checked-out commit and application container before interpreting output:

```bash
cd ~/MakerVault-Staging
git fetch origin feature/self-hosted-slicer-foundation
git status --short --branch
git rev-parse --short HEAD
git rev-parse --short origin/feature/self-hosted-slicer-foundation
sudo docker exec makervault sh -c 'grep -n "_validate_creality_purge_route_pair" /app/backend/core/management/commands/diagnose_slicer_printer_profiles.py'
```

The parent-relative validation was corrected in commits `db206b4d`,
`ec744d48` and `bcf1dc0b`; the earlier route implementation compared a
fixed multiplier-2.0 control to a baseline lacking the multiplier and would
reject the intended change as unrelated. New regression now proves the
baseline/parent comparison and rejects unrelated configuration mutations.
Do not reset/rebase the working tree blindly; if HEAD differs from the
remote branch, inspect `git status` and switch only after checking any
local modifications. The pinned worker remains unchanged.


## Creality native generated-config sensitivity check (20 November 2026)

The preceding eight-way K2 server run passed 56/56 tests and eight offline
slices. Project flags explicitly toggled `purge_in_prime_tower`, yet executable
motion, machine commands, tower size, and tagged tower E all remained identical.
The project archive inspection proves **serialised settings**, not effective
native `PrintConfig` values.

A new offline-only check adds:

- `creality_emitted_gcode_baseline_audit`: strict, redacted extraction of only
  recognised scalar/boolean setting comments from returned native G-code;
  excludes G-code lines, printer macros and whole flush matrices. Missing
  comments are reported as absent, **not** as proof of ignored settings.
- `emitted_gcode_settings_comparison` for each control: records only safe
  sanitised numeric/boolean values and names of changed emitted settings.
  This is emitted metadata, still **not direct introspection into Creality's
  in-memory effective configuration**.
- `prime_volume_positive_control`: one additional disposable native 3MF,
  based on the exact multiplier-2.0 control, that changes only
  `prime_volume=45→180` mm³ while leaving vendor scripts, geometry,
  matrix, multiplier and tool mapping untouched. This source-backed setting
  ordinarily affects prime tower generation; unchanged output is evidence
  supporting a loader/override hypothesis, but is not conclusive if another
  native minimum or purge mode dominates it.

The diagnostic now has **nine** native slices total and the expected
focused unit-test count is **59** (previous 56 plus 3). No worker, runtime
binary or production adapter updates are needed. The positive control is
never submitted to a printer.

```bash
cd ~/MakerVault-Staging
git pull --ff-only origin feature/self-hosted-slicer-foundation
sudo python3 scripts/install_slicer_staging.py update
sudo docker exec makervault python3 /app/backend/manage.py test \
  core.tests.test_slicer_printer_compatibility \
  core.tests.test_slicer_tower_diagnostics \
  core.tests.test_slicer_flush_adapters \
  core.tests.test_slicer_creality_project --noinput
sudo docker exec makervault python3 /app/backend/manage.py \
  diagnose_slicer_printer_profiles \
  --engine crealityprint --topology single_nozzle_changer \
  --printer-profile-id 91b19730-66f5-4b5f-bd7d-b08fbb4ee768 \
  --process-profile-id 0c90fa89-a193-48b6-ac94-a69792230163 \
  --filament-profile-id e9c1274c-d95b-4592-87e5-03a645d699aa \
  --filament-profile-id eb8473e9-f993-4c6e-8cc4-fb357e3ae782 \
  --native --test-flush
```

Interpret in order: confirm `prime_volume_positive_control` executed,
compare its native motion and tower extrusion against `multiplier_2_0`,
then check whether any emitted setting comments track the 3MF changes. If
no emitted settings are present, stop treating G-code metadata as effective
configuration proof and move to a source-instrumented/round-trip loader
probe in an independently approved worker build; do not change the pinned
engine or claim a physical flushing fix.


## Isolating GUI-style native preset merge (20 Nov 2026, source-based follow-up)

The completed **59/59** staging suite and **nine** offline Creality v7.3.1
K2 slices reveal a useful split in G-code-emitted comments:

- Explicit `flush_multiplier=2.0` survives into generated G-code comments,
  although the executable motion and tagged tower extrusion remain unchanged.
- Explicit `purge_in_prime_tower=1` in the generated 3MF is emitted as **0**.
- Explicit `prime_volume=180` in the generated 3MF is emitted as **45**.
- No control changed the G0/G1 or machine-command digests, or the tower E.
  These are generated G-code comment observations, not direct native
  in-memory `PrintConfig` instrumentation.

The **exact official v7.3.1 source** contains
`src/slic3r/CLI/SliceCommand.cpp::refresh_creality_project_configuration`
(lines ~2006–2057), which loads the Creality system presets, applies the
project configuration to defaults, invokes
`PresetBundle::load_config_model(...)`, and then **replaces**
`m_print_config = project_bundle.full_config()`. Called by
`prepare_configuration` before slicing. The associated
`src/libslic3r/PresetBundle.cpp::load_config_file_config` (around
lines 3965–4050) reads `different_settings_to_system[0]` as process
option override identifiers. This is a specific hypothesis for why those
two values revert while the multiplier is present in metadata, but
the actual diagnosis requires an A/B test.

Two **additional disposable 3MF controls** have been added, without
changing the production Creality adapter or worker:

- `prime_volume_marked`: exact same 180 mm³ positive-control project,
  with **only** `prime_volume` appended to the existing process
  `different_settings_to_system[0]` list.
- `purge_route_tower_marked`: exact same purge-in-tower project at
  explicit multiplier 2.0, with **only** `purge_in_prime_tower` appended
  to its process override list.

Each test preserves the native printer macros, matrix, other project
settings, geometry, and remaining five entries of the override vector.
The existing unmarked controls remain in place for direct comparison.
New comparisons include `emitted_keys_changed_vs_unmarked`, motion,
machine commands and tagged tower E. The output is limited to sanitised
config values and hashes.

Expected focused Django tests: **61** (59 prior + 2).
Expected offline native Creality slices: **11** (nine prior + two marked).
These new runs **have not yet been executed on staging**.

```bash
cd ~/MakerVault-Staging
git pull --ff-only origin feature/self-hosted-slicer-foundation
sudo python3 scripts/install_slicer_staging.py update
sudo docker exec makervault python3 /app/backend/manage.py test \
  core.tests.test_slicer_printer_compatibility \
  core.tests.test_slicer_tower_diagnostics \
  core.tests.test_slicer_flush_adapters \
  core.tests.test_slicer_creality_project --noinput
sudo docker exec makervault python3 /app/backend/manage.py \
  diagnose_slicer_printer_profiles \
  --engine crealityprint --topology single_nozzle_changer \
  --printer-profile-id 91b19730-66f5-4b5f-bd7d-b08fbb4ee768 \
  --process-profile-id 0c90fa89-a193-48b6-ac94-a69792230163 \
  --filament-profile-id e9c1274c-d95b-4592-87e5-03a645d699aa \
  --filament-profile-id eb8473e9-f993-4c6e-8cc4-fb357e3ae782 \
  --native --test-flush
```

If either marked version now emits the expected configuration
(`prime_volume=180` or `purge_in_prime_tower=1`) and especially if
its motion/tower deposition changes, this establishes an actionable
preset-merge contract for the native 3MF route. It still does not establish
safe physical purge volumes; do not merge production flushing changes or
send diagnostic G-code to the printer.


## Marked-control reporting regression fix (20 Nov 2026 23:27 GMT)

Staging pulled `e9d42a90..f5760366`; pinned worker remained unchanged;
**61/61** focused tests passed. The expanded native command subsequently
failed while **assembling the diagnostic JSON**, after reaching the
marked-control reporting loop:

```text
KeyError: 'prime_volume'
diagnose_slicer_printer_profiles.py:944
```

The old terminal loop incorrectly guessed every marked control's parent by
stripping `_marked`: `prime_volume_marked` was compared to nonexistent
`prime_volume` instead of `prime_volume_positive_control`. A preceding
explicit comparison block already did the correct lookup, but the duplicate
loop overwrote it and raised. This is an application diagnostic reporting
bug; it does not demonstrate a native engine failure.

Fixed by replacing both reporting paths with a single
`_creality_marked_result_comparison` helper and explicitly enumerating all
four parent pairs (both multipliers, `prime_volume_positive_control` and
`purge_route_tower`). Added regression coverage including missing-parent
rejection. New expected focused test count **62** and native offline
scenario count remains **11**. Because previous output was interrupted,
do not claim the 11 native slices or preset-marking result are validated
until the corrected command completes.

Use the same staged update, test command, and K2 native diagnostic
command shown above; no worker refresh, physical printer operation or
production adapter modification.


## Verified prime-volume override, machine-owned purge route follow-up (21 Nov 2026)

User Debian staging validated updated diagnostics at commit `51a03db9`:
**62/62 tests passed**, **11 offline Creality native slices completed**, pinned
worker image unchanged. `prime_volume_marked` set `prime_volume=180`
in emitted G-code and changed executable motion and tower deposition:
tower positive-E **1090.971 -> 3953.060 mm**, footprint
**22.898×22.898 -> 38.898×38.398 mm**, motion/M-command hashes changed.
The exact same project at 180 mm³ **without** a process override marker
emitted the restored **45 mm³** and unchanged tower. The override-marker
contract is therefore empirically proven for native `prime_volume`.

The earlier process-marked `purge_in_prime_tower=1` control still emitted
`0`, with no G-code motion or tower change. Official Creality v7.3.1
`Preset.cpp`, `PrimeTowerOptions.hpp`, machine profile presets, and
parameter metadata place this option in the **printer/machine** preset,
NOT the process preset. `PresetBundle.cpp::load_config_file_config`
uses `different_settings_to_system[num_filaments + 1]` for printer
overrides, versus index zero for process overrides.

New **disposable** `purge_route_tower_printer_marked` control uses the
same purge-route-enabled, multiplier-2.0 3MF and changes **only** the last
element of `different_settings_to_system` to include
`purge_in_prime_tower`. The process and four filament entries are
unchanged, native printer macros and other archive entries byte-preserved.
It directly compares to the unmarked `purge_route_tower` for emitted
`purge_in_prime_tower` value, native motion, M commands and tagged tower
E. Keep `purge_route_tower_marked` as the known negative/process control.

Expected focused test count **63**; expected **12** native offline
slices. These new results are **not yet run on Debian**. Do not refresh
the worker or permit physical printing.

```bash
cd ~/MakerVault-Staging
git pull --ff-only origin feature/self-hosted-slicer-foundation
sudo python3 scripts/install_slicer_staging.py update
sudo docker exec makervault python3 /app/backend/manage.py test \
  core.tests.test_slicer_printer_compatibility \
  core.tests.test_slicer_tower_diagnostics \
  core.tests.test_slicer_flush_adapters \
  core.tests.test_slicer_creality_project --noinput
sudo docker exec makervault python3 /app/backend/manage.py \
  diagnose_slicer_printer_profiles \
  --engine crealityprint --topology single_nozzle_changer \
  --printer-profile-id 91b19730-66f5-4b5f-bd7d-b08fbb4ee768 \
  --process-profile-id 0c90fa89-a193-48b6-ac94-a69792230163 \
  --filament-profile-id e9c1274c-d95b-4592-87e5-03a645d699aa \
  --filament-profile-id eb8473e9-f993-4c6e-8cc4-fb357e3ae782 \
  --native --test-flush
```

If the printer-marked case retains purge routing and changes emitted
motion, next compare native flush matrix vs multiplier at a fixed verified
route, with bounded physical purge validation kept separate. Even when
tower changes, printer-side purge, physical CFS routing and safe purge
amounts remain unverified.


## Confirmed native printer-slot purge retention; controlled flush sensitivity (21 Nov 2026)

The user's completed 12-slice offline diagnostic confirms the remaining
printer-slot override. `purge_route_tower_printer_marked`, produced from
exactly the same enabled-route 3MF as the unmarked/process-marked controls,
retains `purge_in_prime_tower=1` in G-code settings and changes *executable*
G-code. Tower positive-E moves from **1090.971 to 6011.448 mm**, tower
footprint from **22.898×22.898 to 47.398×45.398 mm** and tower-tagged
deposition moves from **3247 to 7477**. G0/G1 and M-command digests both
change. The wrong-slot `purge_route_tower_marked` is unchanged and emits
`purge_in_prime_tower=0`. This validates native machine-setting override
placement; physical purge remains unverified.

New disposable-only native matrix/multiplier sensitivity run retains
`purge_in_prime_tower=1` in the **last/printer** override slot and marks
`flush_multiplier`, `flush_volumes_matrix`, and
`flush_volumes_changed` in the **first/process** override slot. All
vendor scripts, geometry, printer and filament profiles are preserved.

Three additional native slices:
- `tower_flush_multiplier_1_0`: directional matrix unchanged,
  explicit multiplier 1.0.
- `tower_flush_multiplier_2_0`: same matrix and purge route,
  multiplier 2.0.
- `tower_flush_forward_2_0`: same multiplier 2.0 and purge route,
  only directional T0→T1 increased from fixture raw **140 to 165 mm³**.
  Fixture 140 mm³ is a conservative builder fallback, *not a proven
  manufacturer-recommended value*.

The `creality_tower_flush_sensitivity` summary reports sanitised
emitted settings and source-tagged tower movement/E plus a direct
comparison against the multiplier-2.0 control. Interpret changes in G-code
motion or tower deposition as evidence of native response, not numerical
proof of real flush volume or firmware-side purge. A new regression test
checks both override slots and byte-preserved non-project ZIP entries.

Expected focused Django tests: **64** (previous 63 + one).
Expected native Creality offline slices: **15** (previous 12 + three).
**The new controls have not yet been run on Debian.** Keep the
worker pinned and do not submit diagnostic G-code to any printer.

```bash
cd ~/MakerVault-Staging
git pull --ff-only origin feature/self-hosted-slicer-foundation
sudo python3 scripts/install_slicer_staging.py update
sudo docker exec makervault python3 /app/backend/manage.py test \
  core.tests.test_slicer_printer_compatibility \
  core.tests.test_slicer_tower_diagnostics \
  core.tests.test_slicer_flush_adapters \
  core.tests.test_slicer_creality_project --noinput
sudo docker exec makervault python3 /app/backend/manage.py \
  diagnose_slicer_printer_profiles \
  --engine crealityprint --topology single_nozzle_changer \
  --printer-profile-id 91b19730-66f5-4b5f-bd7d-b08fbb4ee768 \
  --process-profile-id 0c90fa89-a193-48b6-ac94-a69792230163 \
  --filament-profile-id e9c1274c-d95b-4592-87e5-03a645d699aa \
  --filament-profile-id eb8473e9-f993-4c6e-8cc4-fb357e3ae782 \
  --native --test-flush
```


## Confirmed multiplier/directional native sensitivity and bounded project-builder fix (21 Nov 2026)

User's `Pasted text(20261121-002608).txt` is a **tail-only**
diagnostic response; it includes the full
`creality_tower_flush_sensitivity` object but does not show the Django
test-run header. It confirms:

| Native comparison | T0→T1 fixture | Multiplier | Tagged tower positive-E | Tower XY |
| --- | --- | --- | --- | --- |
| `tower_flush_multiplier_1_0` | 140 mm³ | 1.0 | 3109.561 mm | 35.398 × 34.398 mm |
| `tower_flush_multiplier_2_0` | 140 mm³ | 2.0 | 6011.448 mm | 47.398 × 45.398 mm |
| `tower_flush_forward_2_0` | 165 mm³ | 2.0 | 6663.034 mm | 50.398 × 48.898 mm |

Both A/B comparisons changed G0/G1 and M-command SHA, tower
footprint and tower tagged E, with `purge_in_prime_tower=enabled`
in the emitted G-code. Therefore Creality's native slicing does respond
to both the multiplier and directional matrix when the process
override list and printer purge override are correctly preserved.

**These figures are lengths of filament extruded into *tagged tower
moves*, NOT independently measured mm³ of purged material.** Source
matrix 140 mm³ is a diagnostic fallback, not a Creality K2 preset
default. The generated G-code still does not validate physical
purging at printer-side tool changes.

The production project builder formerly marked only support process
options in `different_settings_to_system[0]`. A bounded fix now
writes native process override markers for **explicitly requested**
`flush_multiplier`, `flush_volumes_matrix`,
`flush_volumes_changed`, `enable_prime_tower` and for the
selected process profile's explicit `prime_volume`, when applicable.
Machine `purge_in_prime_tower` is marked in the last/printer
override slot **only when provided by the selected machine profile**;
its value is deliberately not changed. The fix does not force tower
purging, invent flush-volume defaults, rewrite manufacturer scripts
or change the isolated native worker. It does not promise the CFS
firmware will purge at the specified physical location.

Regression coverage tests the bounded allowlist, stable process/
printer/filament slots, repeat safety, no invented fields, and actual
generated Creality 3MF output. **These production-path edits are
committed on a draft PR branch, not yet run on Debian.**

Next: app-only staging rebuild and the four focused test suites
(previously 64; now **66** tests expected with two added methods;
existing project test also has stronger assertions). Run a normal
non-printing native staging slice with explicit flush requests and
compare hashes/settings; do not dispatch to the K2. The existing
diagnostic uses its own disposable marker controls and therefore
does NOT by itself validate the new production 3MF marker path.
Keep PR in draft until end-to-end production 3MF slicing evidence and
physical CFS verification are collected.


### Separating corrected project generation from historical negative controls

The regular `build_creality_project_candidate(...)` now defaults to
`preserve_native_flush_overrides=True`. Diagnostic fixtures which
deliberately test the consequences of *omitted* process markers explicitly
use `preserve_native_flush_overrides=False`; their existing positive/negative
A/B comparisons are therefore unchanged. No UI caller opts out. The
parameter is strictly boolean and is regression-tested along with the
real builder's explicit marker output. Production-path native slicing is
still **not yet server-verified**. App-only staging update remains required;
do not refresh or rebuild the pinned native worker.

To avoid accidentally treating a successful repetition of the disposable
controls as production verification, first run the focused Django suites
(**66 expected**) after updating, and separately perform an offline
MakerVault slice generated through the regular (default-preserving)
project-builder path with explicit flushing. Do not send a print job.


## Focused ordinary production-builder offline verification (21 Nov 2026)

Latest user's `Pasted text(20261121-003437).txt` confirms app-only
Debian staging `df41dc7b..1aee2a32`, the verified pinned worker
`sha256:7a3120b320dc5a0e26147c32bbe620bf094574b26d8f06247589ead2feba24b8`
unchanged and healthy, and **66/66 focused Django tests PASS**.
This validates regression coverage but is not end-to-end proof of native
production 3MF slicing.

To close that distinction, new `--test-production-flush` command option
runs exactly **three offline native slices** using
`build_creality_project_candidate` with its normal
`preserve_native_flush_overrides=True` default, rather than disposable
post-build marker edits. Selects the same two approved filament profile
identities and two object geometry placements; retains manufacturer
printer/filament scripts.

The three A/B scenarios: multiplier 1.0; multiplier 2.0; multiplier 2.0
with only T0→T1 increased by 25 mm³ from the *project's actual source
matrix entry*. It requires `--engine crealityprint --native`, refuses
`--test-flush` and unsupported topologies, validates process marker
presence and requested matrix values *before slicing*, and rechecks the
pinned engine manifest afterwards. It does not submit any printer job.
It reports the selected machine profile's original
`purge_in_prime_tower` and whether the regular builder marked that
printer override, but **does not force it enabled**. If the original
native printer profile disables it, tower motion sensitivity is not
guaranteed; this is expected and should not be falsely called a failure.
`normal_multiplier_2_0` is the common comparison parent; reports
safe emitted settings, tagged-tower geometry/positive E, executable
motion/M-command hashes and differences.

Run after staging app-only update and focused tests
(**67 expected, up from verified 66**):

```bash
cd ~/MakerVault-Staging
git pull --ff-only origin feature/self-hosted-slicer-foundation
sudo python3 scripts/install_slicer_staging.py update
sudo docker exec makervault python3 /app/backend/manage.py test \
  core.tests.test_slicer_printer_compatibility \
  core.tests.test_slicer_tower_diagnostics \
  core.tests.test_slicer_flush_adapters \
  core.tests.test_slicer_creality_project --noinput
sudo docker exec makervault python3 /app/backend/manage.py \
  diagnose_slicer_printer_profiles \
  --engine crealityprint --topology single_nozzle_changer \
  --printer-profile-id 91b19730-66f5-4b5f-bd7d-b08fbb4ee768 \
  --process-profile-id 0c90fa89-a193-48b6-ac94-a69792230163 \
  --filament-profile-id e9c1274c-d95b-4592-87e5-03a645d699aa \
  --filament-profile-id eb8473e9-f993-4c6e-8cc4-fb357e3ae782 \
  --native --test-production-flush
```

This flag/test is **not yet verified on Debian**. Keep PR #171
draft; physical CFS purge, printer firmware behaviour and final
production dispatch safety remain unverified.


## Real production A/B confirms native K2 route is off; audit manufacturer macro next (21 Nov 2026)

User log `Pasted text(20261121-003805).txt` confirms app-only staging
updated to `38720482`, isolated pinned worker image unchanged/healthy,
**67/67 focused Django tests PASS**, and all **three real production
3MF builder native offline slices succeeded**. Every normal builder
case preserves selected machine profile `purge_in_prime_tower=0`
(including printer override declaration), returns 24 T0 and 24 T1
selects, and produces identical executable G0/G1 and M-command hashes
and identical marked tower deposition: **1090.971 mm positive-E**,
**22.898×22.898 mm XY**. A multiplier of 1.0 vs 2.0, and raw fixture
T0→T1 140→165 mm³ with multiplier 2.0, still change G-code comment
metadata and project setting keys, **not motion or machine commands**.
This is expected with source printer profile's tower purge disabled,
NOT proof of physical flushing and NOT validation of user-changeable
purge volume at the K2's external flush location.

Review of exact upstream `CrealityOfficial/CrealityPrint` v7.3.1
`resources/profiles/Creality/machine/Creality K2 0.4 nozzle.json`
confirms `purge_in_prime_tower=0` and an unmodified
`change_filament_gcode` containing `flush_length_1` through
`flush_length_5` and Creality `M8200` commands. Critically, the K2
script begins with the `{if multicolor_method}` condition, so a native
print may have tool selects without executing the manufacturer's full
change/purge macro. The K2 leaf machine preset does not itself define
`multicolor_method` (it may be inherited/resolved elsewhere; do NOT
infer its runtime value from omission). Upstream `PresetBundle.cpp`
classifies `multicolor_method` as a machine capability, not a project
option, so do not inject it into a 3MF to force the script.

New read-only diagnostic addition to the existing 3-slice
`--test-production-flush`: emitted `multicolor_method` comment
(if present and a valid 0/1 flag), safe source/project flag presence,
and **counts only** of exact G-code `; FLUSH_START`,
`; FLUSH_END`, `M8200`, `SET_VELOCITY_LIMIT`, and
`T<number>` markers. It does not return any proprietary vendor
scripts, alter macros, change native worker, select a different printer
or enable CFS. A unit test validates counts and excludes comments
which merely mention machine commands.

Expected focused Django tests: **68** (67 verified + 1 newly added).
For minimal repeat, after app-only update run the four focused suites
and `--native --test-production-flush` again (3 native slices).
Inspect `production_builder_offline_controls` emitted
`multicolor_method` and `toolchange_macro_audit`. If no K2 change
macro markers are emitted, diagnose missing/disabled native machine
capability or CLI macro invocation; **do not treat identical G-code
hashes as correct printer-side flushing**. Still no physical printer
safety/flush validation and PR remains draft.


## K2 native filament-change macro not emitted; opt-in offline multicolor gate probe (21 Nov 2026)

User uploaded `Pasted text(20261121-004307).txt`, which confirms
staging app-only `38720482..31a88439` succeeded with worker image
`sha256:7a3120b320dc5a0e26147c32bbe620bf094574b26d8f06247589ead2feba24b8`
untouched and healthy. The user repeated the *three* ordinary
production 3MF offline slices, all completed. The shared source
machine and project have `purge_in_prime_tower=0`, source
`multicolor_method=not_explicit`, and project
`multicolor_method=absent`. The emitted G-code comment audit reports
`multicolor_method=disabled` in all three cases. There are 48 native
T selections, **ZERO** exact `FLUSH_START`/`FLUSH_END` markers and
**ZERO** `M8200` commands. Tower deposition and actual G0/G1 and
M-command hashes remain identical across multiplier 1→2 and
directional T0→T1 140→165mm³. Source K2 0.4 machine's native
`change_filament_gcode` starts with `{if multicolor_method}`
and includes `flush_length_1..5` and M8200 purge operations.
Thus the expected K2-script purge path is absent from these
G-code outputs; tool select count alone is not reliable proof.

No *new* Django test run is shown in this attachment. Previous
verified 67/67 remains the latest displayed complete run.

Official `CrealityOfficial/CrealityPrint` 7.3.1
`PresetBundle.cpp` explicitly documents `multicolor_method` as a
**machine capability**, not a normal project option. Original selected
K2 machine profile lacks an explicit value, and its source
`purge_in_prime_tower=0` must be respected. Do not silently
set `multicolor_method=1` or `purge_in_prime_tower=1` in
production, modify vendor toolchange macros or submit G-code.

New **explicit opt-in** `--probe-multicolor-gate` may be used only
with `--engine crealityprint --native --test-production-flush`.
It adds **one extra disposable native offline slice**, based on the
same ordinary K2 project at multiplier 2.0; its test-only 3MF
contains `multicolor_method=1` in the last/printer override slot,
with the vendor scripts, geometry, other fields and 3MF members
byte-preserved. This is a **positive control**, NOT a fix, not a
verified native printer capability and **never safe to print**. The
report adds `experimental_multicolor_enabled` alongside three
standard cases and checks emitted setting and count of genuine
vendor purge markers/M8200 commands vs standard multiplier 2.0.
It does not save or alter any imported printer profile or native
worker code.

The new regression tests ensure field isolation, no duplications,
byte-identical non-project ZIP members and CLI opt-in.
Expected 69 focused tests (latest verified 67 + two new tests
since previous verified run: prior macro audit + this positive control)
and **four offline native slices** on opt-in. These are **not yet run
on the user's Debian staging**.

```bash
cd ~/MakerVault-Staging
git pull --ff-only origin feature/self-hosted-slicer-foundation
sudo python3 scripts/install_slicer_staging.py update
sudo docker exec makervault python3 /app/backend/manage.py test \
  core.tests.test_slicer_printer_compatibility \
  core.tests.test_slicer_tower_diagnostics \
  core.tests.test_slicer_flush_adapters \
  core.tests.test_slicer_creality_project --noinput
sudo docker exec makervault python3 /app/backend/manage.py \
  diagnose_slicer_printer_profiles \
  --engine crealityprint --topology single_nozzle_changer \
  --printer-profile-id 91b19730-66f5-4b5f-bd7d-b08fbb4ee768 \
  --process-profile-id 0c90fa89-a193-48b6-ac94-a69792230163 \
  --filament-profile-id e9c1274c-d95b-4592-87e5-03a645d699aa \
  --filament-profile-id eb8473e9-f993-4c6e-8cc4-fb357e3ae782 \
  --native --test-production-flush --probe-multicolor-gate
```

A positive probe still does NOT prove physical K2 CFS flush routing,
and a negative probe warrants investigating the 7.3.1 CLI
printer-preset effective value, not manufacturing custom purge code.
Keep PR draft and print dispatch blocked pending source and
physical validation.


## Multicolor gate positive result; isolated external K2 flush sensitivity (21 Nov 2026)

User log `Pasted text(20261121-005129).txt` confirms staging
`31a88439..62fc1381` app-only update succeeded with the pinned
worker unchanged/healthy, **69/69 focused Django tests PASS**, and
all four offline native 3MF slices complete. At multiplier 2.0:
original K2 native project (`multicolor_method` absent, emitted
disabled) produces **zero** `FLUSH_START`/`FLUSH_END` and
**zero** `M8200` commands, 48 T selects and tower positive E
1090.971mm. The **disposable diagnostic-only** project carrying
`multicolor_method=1` in printer override slot produces
**50 FLUSH_START + 50 FLUSH_END**, **287 M8200 commands**,
6020 rather than 5470 G1 extrusion moves and different executable
motion and machine command digests; emitted `multicolor_method` is
enabled. Both retain `purge_in_prime_tower=0`, and tagged prime
tower output is unchanged. This establishes that the K2's
manufacturer change-filament script is gated by multicolor_method;
it does not establish printer/firmware safety, valid purge amounts,
or the source of the supported machine capability.

An optional follow-on, still within **the same existing explicitly
opted-in `--probe-multicolor-gate`**, adds two disposable-only 3MF
slices in addition to the existing 4: `experimental_multicolor_multiplier_1_0`
compares 1.0 to 2.0 with the machine capability and source matrix
held constant; `experimental_multicolor_forward_2_0` increases
T0→T1 by 25 mm³ at multiplier 2.0, keeping the capability
constant. The source machine profile, vendor change_filament_gcode,
geometry, worker and actual printer remain unmodified. It compares
**executable motion/M-command SHA** and scrubbed K2 macro counts,
not just comments or tagged prime-tower E. These controls are
**not yet run on Debian** and must NEVER be printed.

Run the focused suite (69 expected, unchanged) and existing
`--native --test-production-flush --probe-multicolor-gate`
with the approved K2 profile IDs. **6 offline slices expected**:
3 original-project controls plus 3 machine-capability-enabled
disposable controls. Verify that multiplier/matrix changes affect
actual external K2 flushing script generation. Even a positive
result is not permission to enable this unverified capability in
normal profiles or submit any print.

Retain PR #171 as draft; do not merge until machine-capability
provenance is understood and physical printer safety is checked.


## Confirmed K2 external purge-code sensitivity with gated native positive control (21 Nov 2026)

User's `Pasted text(20261121-005517).txt` shows successful
app-only staging update `62fc1381..4da21c60`, unchanged healthy
pinned worker, and all **six offline** native Creality 3MF slices
completed; no new Django test command shown in this attachment.
Latest confirmed focused tests remain **69/69** from the preceding
uploaded log.

For ordinary real K2 project 3MF, `multicolor_method` remains
disabled, `purge_in_prime_tower=0`, K2 native purge macro markers
remain absent, and changing multiplier 1↔2 or T0→T1 raw directional
140↔165mm³ produces identical executable motion and M-command
digests. The same inputs through the ordinary MakerVault builder,
with the **test-only** machine capability `multicolor_method=1`
applied to otherwise identical disposable 3MF, prove BOTH controls
alter executable G-code:

| Gated offline control | Multiplier | T0→T1 | FLUSH_START/END | M8200 | G1 extrusion moves | Actual motion and M SHA |
| --- | --- | --- | --- | --- | --- | --- |
| `experimental_multicolor_multiplier_1_0` | 1.0 | 140mm³ fallback | 50/50 | 287 | 6020 | Different vs gated 2.0 |
| `experimental_multicolor_enabled` | 2.0 | 140mm³ fallback | 50/50 | 287 | 6020 | Reference |
| `experimental_multicolor_forward_2_0` | 2.0 | 165mm³ fallback | **74/74** | 287 | **6284** | Different vs gated 2.0 |

The identical flush-start/M8200 counts for the multiplier comparison
do **NOT** invalidate the result: its G0/G1 motion and machine-command
hashes differ, consistent with changed extrusion command values
without changing the number of native operations. The directional
matrix test also creates 24 additional flush start/end sections and
264 extrusion moves. Tagged tower positive E stays 1090.971mm,
XY22.898×22.898mm, as expected with K2's original
`purge_in_prime_tower=0`. All G-code values are offline-only and
**not physically calibrated purge volumes**; default 140mm³ is a
builder diagnostic fallback, not an official K2 matrix default.
No printer sent any commands.

Remaining engineering decision is **where a legitimate
`multicolor_method=1` machine capability originates** in
Creality's official preset-selection flow. Upstream
`PresetBundle.cpp` excludes this capability from project options
and expects it from a printer profile. The selected resolved
imported machine has no explicit capability and generates
`multicolor_method=0`. Do not generalise the synthetic 3MF
positive-control override into all production jobs, change native
vendor macros, or declare physical validation complete. PR #171
remains draft; K2 printer dispatch of unverified generated
multi-colour jobs must remain blocked until a supported machine
capability source, approved purge quantity and physical test path
are established.


## Production-path machine capability preservation (21 Nov 2026)

Upstream Creality Print 7.3.1 `src/libslic3r/PresetBundle.cpp`
explicitly treats `multicolor_method` as **machine-preset** state,
not an ordinary project option. Its GUI
`src/slic3r/GUI/GUI_Factories.cpp` updates the **edited printer
preset's** `multicolor_method` in connection with
`flush_into_skeleton`; that UI path does NOT establish that every
K2/CFS printer should be forcibly enabled, nor a safe physical
purge volume. The stock K2 0.4-nozzle preset does not declare
`multicolor_method`, even though its native unchanged
`change_filament_gcode` is gated on that setting.

The ordinary MakerVault Creality 3MF builder now:
- propagates an explicitly present, type-validated
  `multicolor_method=0/1` from the **selected resolved machine preset**
  into the native printer settings override slot
  `different_settings_to_system[-1]`, without duplicates;
- preserves the selected K2 printer's original
  `purge_in_prime_tower=0`, physical/nozzle mapping,
  material assignments, and **byte-identical native vendor
  change-filament script**;
- does NOT infer `multicolor_method=1` from printer name, CFS
  topology, painted model, flush multiplier or diagnostic examples;
- optionally supports a **strict** builder mode
  `require_verified_multicolor_purge=True` for a future
  printer-ready route. It rejects missing/disabled machine capability
  and rejects a machine profile lacking an expected native
  `{if multicolor_method}`, `flush_length_1` and `M8200`
  macro structure. This is only a source-structure check, **not
  physical approval**. The opt-in strict mode must be used by any
  future dispatch path before printing; current diagnostic candidates
  retain their original behaviour, so the negative controls
  remain valid.
- keeps synthetic `--probe-multicolor-gate` a separate
  explicitly opted-in, **offline-only**, never-print test.

Additional Django unit tests cover missing/invalid/disabled
capabilities, exact native printer-slot marking, idempotence,
fail-closed strict source checks, and real 3MF builder preservation
of the original script and printer purge route.

**Current selected K2 profile still lacks an explicit capability**.
No unverified capability is written into the user's imported profile
or database, so we have deliberately not enabled live K2
multicolour print submission or declared physical compatibility.
To advance: obtain/derive a **manufacturer-configured, explicit
printer preset** via a supported Creality Print UI/profile workflow,
verify it reflects the intended K2/CFS operating mode, import
it as a new profile (preserving the stock reference), and then
run an end-to-end **offline** slice with strict capability validation
and native K2 purge-marker/motion audit. Finally perform a
separately authorised controlled printer test.

Public PR #171 remains **draft**. These changes touch app-side
native 3MF builder, tests and documentation only; the pinned
worker, native binary, firmware and printer remain unchanged.


## Inspect a real exported Creality Print 7.3.1 K2 printer preset (21 Nov 2026)

Creality Print 7 supports **File → Export → Export Presets**;
the user should select the actual saved **K2 0.4 mm printer preset**
on their desktop, export it without editing the stock machine
settings, and supply it for inspection/import as a separate
candidate. **Do not turn on Flush into skeleton just to activate
`multicolor_method`**: upstream GUI
`sync_multicolor_method_to_flush_into_skeleton()` mutates the
printer preset based on that choice and this may also affect
geometry/flush deposition options. Exported formats may vary;
inspect the export before interpreting as a native JSON printer
profile or importing it into MakerVault. Do not upload printer
credentials, tokens or network secrets.

New **`--audit-machine-capability`** mode in existing
`diagnose_slicer_printer_profiles` is completely read-only and
requires `--engine crealityprint` with explicit existing selected
K2 printer, process and two filament profile IDs and topology.
It rejects all native slicing flags. It reports the effective
selected printer `multicolor_method`, original
`purge_in_prime_tower`, whether the unchanged vendor
`change_filament_gcode` has the known K2 macro structure and
a hash/nearest-ancestor field provenance using the existing
`audit_creality_profile_origins`. It never returns macro text,
calls the slicer, writes a profile, modifies printer firmware,
or communicates with a physical printer.
`printer_ready_candidate` means *structurally eligible for
further offline tests* only, while `printer_ready` stays
**false** categorically until printer safety validation.

```bash
cd ~/MakerVault-Staging
git pull --ff-only origin feature/self-hosted-slicer-foundation
sudo python3 scripts/install_slicer_staging.py update
sudo docker exec makervault python3 /app/backend/manage.py test \
  core.tests.test_slicer_printer_compatibility \
  core.tests.test_slicer_tower_diagnostics \
  core.tests.test_slicer_flush_adapters \
  core.tests.test_slicer_creality_project --noinput
sudo docker exec makervault python3 /app/backend/manage.py \
  diagnose_slicer_printer_profiles \
  --engine crealityprint --topology single_nozzle_changer \
  --printer-profile-id 91b19730-66f5-4b5f-bd7d-b08fbb4ee768 \
  --process-profile-id 0c90fa89-a193-48b6-ac94-a69792230163 \
  --filament-profile-id e9c1274c-d95b-4592-87e5-03a645d699aa \
  --filament-profile-id eb8473e9-f993-4c6e-8cc4-fb357e3ae782 \
  --audit-machine-capability
```

Expected **72** focused Django test methods: prior verified 71
plus one new CLI flag regression. New command has **not yet been
run** on Debian. Existing original K2 preset should report
`source_multicolor_method=not_explicit`,
`printer_ready_candidate=false`. This is the desired fail-closed
baseline; don't fix it by synthesising a value.

After a genuine manufacturer-configured machine preset is supplied,
inspect its provenance, confirm exact version/name/conditional
native script/purge route, then import separately and run the
ordinary 3MF native **offline** path with
`require_verified_multicolor_purge=True` before considering
printer dispatch. Keep PR #171 draft, pinned worker untouched.


## Root cause established: Creality official profile catalogue pinned to wrong release (21 Nov 2026)

User asked whether MakerVault profiles came directly from Creality Print.
**YES**: MakerVault's official Creality catalogue uses the genuine
`CrealityOfficial/CrealityPrint` GitHub repository. But inspection
of `backend/core/slicer_creality_official_profiles.py` found it
**pinned to the upstream `v7.3.0` tag**, and
`slicer_api.py` intentionally allowed those v7.3.0 source bytes
to be imported under the `7.3.1` runtime/version label. The
actual isolated Creality engine is v7.3.1; **this version mismatch
explains the missing K2 external purge macro**.

Verified exact Creality upstream file
`resources/profiles/Creality/machine/Creality K2 0.4 nozzle.json`:
- Upstream `v7.3.0`: `change_filament_gcode` **212 characters**
  with SHA-256 **`d848d81ee40a47a4483b85e232b4a583afa05fe9663e4272ebfd10b19f16a54b`**.
- The exact same **SHA-256** was reported by Debian
  `--audit-machine-capability` for selected old K2 profile
  `91b19730-66f5-4b5f-bd7d-b08fbb4ee768`, defined on that
  selected profile at parent depth zero. **This is definitively
  the old manufacturer's v7.3.0 script, not a truncated script
  or a faulty ZIP conversion.**
- Upstream `v7.3.1`: manufacturer K2
  `change_filament_gcode` **7183 characters**, including the
  native `{if multicolor_method}` gate, `M8200`,
  `flush_length_1..5`, `FLUSH_START` and `FLUSH_END`
  sections; corresponds in length and shape to user desktop
  Creality Print v7.3.1 exported K2 configuration.
- Upstream official `Creality.json` manifests have K2 entry in
  both releases (v7.3.0: 94 machine /1497 filament/293 process;
  v7.3.1: 101 machine/1579 filament/308 process).
- Desktop exported **v7.3.1** machine still has
  `multicolor_method=0`. Do not infer disabled gate should be
  forced on automatically. Separate supported capability
  configuration and offline validation is still necessary.

**Fix on draft PR #171**:
- Pin Creality official catalogue `ENGINE_VERSION=7.3.1`,
  `REF=v7.3.1`; all official machine, process, filament and
  parent-chain downloads now use matching Creality engine release.
- Remove the old special case in the official-profile import API
  that let source v7.3.0 content masquerade as v7.3.1. Now
  explicit old release selections are rejected.
- New official imports are stored at distinct
  `source_scope=CrealityOfficial/CrealityPrint@v7.3.1/Creality`.
  Existing old `@v7.3.0` records and imported profile bytes
  **are preserved unchanged**; no automatic DB migrations,
  profile replacement, or grandfathered execution approval.
- Tests have been updated to assert v7.3.1 source and engine,
  reject explicit 7.3.0 selection before network/storage access,
  and recognise old vs new catalogue provenance via the optional
  read-only `--audit-machine-capability` command.
  `official_source_release` distinguishes source tag from
  stored engine version in the audit output. No printer calls.

After installing the **app-only** update in staging (do not
`refresh-worker`), run focused regression suites:
`core.tests.test_slicer_creality_official_profiles`,
`core.tests.test_slicer_official_api`,
`core.tests.test_slicer_printer_compatibility`,
`core.tests.test_slicer_creality_project`.
Then use the built-in MakerVault official profile search to
**reimport K2 machine, selected process and filaments from
v7.3.1 as separate candidate profiles** with their native
inheritance chains. Confirm the new machine script length/shape
using read-only audit; compare the generated normal 3MF offline
before any print approval. **Do not** change stock K2's native
`multicolor_method=0` automatically and do not merge PR #171
or submit experimental print G-code.


### Safety/UX follow-up: visible legacy profile warning

Official v7.3.1 source is now also the default browser source
for the **actual** Creality Print v7.3.1 installed engine.
The saved profiles view warns specifically when a previously
imported `CrealityOfficial/CrealityPrint@v7.3.0/...` record has
been labelled `engine_version=7.3.1`; it does not remove,
modify, hide or auto-replace that record. The official search
dialog now treats any future Creality catalogue/engine release
mismatch as an error instead of promising that mismatched
presets can simply be imported. Source identities and tagged
release are returned from the API.

Frontend source assertions added to
`frontend/tests/slicerNovemberFeedback.test.js`.

**On staging:** the previous K2 profile's own script hash
`d848d81e...` matches Creality's original `v7.3.0`
`change_filament_gcode` precisely. No ambiguity remains
about that script's release, but the source_scope of the selected
profile itself should be verified with the new read-only
`official_source_release` diagnostic field.

No Creality code is changed, no printer scripts rewritten,
and no physical tests approved. The new v7.3.1 source is not
a guarantee that `multicolor_method` is enabled:
the user's original desktop export itself says `0`.


## Shared exact-version official catalogue resolver (21 Nov 2026)

Following the Creality v7.3.0/v7.3.1 purge-macro mismatch,
MakerVault's official source selection now uses
`backend/core/slicer_official_release_resolver.py` for all
**five** supported native catalogue integrations. The browser,
native inheritance-chain importer and POST import route must
all match the selected `engine/version` to a **reviewed upstream
tag**, not the latest/default release or an unrelated slicer's
profiles. Both GET and POST reject unsupported and explicitly
blank version selections *before network or database mutations*.
No URL is assembled from an unapproved version.

| Engine | Reviewed exact version(s) | Upstream ref(s) | Catalogue |
| --- | --- | --- | --- |
| OrcaSlicer | 2.4.2, 2.5.0 | v2.4.2, v2.5.0 | OrcaSlicer/OrcaSlicer |
| Creality Print | 7.3.1 | v7.3.1 | CrealityOfficial/CrealityPrint |
| Bambu Studio | 02.09.01.70 | v02.09.01.70 | bambulab/BambuStudio |
| PrusaSlicer | 2.9.6 | version_2.9.6 | prusa3d/PrusaSlicer |
| Snapmaker Orca | 2.4.1 | v2.4.1 | Snapmaker/OrcaSlicer |

**Only approved, available engine releases are supported.**
The resolver will not assume every engine release has a matching
profile tree or compatible format. Adding a new release requires
reviewing that engine's upstream tag and manifest layout and
extending the tested mapping. Bambu and Prusa integrations
currently import only manufacturer model-level records, not
native printer/process/filament slices.

The official-profile UI displays the exact selected slicer version
as read-only catalogue release, including for Orca; it no longer
silently substitutes Orca 2.5.0 for an unsupported engine version.
The UI refuses to search/import if the slicer release changed
after opening the modal. API response includes approved versions
and source ref, and rejects an unsupported release rather than
returning results from another engine/version.

Orca's two *explicitly approved* releases still work: their
manifest and dependency fetcher are version-parameterised.
Creality's K2 v7.3.1 full manufacturer filament-change macro is
used for **newly imported** records from that release. All
imported child/parent profiles share owner, engine, exact version
and source scope, and existing imported 7.3.0 records and saved
jobs are NOT migrated, overwritten or given new approval.
The immutable isolated worker and printer/firmware aren't touched.

Regression coverage: `test_slicer_official_release_resolver`
(new), `test_slicer_official_api` (all-engine GET/POST rejection
and accurate source-ref reporting),
`test_slicer_official_chain` (reject cross-release parent
chain before downloads), and
`frontend/tests/slicerNovemberFeedback.test.js` (matching UI
selection/no fallback). Source code committed to draft PR #171.
**Not yet validated on Debian**: run these tests after app-only
update; no isolated slicer-worker refresh.


## Slicer history housekeeping and thumbnails (21 Nov 2026)

Draft PR #171 adds controls at the **top of Saved slicing drafts**:

- Filter: All / unsliced drafts / completed slices / other active+inactive.
- Select entries (checkboxes on loaded rows), Select all filtered,
  Clear selection and Delete selected, with a confirmation that
  names the number of entries.
- Remove all drafts and Remove all slices explicitly include older
  entries beyond the current visible page; the backend uses a
  bounded, owner-only transactional delete. Queued/running jobs
  cannot be deleted. Failed/cancelled/stale jobs can be selected.
- Remove all unsaved G-code is a **separate**, explicitly confirmed
  operation: it removes only owner-private generated
  `FileAsset(category="other")` with
  `generated_by=makervault-slicer`, `extension=.gcode` and
  a matching `slice_job_id`, and never `FileAsset(category="gcode")`
  promoted into the G-code library, nor STL/3MF source files.
  Completed jobs whose unsaved output is removed remain in
  `stale` history without a preview. Orphaned private G-code
  remaining after deleting completed jobs can also be cleared.
  Protected or conflicting files are skipped and not detached.
- Ordinary single or bulk draft/job deletion **preserves** generated
  private G-code and existing library files; users explicitly
  choose the separate unsaved-output cleanup if desired.
- Completed sliced G-code no longer keeps source `SlicerProfile`
  records artificially locked. On explicit profile deletion,
  completed SliceJob foreign keys to that profile are detached,
  preserving the existing name/version snapshot, output file and
  history. Unfinished, active or retryable jobs and native parent
  dependencies still block profile deletion; no printer dispatch
  or profile automation changes.

Each saved completed slice now shows the **existing embedded PNG
thumbnail from its G-code**, served by a new private, owner-checked,
bounded (2 MiB header) read-only thumbnail endpoint. No image is
generated at view time and no new printer G-code is created.
Unavailable images use a compact visual placeholder; non-completed
drafts show a placeholder. Existing 96x96/300x300 G-code header
blocks are parsed and base64-decoded only within strict size limits.

Regression additions:
`core.tests.test_slicer_job_bulk`,
two completed-versus-draft profile-deletion cases in
`test_slicer_official_api`, and
`frontend/tests/slicerNovemberFeedback.test.js` source assertions.

**The new changes have not yet been run or deployed on Debian.**
Use only `sudo python3 scripts/install_slicer_staging.py update`
on the staging app, not `refresh-worker`. No printer settings,
firmware, manufacturer's slicer scripts or generated physical
print are changed. PR #171 remains a draft.
