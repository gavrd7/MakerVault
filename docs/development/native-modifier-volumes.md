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
