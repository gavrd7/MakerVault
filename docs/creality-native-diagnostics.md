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

The wrapper intentionally returns **exit 2** if none of the six CLI scenarios
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

1. **baseline** — exact latest failed MakerVault candidate.
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
yield six failures. If it does, compare a genuine native 3MF using
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
