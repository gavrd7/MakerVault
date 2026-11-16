# MakerVault native slicer compatibility and translation contract

Status: **foundation landed; no native paint export is approved**.

MakerVault is the owner of the editable model, paint polygons, surface semantics,
material source associations, plate transforms, and process/layer settings.
Native slicing engines are output adapters, not the source of truth.

## Execution boundaries

1. **Editable draft**: user geometry and annotations are preserved, regardless of
   which engine can interpret them.
2. **Capability negotiation**: engine key AND exact installed version determine
   whether an annotation can be edited in the selected workspace and whether
   its native export is verified. The `/api/printing/slicer/engines/` response
   publishes capabilities. Values are `verified`, `draft_only`,
   `unverified`, and `incompatible`.
3. **Native translation**: a future adapter maps precise MakerVault surface
   polygons, filament/tool bindings and layer bands into an engine-native
   project. All omitted or lossy mappings are explicit errors.
4. **Real worker verification**: a pinned exact executable must produce
   inspectable toolpaths, test slices and expected feature signatures.
5. **Physical printer submission**: a separate printer/firmware/material
   topology capability check verifies tool changes and safety. A successful
   offline slice is not print approval.

## Current contract

- Orca 2.4.2/2.5.0: all five semantic features are `draft_only`. This keeps
  painting available for edit/save/reopen tests, not native G-code export.
- Cura: no accurate native translation is currently implemented;
  `incompatible` disables those editor tools while preserving saved edits.
- Other engines and unreviewed versions: `unverified` (fail closed).
- Normal non-painted ABS slicing, native global fuzzy skin settings and
  single-material G-code remain independent of this surface-annotation gate.
- Existing backend queue admission still rejects unexportable surface edits;
  no frontend capability status can independently unlock worker execution.

## Future engine adapter interface

An adapter should accept a validated immutable project specification with:
- source mesh fingerprint and per-object local mesh transform;
- clipped polygon patches with semantic type and action, including erasure;
- layer-height bands and per-object process parameters;
- logical filament identities independent of physical CFS/AMS/MMU/IDEX slots;
- explicit target engine key/version and hardware-tool topology.

It should return a native project binary plus a **translation receipt** listing
all consumed features, exact adapter/engine versions, object IDs, converted
surface-patch count, fidelity assertions, and diagnostics. It must reject:
- unsupported features, rather than silently dropping them;
- paint geometries that cannot be reproduced at selected precision;
- changed mesh fingerprints or invalid native assignment references;
- ambiguous filament and tool selection;
- mismatched native exporter and worker versions.

Recommended acceptance order: variable layer range, support enforcer/blocker,
seam enforcer/blocker, selective fuzzy skin, then per-region material painting.
Native exporter activation must follow independent real-binary fixtures for
each supported engine version. Cura requires independently demonstrated
equivalence; UI similarity and common slicer ancestry are not sufficient.

## User experience

- Disabled tools display a reason and suggest OrcaSlicer for draft editing
  when appropriate. Never suggest that Orca currently has *verified* native
  painting export.
- Before changing engine or version, show incompatible existing annotations;
  user acknowledgement must preserve those annotations, not flatten them.
- Draft/project save remains available. Slice is blocked whenever the current
  plate contains any annotation without verified export capability.
