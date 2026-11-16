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
   publishes capabilities. Values are `verified`, `test_only`, `draft_only`,
   `unverified`, and `incompatible`. `test_only` is strictly offline and
   must always carry a no-printer-submission marker.
3. **Native translation**: a future adapter maps precise MakerVault surface
   polygons, filament/tool bindings and layer bands into an engine-native
   project. All omitted or lossy mappings are explicit errors.
4. **Real worker verification**: a pinned exact executable must produce
   inspectable toolpaths, test slices and expected feature signatures.
5. **Physical printer submission**: a separate printer/firmware/material
   topology capability check verifies tool changes and safety. A successful
   offline slice is not print approval.

## Current contract

- Orca 2.4.2: all five semantic features are `draft_only`.
- Orca 2.5.0: variable-layer ranges are `test_only` for an **offline**, single,
  upright, unscaled model. The native adapter writes
  `Metadata/layer_config_ranges.xml` and audits actual `;LAYER_CHANGE` / `;Z:`
  increments against each requested interval. Generated G-code carries
  `variable_layer_test=true` and is explicitly denied printer submission.
  Support enforcer/blocker painting is also `test_only` for one upright,
  unscaled model: saved clipped brush polygons are re-triangulated into
  equivalent native faces carrying Orca's `paint_supports=4/8` states.
  The worker accepts only these exact leaf annotation values. Source STL
  fingerprints are checked in the same local coordinates used by the browser.
  Generated G-code is marked `support_paint_test=true` and is denied upload/
  print start; actual support generation still needs a pinned-binary
  comparison before declaring the adapter verified.
  Colour, seam and selective fuzzy skin painting remain `draft_only`.
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

## Remembered loaded-filament presets

The selected native filament profile for a detected material is now saved as
an owner-scoped database preference independent of slicing drafts. The key
includes the physical printer, engine/version, and a privacy-preserving hash
of material/product/vendor/colour identity (or a spool/RFID identity when
product information is unavailable). It is **not** keyed only by CFS/AMS bay
number: a different filament loaded into the same bay does not inherit the
previous profile, whereas an identical product in another bay can reuse the
saved choice.

All manual slot-preset selections and successful official imports write the
preference immediately. Reopening the editor or refreshing filament slots
fetches and restores matching preferences; owner-scoped API validation
rejects unrelated printers, stale/foreign native profiles, unrecognised
versions and unidentified materials. Explicitly saved draft settings are
still retained and are not overwritten during ordinary rehydration.

The current application has no automatic backfill of preferences from old
drafts. Existing manually chosen profiles need to be selected once after
this migration, after which their associations are remembered. A missing
material fingerprint is reported rather than persisted ambiguously.
