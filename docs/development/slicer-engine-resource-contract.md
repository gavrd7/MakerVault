# Engine-neutral slicing resource contract

This work is **not complete** merely because Orca accepts a full plate. The
capacity system must be shared by Creality Print, OrcaSlicer, Bambu Studio,
PrusaSlicer, and future engines (including Snapmaker Orca).

## Separation of responsibility

1. **Model ownership and format validation** are unconditional: each STL/3MF
   must be authentic, well-formed, finite and contain only explicitly supported
   metadata. A machine with more RAM does not waive structural validation.
2. **Preparation admission** compares a *measured* expansion estimate and
   scratch-disk demand against live host/cgroup resources, reserving resources
   for the application and the slicer worker. Unknown readings fail closed for
   large jobs. The policy is independent of engines; each format's decoder
   supplies an empirically tested expansion factor.
3. **Transport** is currently authenticated JSON/base64 with live resource
   admission on both peers, plus a hash-bound compressed Creality placed-STL
   contract and bounded streamed-Orca preparation. The JSON envelope remains
   in memory, and truly incremental HTTP upload/download is a separate
   optimisation; never claim the transport itself is streamed.
4. **Worker admission** independently measures its own cgroup RAM and scratch
   space and revalidates the model. The client-side allowance is not trusted.
5. **Native invocation** derives geometry/triangle settings from validated
   inputs where the installed engine supports them; unsupported flags must not
   be invented. Actual engine memory/CPU/concurrency remain isolated.
6. **Output** is validated and stored privately under shared RAM/disk
   allowances. The current worker G-code response is buffered JSON/base64,
   not a streaming download. It no longer uses a universal 64-MiB capacity
   ceiling when live resources are measurable.
7. **Regression coverage** must exercise both repeated and distinct source
   models, transformations, paints/modifiers, extreme/corrupt inputs, and a
   constrained-memory worker, for every supported engine.

## Engine adapter contract

A future registered slicer engine supplies only:

- a verified input format and any native project encoding,
- an independently audited model/metadata validator,
- per-format processing-memory and scratch-disk cost estimators,
- a verified native CLI or equivalent offline entrypoint,
- an output validator and placement/toolpath audit.

All engines consume the same capacity decision and request/response transport.
A new engine **must not introduce a fresh fixed total-model, XML or G-code byte
cap** merely to fit the existing transport. Security/resource ceilings remain
valid when justified by structural or measured machine limits.

## Implemented in draft PR #208

- `backend/core/slicer_resource_budget.py` centralises source, geometry,
  expanded XML, ZIP, G-code and configuration capacity from host/cgroup RAM.
  Small-job compatibility fallbacks still apply where telemetry is absent.
- The owner-scoped STL import/read APIs, 3MF project import/export, painting
  assets and G-code bounds/storage now use the common budget.
- Prusa's placed STL, Prusa/Creality/Bambu native 3MF project producers, and
  ordinary 3MF geometry exporters use resource-based capacity admission.
- `slicer_worker/resource_budget.py` centralises worker RAM, temporary-disk,
  model and G-code capacity. All four installed native runners use it.
- Worker STL, core 3MF and native Creality/Prusa/modifier validators now use
  resource-based geometric size limits but retain format, profile, paint and
  security checks.
- `backend/core/slicer_streamed_plate_3mf.py` and
  `slicer_worker/streamed_orca_validation.py` avoid the full expanded XML
  DOM for plain single-material Orca plates, including *different* source STLs.
- PR #206's working Creality multi-model placed STL/CLI adapter has been
  manually reconciled, with compressed SHA-bound transport and corresponding
  unit tests preserved.

## Deliberate limits and pending acceptance

- Per-format schema allowlists, bounded numeric coordinates, prohibited scripts,
  safe project structure and physical tool counts remain mandatory. They are
  **not** arbitrary hardware-capacity limits.
- Some metadata, per-paint-region or per-plate *count* limits still exist and
  need separate feature-level review. They must not be silently relaxed as
  part of memory-size migration.
- The current HTTP model and G-code body is still JSON/base64 buffered under
  measured memory budgets. A fully streaming upload/download protocol is not
  yet implemented.
- Full-bed native compatibility remains to be proven for all supported engines:
  a 20-object real Orca slice (repeated and distinct), large placed-STL
  Creality and Prusa jobs, and Bambu native multicolour/modifier regression.
  CI and real-binary checks must be green, followed by staging acceptance.
- This branch is still based on PR #207. PR #206 was reconciled as code but
  its merge ancestry must be resolved when #207/#208 are merged into the
  updated Prusa branch. Avoid overwriting the verified Creality path.
- No production release or staging deployment is implied by this draft.
