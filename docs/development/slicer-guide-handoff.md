# Future standalone MakerVault Slicer guide — documentation handoff

Status: **planned for the separate docs repository, after the slicer is feature-complete.**

The maker-facing slicer documentation should be a dedicated guide. Do **not**
expand the main MakerVault user guide into a slicer manual. The main guide
should retain only a brief overview and a link to the standalone guide.

Suggested topics to capture during development:
- Installing and upgrading engine workers, pinned binaries and native profiles
- Printer, process and manufacturer filament presets; importing inherited parents
- Single- and multi-plate build preparation; STL/3MF and project drafts
- Object transforms, assembly, measure, cut, hollow, drill, mesh Boolean and modifiers
- Per-object and per-CFS-slot filament profile mapping and colour painting
- Flushing matrix, colour estimates, multipliers, native data and safe material transitions
- Slicing, G-code inspection, preview and verified printer upload/start paths
- Mobile navigation, troubleshooting, engine discrepancies and print safeguards

Move/maintain this outline in the dedicated docs repository when the
standalone slicer guide is begun. Keep engineering caveats and technical
details there instead of filling the application UI with explanatory paragraphs.

UI language policy: British English **colour** is the default. US/Canadian/
North American setup timezones use **color** in presentation strings only.
Never rewrite native profile JSON, stored filament names, G-code, API field
names or source identifiers.
