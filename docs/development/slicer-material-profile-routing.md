# Slicer material/preset identity contract

## Applies across slicer engines and printer material architectures

This is a common data-integrity rule, not a promise that all engines can
currently execute or that a physical changer/toolhead has been integrated.

**Three independent identities:**

1. **Physical material source**: a selected printer-owned physical bay,
   manual spool, AMS/CFS slot, or toolhead filament source
   (`printer_id`, `slot_id`, `slot_index`).
2. **Native engine filament preset**: an owner-scoped imported preset with
   an exact engine key and version (`profile_id`). It determines print
   temperatures and native process/material parameters.
3. **Logical engine tool**: a slicer palette index. Its mapping to hardware
   tools/heads is adapter- and printer-specific and is **not inferred**
   from physical bay index or array order.

**Invariant for any single-material slice**: If the model is assigned to a
physical material source, that source MUST have an explicitly selected native
filament preset of the correct engine/version. At draft creation the backend
resolves this into the actual `SliceJob.filament_profile` and
`SliceJob.filament_preset`. Admission revalidates the same source/preset
identity before handing profiles to the isolated worker. Missing or mismatched
mapping fails closed. The main preset is permitted only when models have no
physical slot assignment.

Other loaded physical sources may retain their native preset selections as
inert metadata; only the model-assigned source affects the single-filament
slice.

**Scope of cross-engine tests**: draft inheritance for every engine
advertised in the catalogue (Orca, Creality Print, Bambu Studio, PrusaSlicer,
Snapmaker Orca, ElegooSlicer, Cura, Anycubic Slicer Next), and numeric /
identity checks across representative material families. This verifies
the common *selection and storage contract*, not executable CLI support.

**Scope of hardware-topology tests**: single-nozzle changes (including CFS
and AMS), independent heads, toolchangers, IDEX and manual changes. Physical
source indexes never implicitly become native tool indexes. Multi-material
execution and physical printer submission remain feature-gated until the
selected engine and adapter/profile/firmware combination is individually
validated. Slicers can disagree about palette numbering, temperature G-code,
headchange timing and purge requirements.

## Outstanding work before multi-material print release

- Adapter-backed identification of the *actual* loaded spool/material,
  including unknown/replaced RFID slots, without trusting UI labels alone.
- Confirm physical material is compatible with the selected native preset,
  plus nozzle, bed/build plate and target temperatures. A PLA temperature
  profile must not silently be sent to print ABS.
- Versioned per-engine palette export and roundtrip 3MF/G-code validation
  for each supported topology, including independent toolheads / IDEX.
- Explicit per-printer changeover/purge/prime-tower compatibility tests.
- Submission-time verification of physical slot identity, profile identity,
  printer state and supported routing, not just successful G-code generation.
- End-to-end integration testing on actual printers before enabling
  non-Orca or physical multi-material transfers.

Until these milestones pass, the system must clearly distinguish a saved
draft or offline preview from a verified and safely executable print.
