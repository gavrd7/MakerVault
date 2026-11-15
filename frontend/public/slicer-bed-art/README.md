# Printer-native and MakerVault build-plate assets

MakerVault's 3D plate preview uses two independent asset types:

- Native **bed_texture**: a validated, same-origin, cached SVG overlay.
- Native **bed_model**: a bounded, validated STL rendered **below** the editable
  print surface as non-interactive machine-space geometry.

Neither affects slicing, G-code, nozzle movement, firmware purge routines, bed
dimensions or the printer compatibility matrix. An unavailable asset always
falls back to the procedural MakerVault plate.

## Bundled starter assets

The Creality K1/K2 SVGs are attributed to OrcaSlicer 2.4.2 contributors and
upstream asset authors, distributed under the source project's AGPL-3.0 terms:

- https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.4.2/resources/profiles/Creality/creality_k1_buildplate_texture.svg
- https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.4.2/resources/profiles/Creality/creality_k2_buildplate_texture.svg

`makervault-official-logo.svg` uses the official MakerVault logo provided by
the project owner, rather than the previous placeholder icon.

## Version-aware imported source adapters

| Profile source | Upstream metadata | Behaviour |
| --- | --- | --- |
| OrcaSlicer | Machine JSON and indexed `machine_model` JSON | Imported official machine profiles, inherited parent chain, 3D model and texture |
| Creality Print | Machine JSON and indexed `machine_model` JSON | Registered official machine profiles, model and texture |
| Bambu Studio | `machine_model` JSON and indexed vendor models | Registered, verified model records; associated native assets |
| Snapmaker Orca | Orca-compatible JSON and indexed vendor models | Registered official source metadata |
| PrusaSlicer | Vendor INI `[printer_model:...]` | Exact registered model/bundle mapping to bed model and texture |

Registration does **not** mean every engine is installed or supports
slicing. The official-search/import interface now provides release-pinned
catalogue selection for OrcaSlicer, Creality Print and Snapmaker Orca, plus
**model/artwork-only** candidate imports from Bambu Studio and PrusaSlicer.
These new adapters need end-to-end validation against real assets and printers.
Only a verified worker and compatible native *printer, filament and process*
presets can enable slicing; metadata-only model records are never sufficient.

Source identity is constrained to a fixed list of upstream repositories and
vendor names. Imported records must have a matching registered engine version,
upstream release tag, source label and hash-verified owner-scoped file. A profile
can never supply a network host, arbitrary URL or local filesystem path for
the artwork fetcher. When an engine lacks a validated upstream tag or metadata
format, no network fetch occurs.

Orca, Bambu, Snapmaker and Creality machine variants often reference a
separate `machine_model` record for `bed_model` and `bed_texture`. MakerVault
checks the official version-tagged vendor index for an **exact** model name;
a non-unique or missing identity is not replaced with a guessed match.

The original SVG and STL are bounded and validated before being cached by
source URL digest in private storage. The preview only serves those assets
to the profile owner. Network failures result in the MakerVault fallback, and
already-cached valid files remain usable offline.

Assets from other upstream licences need their original attribution and
distribution terms reviewed before inclusion in bundled releases. The
cached source artifacts are not MakerVault-owned artwork.

## Remaining improvements

- Expand Bambu Studio and PrusaSlicer metadata-only model browsing to
  complete validated native printer/filament/process profile import workflows,
  without turning vendor model records into executable presets.
- Discover profiles and artwork from *installed* engine versions in the
  isolated worker, rather than from source-labelled imports alone.
- Validate renderer orientation, native STL offsets and asset availability
  on real machines for each vendor and unusual bed polygon.
- Expand support to other engine asset formats and explicit asset-directory
  layouts without permitting arbitrary external URLs or host filesystem access.
