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
