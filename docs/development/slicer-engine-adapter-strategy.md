# MakerVault slicer engine development strategy

> Standing architecture and acceptance policy for **every** existing and future
> slicer integration (including PrusaSlicer and Snapmaker Orca).

## Principle: map, do not reimplement

MakerVault already provides the shared slicer workspace, plate/model state,
painting, object and global settings, modifiers/negative volumes, slicing
workflow, profiles, material assignment, G-code preview, Library and print
submission. **Do not rebuild any of those features independently for a new
engine.** The engine adapter maps MakerVault's canonical state to that
engine's supported native input, profiles and commands, invokes the upstream
native slicer, and returns the result through the shared backend.

- Reuse the existing frontend and canonical model/region schema.
- Translate and preserve **all** requested edits in the native project or
  explicit command-line/profile input. Reject an edit that would be discarded.
- Use the selected engine's genuine printer and filament profiles to
  determine MMU slots, logical tools, toolhead topology, bed limits and
  supported values. Do not hard-code a universal four-colour limit or
  invent machine capacity.
- Separate user-facing generic capabilities from adapter-specific
  serialization and compatibility checks. Treat native settings that
  naturally compose as composable, rather than requiring a bespoke
  allowlist for every permutation of unrelated features.
- Restrict only known upstream incompatibilities, unsupported or lossy
  mappings, malformed/untrusted inputs, device-bound constraints and
  demonstrated dangerous output. Record the precise reason in guidance
  and an automated regression.
- Perform focused translation/round-trip and representative *native*
  acceptance tests across ordinary models, paint, modifiers, negative
  volumes, varied layer heights, material tools and mixed workflows.
  Do not demand a unique full CI/G-code qualification for every
  theoretically possible combination. Finish with the standard shared
  worker, established-engine regression and deployment checks.
- A successful **offline slice** is not proof of safe printer pickup,
  docking, toolchange, firmware compatibility or print start. Keep
  hardware submission independently validated and never waive the
  strict G-code safety audit to unblock a feature.

## Implementation workflow

1. Confirm that the feature exists in the installed/pinned upstream engine
   and identify its genuine native 3MF/config/CLI representation.
2. Map existing MakerVault UI state to that representation in the
   engine-specific adapter without modifying other working engines.
3. Add a round-trip/admission regression proving every requested edit
   survives translation; use a small representative native matrix,
   including compositions with unrelated features.
4. Diagnose any actual incompatibility or unsafe output. Keep narrowly
   scoped guards only for such evidence, not for an untested combination
   merely because it has not previously been enumerated.
5. Mark release readiness when intended engine features work under the
   agreed representative tests, the standard shared CI is green, known
   blockers are resolved, and limitations requiring real printer hardware
   are documented as **hardware qualification**, not silently equated
   with missing slicer functionality.

These are the project's existing design commitments, not a proposal for a
replacement architecture. Apply them to reviews and future engines.
