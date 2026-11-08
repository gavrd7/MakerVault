# MakerVault Interactive Slicer — implementation plan (PR #171 follow-up)

Status: design and execution plan. This is **not** a statement that the functionality is implemented.
Retain the existing approved configuration page as **Slicer Setup**. A saved slicing project opens a distinct full-screen responsive **Prepare / Preview** editor. Use MakerVault-native UI and a separate engine adapter; do not embed a vendor GUI or rely on external cloud slicing.

## Principles

- One consistent MakerVault UI across supported engines, but advertise only capabilities actually supported and tested for the selected engine and version.
- Keep source STL/3MF and project settings independently from generated G-code; neither automatic saving to the Files library nor printing is implicit.
- Never misrepresent a sampled 2D G-code visualisation as a complete native slicer preview.
- Do not give the app Docker privileges or socket access. Keep engine processing in resource-limited, pinned workers.
- Profile data is engine-native. Normalised setting descriptors describe equivalent concepts; conversion/validation remains engine-specific.
- All editing operations, per-object overrides, and painting/modifiers must be serialisable, undoable, and persist across reopening, without silently losing metadata during export.
- Global vs Objects applies wherever meaningful; settings with global-only or object-only scope are clearly marked, not falsely duplicated.
- Preserve external printer submission as a separate consent and verification flow. Never auto-repeat a transmission with unknown delivery status.

## Workflow

**Slicer Setup**: choose verified engine and version, native printer/nozzle/plate, physical spool, associated profiles, initial models; Save draft / Open editor.

**Prepare**: scene/model tree, multi-plate organizer, full 3D viewport, manipulation and painting tools, search and grouped process/filament/printer settings. Persistent draft with explicit save/revert and live validation.

**Preview**: once a slice completes, show one 3D extrusion scene from the *complete* toolpath or a lossless indexed representation, not just the first N G-code moves. Vertical layer-range slider, horizontal toolhead step slider with animated position, move playback and selectable feature visibility. Show slicer-declared time/filament estimates, layer details, legend, travel/retract/wipe/seams, and per-feature statistics. G-code download and library save remain explicit; Send to printer uses existing guarded workflow.

## Capability matrix

| Area | Common MakerVault UI / backend | Engine-specific support or restrictions |
|---|---|---|
| Multiple STL/3MF, plates, import, duplicate, select, move, rotate, uniform / XYZ scale, snap, auto-arrange, measure | Scene graph, transformations, history and coordinates | Native packing, plate conventions and export schema |
| Auto-orient, lay on face, split, cut, mirror, mesh boolean, hollow, drill | Reusable mesh operations with undo and bounded geometry processing | Different allowed modifiers and native project metadata |
| Support painting, seam painting, modifiers, variable-layer-height, colour painting | 3D brush/face/region selection UI and serialised edits | Must be supported by native project format and CLI/engine. Never simulate unsupported native paint settings |
| Process groups | Quality, Strength, Speed, Supports, Multifilament, Others; search, Simple/Advanced; Global/Objects | Map canonical setting ID to native names/types/limits. Some settings are global-only |
| Filaments / extruders | Per-object mapping, physical spool mapping, colour, consumed material estimates | Real multi-material execution needs engine-specific native profile/mapping tests |
| Toolpath preview | Indexed 3D extrusion moves, layer/step scrubbers, feature visibility, camera controls, summary panel | Metadata availability differs: estimated time, line width, speed, temperature, flow, acceleration, fan etc. Show unavailable explicitly |
| Output and print | Save project/draft, slice, add G-code to library, download, explicit send/upload/start | Printer adapter capabilities, acknowledgement and upload verification always independent |

## Preview specification

- Vertical range slider shows a contiguous subset of layers; top and bottom handles where supported, and the current Z in mm.
- Horizontal slider steps through the currently visible G-code segment sequence. Show live virtual toolhead marker, last executed path and upcoming path. Playback controls are optional but useful.
- Colour maps: line/feature type, filament, speed, actual speed, acceleration, jerk, layer height, line width, flow, actual flow, layer time, log layer time, fan speed, temperature, pressure advance — show only supported measured or declared values, with precise unknown/estimated labels.
- Toggles: extrusion feature types, travel, retract/unretract, wipe, seams, supports, brim/skirt, toolhead, build plate, model shell, nozzle/printhead, and other available annotations. Disable unavailable toggles visibly rather than fabricate toolpaths.
- Legend shows statistics and units. Avoid using one feature's colour for another, and ensure selecting a layer doesn't silently alter the model colour.
- Prefer complete layer-indexed worker artifacts (binary geometry and metadata with strict length limits) for responsive loading and accurate UI; preserve G-code as source of truth. If a job is too large, paginate and stream bounded chunks on demand.
- Avoid inferring acceleration, timing, temperatures or line width from XYZ/E alone. Rely on native output metadata or explicit motion commands; mark other data unavailable.

## Delivery phases and acceptance gates

1. **Slicing and printer submission hardening**: capture proof that real STL -> profile -> Orca worker -> inspectable G-code works. K1 native transfer remains uncertain unless a supported native verification source can confirm remote filename and size; do not bypass safeguards or automatically resend. Upload-only and print-start are distinct operations. Add targeted tests.
2. **Prepare editor core**: new route and persistent project scene, multi-plate/object tree, full 3D orbit/pan/zoom, undo/redo, placement, individual XYZ scaling, auto-orient and lay-on-face. Test cross-engine project consistency.
3. **Full 3D layer/step preview**: complete indexed extrusion and travel data, feature legend/visibility, vertical layer and horizontal step scrubbing, toolhead marker, summary and native statistics. Establish parity using known Orca test fixtures, not screenshots alone.
4. **Process settings editor**: typed parameter schemas, categories Quality / Strength / Speed / Supports / Multifilament / Others, Simple/Advanced, Global/Objects, searchable native values, safe edit/restore, inheritance and round-trip tests.
5. **Advanced geometry and painting**: cut/split/boolean/hollow/drill/measure, then supports/seam/colour painting, variable layer height, engine capability gating and native 3MF preservation.
6. **Multi-material and other engines**: independent spool/model material assignment, CFS mappings and preview, tested native output from each engine; additional optional engine implementations without losing UI semantics.

An item is complete only after automated tests, a real-engine fixture, and (where physically testable) staging acceptance. The existing Slicer Setup UX remains unchanged unless necessary.
