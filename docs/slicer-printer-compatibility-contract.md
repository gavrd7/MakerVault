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

## Reference activation evidence: Creality Print GUI versus native CLI

Before a printer-specific physical print, establish the **actual**
CFS-enabled slicing path using a small two-material model in the
manufacturer's Creality Print 7.3.1 desktop application, selecting
the correct printer and attached CFS. The physical CFS slots must be
confirmed in Creality's native Device/Filament mapping workflow.
This is not a change to the stored MakerVault machine profile.

**Single offline reference capture (no print submission):**

1. In Creality Print 7.3.1, select the matching manufacturer's
   machine preset and a connected CFS-capable printer, assign two
   native filaments to a small model, and verify the displayed
   filament mapping. Do not change any machine start/tool-change script.
2. Slice in the GUI, review the native toolpath preview, use
   **Export to Local** to save the exact CFS-enabled G-code, and save
   the matching project as a local 3MF where supported. **Do not
   click One-click Print, Send or start a physical print.**
3. Review the project's effective `multicolor_method`, native
   `change_filament_gcode` lineage, native filament/first-load
   assignments and generated G-code's initial CFS load, T selects,
   M8200, FLUSH_START/END and M83 state. Compare with the pinned
   offline MakerVault engine's existing output. Be alert to
   `wall_filament=0` or other invalid initial tool assignment,
   which users have reported as a historical CFS failure mode.
4. Only then adjust the **generic Creality capability adapter**
   if a stable native distinction is demonstrated. Preserve
   manufacturer scripts and apply changes only to explicitly
   compatible printer profiles. No implicit K2-derived feature
   selection and no automatic physical printer submission.

Sources, accessed 21 Nov 2026:
- Manufacturer [K2 series multicolour guide](https://www.creality.com/blog/k2-series-multi-color-printing-guide):
  CFS enabled at print selection; file-to-CFS slot mapping is a
  distinct operation. Without CFS enabled, the manual says
  multicolour files may be treated as single-colour.
- Manufacturer [CFS management guide](https://www.creality.com/help/help-guide-to-using-cfs-on-the-creality-print):
  connecting the printer and selecting Auto Mapping matches
  detected CFS filaments to native presets.
- Manufacturer [Creality Print quick-start guide](https://www.creality.com/uk/help/help-creality-print-quick-start-guide):
  GUI supports local G-code export without LAN Print.
- [Creality community comparison of versions](https://forum.creality.com/t/k2-plus-starts-to-print-without-loading-filament/51844):
  users reported incorrect `wall_filament=0` and different
  `multicolor_method` values in older version G-code; these are
  anecdotal/version-specific, not a proof about 7.3.1.

**Known blocker:** No authentic CFS-enabled desktop-generated 7.3.1
G-code/project sample for this exact user-selected printer has been
provided or verified yet. The existing `multicolor_method=1`
in-memory diagnostic is *not* equivalent to this reference. The
official baseline profile must remain unchanged. A successful
offline macro audit alone must not be interpreted as CFS physical
routing approval.
