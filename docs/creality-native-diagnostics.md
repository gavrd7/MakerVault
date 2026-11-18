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
