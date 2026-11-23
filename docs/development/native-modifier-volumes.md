# Native primitive modifier volumes — implementation and acceptance

Tracking issue: [#178](https://github.com/gavrd7/MakerVault/issues/178).

## Scope

OrcaSlicer/Bambu Studio use non-printing `modifier_part` child meshes in their 3MF
`Metadata/model_settings.config`; a generic independent STL plate object or
a negative-volume Boolean subtraction **does not** reproduce that behaviour.
Creality Print uses a related native-project format but must be tested against
its own pinned executable and compatible printer/process presets.

The initial cross-engine design uses **model-owned**, bounded modifiers rather
than stand-alone printable assets:

- Geometry primitives: box, cylinder, sphere, cone, disc and torus.
- Parent instance owns identity, shape, dimensions, coordinates and native
  regional overrides.
- Initial permitted native keys: `wall_loops` and `sparse_infill_density`.
- All values are validated, bounded and saved with the private slice draft.
- Saving does not mutate a printer or any native preset.
- Until native per-engine verification, slicing a modifier-bearing draft
  fails explicitly; it must never ignore the modifier or emit it as printable
  geometry.

## Native acceptance gates (required before enabling modifier slicing)

For **each** installed tested engine/version (OrcaSlicer, Creality Print,
Bambu Studio), with the actual release binary and correct native profiles:

1. Export a modifier as a properly nested component/child volume with
   `modifier_part` classification and per-part native settings, **not** as a
   separate printable plate item. Round-trip parse to confirm membership,
   transform, metadata and non-printing classification.
2. Slice an unchanged baseline solid cube with 15% infill, and the same cube
   with a 50% infill box intersecting only its upper or central region.
3. Compare actual emitted **region-specific positive-E extrusion paths**, not
   only archive bytes, slicer reports or G-code SHA. The affected region must
   differ materially; an unmodified control region must remain equivalent.
4. Repeat with two modifiers, reversed position, out-of-bounds/no-intersection
   inputs, translated/rotated/scaled parents, saved-draft reload and duplicate.
5. Verify native version-specific parsing rather than silently falling back to
   global settings or ignoring modifier geometry. Validate per-engine settings
   availability, error handling, isolated worker and security regression.
6. Check desktop/mobile preview and parent/child selection, editing and reset
   operations. Confirm print-submission guards are unchanged.

**Current state:** editor/model draft metadata, translucent geometry preview,
fail-closed execution and structural native-style modifier-part 3MF fixture
export are implemented. **Actual native-engine parsing and regional G-code
behaviour are not yet verified** for OrcaSlicer, Creality Print or Bambu Studio;
the fixture exporter is not yet enabled for production slicing. This branch must remain **Draft**
and issue #178 remains open until all acceptance gates above are met.


## Current PR implementation and validation status (23 November 2026)

The feature branch is reconciled with the released v1.7.1 main branch. It
contains the model-owned draft editor and translucent preview, six bounded
primitive meshes, and a native-style parent/component/part 3MF generator.
Further fixes include independent modifier identities when duplicating a model,
matching torus preview dimensions, preserving parent XYZ rotation, non-uniform
scale and bottom-clearance transforms in the fixture, a 48-region plate-wide
save/UI limit, and editable regional wall counts.

The production queue **still refuses all modifier-bearing slice requests**.
The standard worker 3MF validator also continues to reject nested modifier
parts by default. An explicitly selected, bounded
`allow_native_modifier_fixture` validation mode exists only for isolated
acceptance fixtures and does not change the service or the normal admission
path.

`.github/workflows/native-modifier-orca.yml` builds matching 15%-baseline
and 50%-regional modifier projects and exercises the pinned **real** Orca
binary under UID 10001 with no network, printer or persistent state.
`slicer_worker/modifier_acceptance_probe.py` compares central-region
positive-E G-code with a lower, unaffected control region. Its first
diagnostic run must be examined: a structural/CLI success alone is **not**
proof of a regional modifier's effectiveness. Do not treat this workflow's
`continue-on-error` diagnostic step as a required passing acceptance gate.

**Still required before changing PR #196 from Draft to Ready:**
- Actual Orca CLI acceptance and region-specific positive-E proof on the
  pinned binary, including a reversed modifier and two-modifier case
- Equivalent native project parsing and spatial G-code proof against pinned
  Creality Print and Bambu Studio, not an assumption of BBS interoperability
- Production worker admission for *only* proven engine+version configurations,
  and demonstrated non-printing modifier parts and safe failure semantics
- API save/reopen and duplication, rotated/scaled preview equivalence and
  desktop/mobile UX review, plus full latest-head CI and staging acceptance

Do not add feature flags that silently enable an unverified engine, export a
modifier as an independently printed solid, or merge this PR solely on
structural 3MF tests.


## 23 November 2026 — native binary acceptance checkpoint

Actual pinned **OrcaSlicer 2.5.0**, **Bambu Studio 02.09.01.70** and **Creality Print 7.3.1** binaries now accept isolated native modifier fixtures for **all six primitive shapes**: box, cylinder, sphere, cone, disc, torus. The tests compare genuine positive-E extrusion in affected and unaffected regions across baseline, upper, lower and paired modifiers. Creality's *native* eight-member external-mesh 3MF is required; a generic BBS-style 3MF fails its native input checks and is not a valid substitute.

The Creality native project-loader and additional five shapes are now **required** GitHub Actions gates. The deliberately unsupported generic-format import remains informational only. These tests exercise fixture-only validation and do **not** mean the production backend/worker has secure native-project export or admission. Production modifier-bearing jobs remain rejected intentionally.

**Merge blockers:** per-engine production export with strict owning-asset and bounded archive admission, full result validation and no silent modifier loss; real-binary independent XYZ move/rotation/nonuniform scale cases; persistence/reopen/duplicate and responsive UI acceptance; current-head green checks and staging trial. Keep PR draft until those are satisfied.

## 23 November — required real-binary gates extended

Orca 2.5.0, Bambu 02.09.01.70 and Creality 7.3.1 now run **required** real CLI G-code acceptance jobs for (a) the box modifier's baseline/upper/lower/paired regions, (b) the five other primitive shapes, and (c) a world-coordinate modifier with independent 12° X tilt, −8° Y tilt, 35° Z rotation and 110/90/105% nonuniform scale. The modifier has its own geometry and transform; it is not moved as part of the target model.

These are acceptance checks for **isolated native fixtures only**. Required workflows are not a substitute for the still-missing production backend exporter, strict worker admission, owner-scoped source validation, native format controls, output audit, or end-to-end UI smoke. Keep modifier-bearing jobs **rejected** until those are tested in a single production path. No misleading "merge-ready" or release labels should be applied on the strength of fixture checks alone.

## Independent modifier transforms (PR #196 follow-up)

New modifiers created through **Add model → Add parameter modifier** now use
`coordinate_space: "world"`, an independently persisted plate-centred
position, three XYZ Euler angles and three XYZ scaling percentages. A modifier
can be selected on the plate and manipulated using its own Move / Rotate /
Scale gizmo or numeric controls, without modifying the associated STL mesh.
The associated model is still the *regional slicing target* and the modifier
is **never** added to the printable build list.

New modifiers do not follow later transformations of the target model.
For predictable duplication, copying a model together with its modifier
drafts initially offsets the newly cloned modifier poses by the copied
model's X/Y displacement; the copies are independent thereafter.

Existing draft records with no `coordinate_space` retain their original
parent-local semantics and validator contract. Never silently reinterpret
saved local records as world-space positions. Explicit Assemble grouping
remains separate from model boolean/geometry merging; this change does
not automatically convert modifiers into printable solids or add a new
Assemble operation.

The fixture exporter bakes independent modifier transforms into modifier
mesh vertices. The production worker remains fail-closed until all
engine/version acceptance and secure project admission requirements pass.
