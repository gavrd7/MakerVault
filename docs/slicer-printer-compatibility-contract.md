# MakerVault slicer/printer compatibility contract

MakerVault is printer-agnostic. Each slicer engine parses native profiles;
each printer connection/adapter reports its hardware capabilities. No printer
family name should be treated as proof of CFS/AMS routing or permission to
submit multi-material G-code.

## Separate capability layers

| Layer | Source of truth | What it can establish |
| --- | --- | --- |
| Slicer engine | Pinned binary and native profile loader | Native formats, settings, slicing output |
| Printer geometry | Imported native machine preset | Plate dimensions, nozzle count, bed and limits |
| Material architecture | Printer adapter's material_system | Single-nozzle changer vs toolchanger, independent heads etc. |
| Material assignment | Selected printer slots and native filament profile bindings | Model colour-to-logical tool identity, not hardware bay command |
| Toolchange firmware | Original selected manufacturer machine macro and its native G-code | A bounded print-format candidate, not physical execution |
| Printer delivery | A separate verified printer adapter and operator approval | Whether this printer may receive the generated job |

The same slicer engine can serve different printers, provided their selected
native profiles and adapter capabilities are compatible. Machine names alone
must not select firmware G-code, physical spool bays or native tool IDs.

## Implemented Creality Print 7.3.x scope

- General/native: selected native machine, process and filament profile
  resolution and inheritance, build-plate dimensions, standard slicing,
  existing native painting/variable-layer encoding and a validated worker.
- Current multicolour encoder: **exactly two logical filament materials**,
  **one native nozzle**, and **adapter-declared single_nozzle_changer**.
  It currently builds a 4-entry Creality project palette with only the first
  two entries assigned to the model. Other slots are placeholders, not
  detected physical CFS bays.
- Current native purge output check: the selected *explicitly enabled*
  machine must carry the recognized manufacturer gated macro using
  FLUSH_START/FLUSH_END and M8200, with verified M83 relative E sections
  in generated worker G-code. This is a supported **macro strategy**, not a
  claim that all Creality printers or firmware use these commands.
- Different native layouts (more than two selected filaments, K3
  multi-nozzle configurations, toolchangers, IDEX, or manufacturer macros
  with different commands) remain **unsupported by this specific encoder**.
  Do not fabricate four-slot mapping, duplicate machine nozzles or translate
  commands between firmware families.
- The existing K2-specific legacy fallback in offline_material_system is
  retained for historic K2 staging data. It allows **offline preparation
  only** and grants no printer submission authority. Other printers can use
  the generic adapter-declared material_system route today when compatible.

## Creality Print machine capability activation

The stock K2 preset previously inspected on Debian has an *absent*
multicolor_method value. Its manufacturer toolchange macro contains a
multicolour branch, but the ordinary native slice did not emit flush commands.
A disposable gate probe proved that activating the option makes the engine
emit different native flushing; this **does not authorize silently modifying
the stored vendor profile**.

A future enabled profile must come from an explicitly selected,
manufacturer-compatible native machine configuration. It must retain
the original vendor toolchange macro and native identity/geometry.
Do **not** assume that enabling the Creality GUI's experimental purge-to-
skeleton feature is equivalent to authorizing all CFS hardware: those are
separate questions. Native G-code evidence can pass the offline gate
without proving the printer's material-bay and firmware semantics.
The printer submission gate remains separate.

For other Creality printers, inspect their actual native machine profile and
adapter-declared topology independently. No K2 file, script or purge
parameter should be copied onto a different printer merely to make slicing
appear successful.

## Acceptance boundary

Existing synthetic matrix and spatial comparisons are sufficient to stop
expanding general painting diagnostics at this stage. The next acceptance
is a native machine-profile and generated-G-code safety review for an
**authentically enabled** profile followed by a small **separately authorised**
printer test. Do not automatically turn experimental slices into approved
printer jobs. Additional models require representative real hardware/profiles
before being marked verified; lack of such evidence should appear as
"not yet verified", not "unsupported by Creality Print".
