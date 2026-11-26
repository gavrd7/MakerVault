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
3. **Transport** must not materialise unbounded base64 JSON payloads. Large
   jobs require bounded streaming or compressed transport with authenticated
   message integrity, content-length accounting and backpressure.
4. **Worker admission** independently measures its own cgroup RAM and scratch
   space and revalidates the model. The client-side allowance is not trusted.
5. **Native invocation** derives geometry/triangle settings from validated
   inputs where the installed engine supports them; unsupported flags must not
   be invented. Actual engine memory/CPU/concurrency remain isolated.
6. **Output** is streamed to private storage under a measured disk budget,
   rather than relying on a universal 64-MiB G-code response ceiling.
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

## Implementation and limitations

- `backend/core/slicer_resource_budget.py`: generic source and job headroom
  inspection (legacy source ceilings still remain where callers pass them).
- `slicer_worker/resource_budget.py`: generic worker RAM + scratch filesystem
  headroom and operation-level admission.
- `slicer_worker/streamed_orca_validation.py`: first consumer of shared
  worker measurement; this is **not** a generic worker mesh validator.
- `backend/core/slicer_streamed_plate_3mf.py`: currently the *plain,
  single-material Orca* streamed-compound implementation. It is a useful
  proof of transport and XML preparation, not implementation for every engine.

**Still outstanding before the overall requirement is fulfilled:** migrate
per-source mesh admission, 3MF and binary STL native format paths, the old
base64 request/response caps and stored G-code output to measured resource
admission. Add representative real-binary fixtures for Creality, Orca, Bambu
and Prusa. The workflow should not be marked complete or merge-ready solely
on the new Orca 20-model test.
