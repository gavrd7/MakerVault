# K2 Combo / CFS — controlled staging acceptance

**Scope:** A first multi-colour hardware acceptance on the user's registered
Creality K2 Combo, with **one nozzle and CFS**. This does not approve other
Creality printers, AMS/MMU hardware, IDEX, or independent-toolhead models.

## Software proof required before physical testing

- Official, independently SHA-256-pinned OrcaSlicer **2.5.0** worker.
- Resolved native K2 0.4 mm machine, verified process and PLA filament
  profiles. The machine profile must explicitly declare a single-nozzle
  multi-material changer, non-manual material changes, a native changeover
  macro and prime-tower purging. A model name alone is not capability proof.
- The bounded two-model, two-tool native 3MF passes real-engine acceptance.
  Model-region deposited extrusion must correspond to its intended native
  tool index, not merely to a preview swatch.
- Directional native flushing matrix correctly serialised as Orca native
  **string-valued array**, plus native **per-nozzle multiplier array**.
  The current 300/220 mm³ tests are **arbitrary development fixtures**,
  not safe manufacturer recommendations.
- G-code audit must observe both tools depositing on their respective
  objects, at least two tool changes, non-model extrusion from both tools
  and independently labelled prime-tower deposition. It must reject
  absent/ambiguous evidence, and it never pretends to simulate firmware.
- A separate same-material, **black/white** native filament-palette fixture
  must pass the above checks; this verifies distinct profile support,
  not physical matching of spool colours.

The real Orca 2.5 CI workflow records these results; the K2 profile/prime
tower audit is a *required* check when invoked. Some additional probes are
still exploratory and may be marked `continue-on-error`; inspect their
**individual step outcome**, not only the workflow's green status.

## Stage A — testing in the existing MakerVault UI

1. Update staging to the reviewed development branch and verified worker
   image, using the existing isolated worker installation process.
2. Confirm registered printer and firmware identity, nozzle diameter, CFS
   accessory and current live CFS slot telemetry. Do not infer compatibility
   solely from 'Creality', 'K2' or a profile filename.
3. Load two ordinary compatible PLA spools into two physical CFS slots.
   Refresh slot inventory; review manufacturer, material and colour.
4. Put two small separate models on a plate; assign different **intended
   physical slots**. Confirm model tree, swatches and saved draft round-trip.
5. Inspect the directional flushing table. Use verified native preset
   values wherever available. Never copy CI's 300/220 mm³ figures into a
   real printer without calibration. Verify the prime-tower setting.
6. Verify that mapped drafts are **still blocked from normal Slice and
   direct printer submission** until the per-printer runtime gate is
   implemented. The UI should explain that these are intended mappings.

## Stage B — prerequisites for a supervised *real* K2 test

Do not bypass the above block merely to run a physical print. Before
implementing the supervised flag, the app must still:

- Offer explicit **slot → native tool** mapping with selected native PLA
  profile per tool (including real colours and independent profile IDs).
- Recheck ownership, K2 model/firmware, nozzle, CFS presence and selected
  live slot identity immediately before slicing and again before submission.
- Compare selected printer+profile+engine+topology against a versioned
  successful acceptance record; missing or stale evidence fails closed.
- Generate and preview complete native multi-material G-code with its
  nozzle/filament transition macros, flush and prime-tower extrusion; make
  the output visible for manual inspection before any transfer.
- Separate **upload only** from **start print**, with explicit operator
  approval, compatibility verification and cancellation available.
- Preserve the original G-code and immutable subsequent edited versions;
  inserted pauses are firmware-dependent and require separate validation.

Only when these software gates pass should the supervised K2 print be
enabled. The first physical print should use two small PLA parts with
contrasting colours on a clear plate, monitored throughout the first
changeovers. Confirm each unload/load, purge location, prime-tower adhesion,
head clearance and colour cleanliness. Stop on wrong-tool, collision,
unexpected temperature, clog or incorrect CFS state.

## Remaining boundaries

Nothing in this acceptance plan enables print-start, writes CFS firmware,
changes printer configuration or asserts a real machine passed. The current
`slicer_execution._validate_plate_execution` deliberately refuses
`material_slot` mapped drafts. Do not remove this block until the explicit
per-printer and per-slot hardware gates are implemented.
