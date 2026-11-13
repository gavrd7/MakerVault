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


## Printer-loaded material mapping (CFS, AMS, RFID spools)

Reuse the existing provider-neutral live material slot inventory. MakerVault
already reconciles the latest observed slot details from supported printer
adapters (e.g. Creality CFS and other systems) and can link an observed slot
to an inventory spool when identity is verified. The initial editor's
**Multifilament** panel now reads this shared inventory and displays loaded
slots without writing to printer hardware.

**Next acceptance milestone:** expose a single, consistent material
assignment model, independent of the selected slicing engine:

1. Identify the printer, adapter, system, unit, slot and last-observed state.
   Differentiate fresh vs stale data. Slots may be empty or lack a reliable
   RFID identity; never invent spool links based on colour alone.
2. Treat physical spool, native engine filament preset and tool/extruder
   mapping as *different objects*. Link explicitly; warn for missing material,
   diameter/temperature mismatch and unsupported tool counts.
3. Allow an entire object or an individual printable mesh component to select
   a loaded slot and preview the corresponding swatch. Preserve mapping when
   saving/reopening the project.
4. Use the same mapping for colour/material painting after the selected engine
   supports the required native painted region/3MF format and CLI round-trip.
   Map painted regions to an engine tool index, *then* to printer slot identities
   through the selected printer's adapter.
5. If a printer has no live material telemetry, allow manual assignment of
   the physical spool and native filament preset without pretending a
   particular slot is loaded.
6. Reconcile again immediately before slicing and before explicit print
   submission. Changed or stale material identities should prompt a review,
   not silently change model colours or tool indices.
7. The preview legend must distinguish intended filament, assigned tool and
   live printer slot; the chosen colour swatch is not proof of loaded material.
   Spool inventory is not deducted at slice time.

Cross-engine capability matrix must explicitly identify whether each engine
and version supports multiple objects/tools, per-object material mapping,
painting, variable layer height, tool changes and native project round-trips.
Unsupported features are disabled instead of simulating an incorrect slice.

The current read-only loaded slot panel is a *discovery foundation*, not
multi-material printing support. Native engine and physical printer test
fixtures are required before enabling object-level selection or painting.

## Native material routing implementation (November 2026)

A common, non-vendor-specific route has two distinct axes:

- **Single nozzle with filament changer:** multiple physical bays feed one hotend
  (e.g. CFS/AMS); the engine must select virtual filament IDs, generate
  unload/load/flush sequences from the machine's approved native profiles,
  and account for tower/flush waste.
- **Independent toolheads:** each native tool selects its dedicated hotend
  (e.g. Snapmaker U1); preserve offsets, docking/parking and standby/heating
  logic from the manufacturer's actual verified printer profile. Do not apply
  CFS-style purging or invent a toolchange macro.

Implemented groundwork: `slicer_material_routing.py` validates an explicit
mapping from physical slot IDs to zero-based engine tools; Orca 3MF generation
can write one-based per-object `extruder` metadata for individually preserved
mesh objects. These native indices are **not** derived from slot order.
Unit tests cover both topologies and malformed/conflicting routes.

**Not enabled in the production slicing worker yet.** The existing verified
compound-3MF route merges objects, and worker input currently includes a
single native filament preset. Generated multi-material G-code requires
engine-specific *multiple* resolved filament presets, printer-native tool
configuration, complete object retention, and binary evidence that its actual
G-code includes intended tool changes. Therefore mapped drafts intentionally
fail closed at queue admission and have disabled Slice controls in Prepare,
rather than printing all assigned colours as one material.

Before activation:

1. Resolve an ordered native filament palette matching the selected engine
   and version, each preset inherited and owned/verified, with compatible
   nozzle/material temperatures and validated machine tool count.
2. Bind each saved object to a **verified** native tool index through the
   selected physical printer's topology and live slots; reject missing,
   stale, cross-printer or conflicting assignments.
3. Use the unmerged, object-preserving 3MF; demonstrate a pinned real Orca
   CLI fixture for at least two differently assigned objects. Assert actual
   tool changes and per-tool extrusion in the generated G-code (not just
   metadata or a preview swatch). Verify cooling, purging and estimates.
4. Separately verify a CFS/AMS-style single-nozzle fixture and a dedicated
   toolhead fixture. Snapmaker U1 requires its own approved native profile,
   firmware and physical acceptance; do not reuse K2 printer commands.
5. Restore slicing UI only for exact verified topology/profile/engine
   combinations. Print submission is a separate, explicit safety gate.

### Ordered native filament palette and G-code evidence

Implemented preparatory modules:

- `slicer_native_material_palette.py` accepts an explicitly ordered list of
  **verified** native Orca filament presets, resolves owner-scoped native
  inheritance, checks same engine/version and consistent filament diameter,
  verifies every assigned native tool has a corresponding selected preset,
  and returns immutable per-object tool indices plus profile bytes.
- `slicer_material_gcode_audit.py` inspects *executed* T-index commands and
  positive XY extrusion for every expected native tool. Comment-only T codes,
  tools selected without deposition, or missing tools fail the evidence check.
  This is a **G-code acceptance aid**, not proof that printer firmware will
  interpret those tools correctly.

Both are deliberately disconnected from worker dispatch; the existing worker
request currently takes a **single** native filament profile. Next work is an
explicit versioned multi-profile worker contract, verified Orca CLI fixture,
and separate manufacturer-specific toolchange acceptance, with no fallback
to single-filament output when assignments are present.

### Multi-material worker contract and real-binary acceptance (November 13)

The worker now accepts a bounded optional `filament_profiles` array alongside
the legacy first-filament field. It is Orca/3MF-only and requires 2–16 ordered,
nonempty, independently size-limited native JSON presets with matching first
profile bytes. Orca's fixed `--load-filaments` argument receives only trusted
scratch paths, never arbitrary user arguments. Worker 3MF validation permits
one-based `extruder` metadata *only* for a matching multi-profile request,
requires every object to have an assignment, and requires at least two distinct
tools. Worker output is rejected if its selected tools fail to deposit material.

An isolated CI fixture now slices two separate cubes through real Orca 2.4.2
using two tool indices. The stronger experimental acceptance gate additionally
requires deposited extrusion in the expected left/right cube regions, not just
purging or metadata. The diagnostic is **non-blocking** until that real binary
and exact printer configuration pass; CI workflow overall success is NOT proof
that the optional diagnostic passed. Inspect the individual `k2_two_tool`
step outcome before making any support claim.

Production `SliceJob` admission remains disabled for projects with
`material_slot` mappings, and no printer commands or automatic print
submissions were enabled. This is intentionally not yet a verified end-to-end
multi-colour feature; further requirements include native K2 CFS toolchange
and purge behaviour, verified live slot/profile reconciliation, a
manufacturer-specific U1 toolhead profile/offset/dock sequence, and
painting-region export with native 3MF round-trips.

### Engine-level blocker observed in real CI

The two-colour offline K2 fixture has reached the pinned Orca 2.4.2
executable with two filament presets and valid object extruder metadata,
but the CLI segfaults (exit `-11`) before producing G-code. This is
consistent with upstream Orca reports:
- https://github.com/OrcaSlicer/OrcaSlicer/issues/15632
- https://github.com/OrcaSlicer/OrcaSlicer/issues/14181

**Do not claim the diagnostic passed merely because the overall real-Orca
workflow is green**: this experimental step uses `continue-on-error` to
preserve existing single-material CI coverage.

Software preflight now includes `prepare_offline_material_plate`, which
checks explicit physical-slot/native-tool bindings and owner-verified ordered
native filament profiles, rejects overlapping mesh envelopes, and creates
unmerged per-object 3MF with matching native extruder metadata. This routine
does not queue or transmit a job.

**Release criteria**, in order:
1. A pinned Orca version (or alternate engine with equivalent native
   acceptance) must slice the two-object, two-tool fixture with actual tool
   selections and extrusion in the expected model regions, not merely a
   green CI workflow.
2. Repeat with the actual approved machine profile, two compatible material
   profiles, and topology-specific switch/park/purge start/end sequences.
3. Reconcile loaded slots and native-tool bindings again immediately before
   slicing and printer submission; support clean cancellation and errors.
4. Only then enable the matched engine+version+profile+topology combination
   through explicit per-printer capability checks. Never enable globally or
   infer machine abilities from a CFS/AMS label alone.
5. Independently validate G-code interpretation on K2 CFS. Snapmaker U1
   requires a separate, actual multi-toolhead profile and subsequent
   acceptance; both share the MakerVault UI without sharing printer macros.

Until those checks pass, saved assigned slots remain project metadata;
slicing mapped drafts is disabled, and the proven single-filament path is
unchanged.

### G-code postprocessing and material flushing (13 November)

**Post-slice editing:** The saved G-code viewer has an explicit `+ G-code`
control alongside the visualiser's layer slider. It reads the **complete**
original file (not the 80k-segment sampled preview), matches native
`;LAYER_CHANGE`/`;Z:` boundaries, inserts user-entered commands *after*
the selected layer and before the next layer marker, previews the exact
insertion, and saves an immutable new asset version. Missing/ambiguous layers,
invalid code, final layers without successors and files over 32 MiB are
rejected. No edit replaces the original file or starts a print. Firmware-
specific pause and temperature commands require human review.

**Native flush preparation:** Orca's directional `flush_volumes_matrix`
is in mm³, row=from tool, column=to tool. Its native `flush_multiplier`
multiplies matrix entries, and `enable_prime_tower` controls tower generation.
MakerVault's filament sidebar now has a collapsible per-slot directional
table, optional multiplier (blank=inherited) and prime-tower choice
(native/enabled/disabled). Draft settings are strictly validated, saved and
restored; the offline material preflight maps physical slot IDs onto
verified native Orca tool indices and derives a new process profile **without
mutating the source profile**.

No generic per-printer multiplier is fabricated. Verified profile data is
retained wherever available; missing native matrix cells require explicit
values for every directed transition. Independent toolheads are rejected by
the single-nozzle CFS/AMS flushing path. Actual purge/unload/load sequences
are never handwritten by MakerVault; they remain owned by selected,
manufacturer-appropriate native profiles.

The pinned 2.5 real-Orca workflow includes an experimental, *nonblocking*
two-tool process-profile fixture with deliberately artificial 300/220 mm³
transitions and prime tower enabled. Passing this probe does **not** mean
flush waste volumes, wipe tower placement, firmware toolchanges or print
quality are certified. Product slicing with intended CFS/AMS assignments
remains disabled until the native tool mapping, flushing/prime-tower G-code
semantics, printer-profile compatibility and physical acceptance are
verified.

### Per-printer capability resolution — mandatory, never vendor-wide

MakerVault must **never** equate a manufacturer with a material topology.
Creality, Bambu Lab, Prusa, Flashforge and other vendors each have multiple
printer architectures; an individual printer may also have optional MMU
accessories, separately addressable nozzles, an independent-toolhead changer,
or a combination of these. Example product families and model names discussed
during development (K3, H2D/H3D, XL, CORE One INDX, Creator 5) are
**research targets**, not machine capabilities verified from their names.
Do not add hardcoded model support from names alone.

Capability resolution must be performed for the **specific registered
printer and its installed hardware configuration**, with explicit
provenance and confidence. Suggested separated fields:

- Printer identity: manufacturer, exact model/variant, firmware and machine
  profile identity; verified nozzle count, material paths, physical toolheads
  and tool positions; installed/paired MMU, feeder or toolchanger modules.
- Material topology: an array of independent **material paths** and
  **toolheads** plus explicit relationships, rather than a single
  manufacturer-wide `single_nozzle_changer`/`independent_toolheads` flag.
  Those two values remain supported for the initial verified implementations,
  but cannot represent all hybrid devices on their own.
- Capabilities: supported switching mechanism per path (manual, MMU, nozzle,
  toolhead docking, IDEX), native G-code dialect/commands, verified purge/
  unload/load behaviour, wipe/prime tower suitability, shared nozzle mixing,
  nozzle/tool offsets, collision/parking rules, bed zones and available
  material-slot sensor telemetry. Every value is capability evidence,
  not a guess from manufacturer or installed slicer engine.
- Sources and overrides: verified printer profile, signed device telemetry,
  documented supported accessory/firmware combinations and an explicit user
  confirmation for optional installed modules. Unknown/conflicting details
  fail closed. A user-provided override cannot silently grant an unverified
  physical print-start capability.
- A snapshot/fingerprint of the *effective* hardware topology, selected
  slicer engine/version, profile versions, bindings, and loaded materials must
  be stored with the draft/preflight; it must be reconciled at slice and
  submit time. Changing firmware, installed feeder modules or toolhead
  configuration invalidates the old mapping.

**Routing separation:** one observed feeder slot is not one toolhead, and
one toolhead is not necessarily one material. Route material source
→ designated nozzle/toolhead → native slicer tool index using verified
bindings. For a hybrid machine, choose the purge strategy *per transition*:
same-nozzle colour swap uses directional flushing; another nozzle/head may
require tool changes/offsets/parking/priming rather than shared-nozzle
flushing; mixing both may require both in the same print.

**Engine separation:** the MakerVault capability contract is shared; each
versioned engine adapter must translate it into that engine's native
configuration and independently prove output. Do not assume common upstream
Orca lineage means identical machine or toolchange commands.

**Release gate:** no multi-material slicing, printer upload or start is
enabled merely by a model name, brand, physical slot list, available
preset or nominal multi-colour support. Require a tested compatibility
record for the exact machine configuration + engine adapter + native
profiles + transition strategy. First-stage K2 CFS and independent-head
tests are evidence for their configurations only, not automatic approval
for other printers from the same manufacturer.
