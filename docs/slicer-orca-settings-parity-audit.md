# OrcaSlicer settings parity audit

Audited: 2026-11-09
MakerVault branch: `feature/self-hosted-slicer-foundation`
Reference: official [OrcaSlicer Wiki](https://github.com/OrcaSlicer/OrcaSlicer_WIKI/blob/main/mkdocs.yml) across Quality, Strength, Speed, Supports, Multimaterial and Others, plus Printer and Material settings.
Runtime validation target: the currently pinned OrcaSlicer 2.4.2 worker. The online wiki may document later versions, including nightly/2.5-only features.

## Principles

1. A MakerVault control must correspond to an actual key in the selected *resolved* native Orca profile; never add a key that the preset does not define.
2. Restrict overrides to validated types and ranges; do not modify startup/filament-change G-code or postprocessors through the normal settings panel.
3. Make feature-dependent inputs conditional on the native enabling control, including nested choices. Do not reset or silently delete a dependent value when toggled off.
4. Preserve native profile inheritance. Original vendor profiles remain read-only; process overrides affect only the draft; custom profile changes are saved as copies.
5. Treat editor visibility and successful backend validation as distinct from an accepted *real Orca binary* slice. Do not claim end-to-end parity until both are exercised.
6. Keep other engines' native settings separate from Orca's schema; avoid mapping Orca keys into unrelated backends without proven equivalence.

## Implemented in this audit batch

- Enlarged the safe native process registry to 245 documented numeric, choice or toggle keys, from about 115 previously.
- Quality: ironing modes/pattern, Z contouring, seams, walls, overhangs and Arachne wall tuning where native keys exist.
- Strength: infill choices and advanced shell/infill controls.
- Speed: first-layer/travel, acceleration, jerk and small-perimeter settings.
- Supports: support styles/patterns, tree support, support ironing, nested enablement.
- Multifilament: a subset of prime-tower, flushing and ooze-prevention controls.
- Others: fuzzy skin, skirts, brims and print mode controls.
- Simple/Advanced/Expert filtering; conditional controls only when their native parents allow them.
- Broader safe scalar printer/filament profile editing. Multi-extruder/multi-channel arrays are deliberately not mass-edited from one scalar input.

## Remaining parity gaps, not falsely represented as complete

These are representative documented gaps identified in the category-by-category comparison; they are not all safe to expose without version-specific enum values, dependency rules and real-engine tests.

| Area | Still requires validation or implementation |
| --- | --- |
| Quality | More scarf seam options, precise Z height, polyhole conversion, some bridging controls and wall generator edge cases |
| Strength | Advanced surface expansion and fill order, linked infill-direction options, additional infill combination/anchor controls |
| Speed | Junction deviation and extrusion-rate smoothing, some overhang-specific speeds |
| Supports | Feature filament assignments, tree branch geometry and extruder-specific support material logic |
| Multimaterial | Full prime-tower family and variant-specific constraints; feature-to-filament assignments; detailed interface and interlocking options |
| Others | Timelapse, advanced fuzzy ripple options, exclusion/output edge cases |
| Printer profiles | Complete printer motion, hardware, bed and multiple extruder editing, plus native boolean/enums/arrays; hardware G-code is deliberately protected |
| Filament profiles | Cooling controls, overrides, temperatures and material-specific lists with proper per-extruder representation; not yet full GUI parity |
| Object scope | True per-object/native process overrides; currently global process settings only |
| Versioning | Some wiki options are newer than the pinned Orca 2.4.2 binary. Runtime support, enum compatibility and version gates must be checked before exposing them |
| Advanced workflows | 3MF painted materials, object-specific profiles and fully native multi-plate export remain separate functional work |

## Test expectations

- Python tests: native choices/toggles/conditional schema, range checks, unchanged protected G-code, custom profile copies, refusal to silently overwrite multi-extruder arrays.
- Frontend tests: detail levels, conditional visibility, precise settings modal placement.
- Real binary: slice known K1/K2 fixtures with representative changed settings, confirm generated G-code and check that native preset inheritance is retained.

The registry is intentionally conservative. An absent key should not be invented simply to make the UI appear equivalent to desktop OrcaSlicer.
