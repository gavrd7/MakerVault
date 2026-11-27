# MakerVault PrusaSlicer feature-parity acceptance matrix

**Status:** development only; draft PR #213. This is the completion
contract for Prusa integration. It is **not** a requirement to implement
all upstream PrusaSlicer capabilities. Every row describes an existing
MakerVault workflow that must work through the same desktop/mobile UI as
the three established engines.

## Completion policy

A row is **done** only when the existing MakerVault control is wired to a
real Prusa setting/project operation, authenticated worker slices genuine
2.9.7 G-code, and a targeted audit confirms the requested geometric or
material effect. No source facet, modifier, tool or setting may be silently
discarded. Basic GUI availability or a zero-exit native slicer call is not
sufficient evidence. Keep all feature additions inside the Prusa adapter
and shared engine contract; regression-test Creality, Orca and Bambu.

Do not translate the absence of owned Prusa hardware into arbitrary
maximum tool count or disabling offline slicer functions. The printer's
actual native extruder/MMU topology determines permissible assignments.
Physical submission requires separate verified firmware and start ACK
tests; leave unsafe printer-start blocked until that is proven.

## MakerVault workflow checklist

| MakerVault feature | Existing Prusa route | Current acceptance / outstanding gap |
| --- | --- | --- |
| Install, uninstall, version and identity | Verified installer and pinned binary, shared worker | Native install/uninstall acceptance exists; ensure UI parity on staging |
| Profile browse/import and global numeric settings | Native profiles, official catalogue, shared pagination | Import and native overrides covered; verify filament manufacturer search against UX requirement on both layouts |
| Add/select/transform/disassemble multiple models | Native 3MF, STL bake, shared plate placement | Up to 200 instances under resource budget; manually inspect assembly tree and controls |
| Primitive shapes, infill modifiers and negative volumes | Native 3MF modifiers and negative bodies | Basic native effects tested; **mixed paint + modifier/negative** is still explicitly rejected |
| Single-material slicing + G-code / thumbnail / preview | Common slice worker and Library | Binary and storage paths covered; confirm full shared UI navigation and preview on staging |
| Global and per-object settings | Native numeric process + 3MF object config | Bounded speed, walls, shells, infill, brim and skirt audited; other MakerVault object controls need parity review |
| Colour paint, material mapping and tool selection | Native TriangleSelector, MMU/XL/INDX material adapter | T1–T7 and one/two complete opposite X/Y faces qualified; **arbitrary painted regions, more paint swatches or multiple colour-painted models** blocked |
| Printer filament list with >4 tools | Printer-derived native topology | MMU5 / XL5 and eight-head INDX proved in real CLI; verify saved and restored UI state and no extra fixed limit |
| Support painting | Native painted support and spatial audit | One selected painted model among up to 200 objects qualifies; simultaneous multi-object paint variants remain unqualified |
| Seam painting | Native facet seam states and G-code spatial audit | Qualified pinned directions only; test broader requested MakerVault seam selections |
| Fuzzy skin painting | Native facet fuzz, owner geometry and G-code audit | **2–200 objects, including multiple independently painted objects**, now mapped; real fifteen-object one/two-painted native CLI assertions must pass before marking done |
| Variable layer height | Native layer range 3MF + object-local toolpath audit | **2–200 single-material objects** now mapped; require native fifteen-object one-variable/fourteen-baseline positive-E tests. MMU combinations remain unqualified |
| Prime tower, purge and independent heads | MMU directional purge; no tower on XL/INDX | Genuine binary tests for MMU, XL and official INDX exist |
| Print from slicer and printer start confirmation | Shared submission adapter; PrusaLink API | Offline G-code valid; native Prusa physical toolchange upload/start currently intentionally guarded. Do not present upload as print start confirmation |
| Mobile and desktop | Shared React components | Required manual visual/interaction pass on actual staging before ready-for-review |

## High-priority remaining integration gaps

1. Generalize colour painting beyond the existing one/two fully painted
   walls and beyond a single colour-painted object, proving correct
   per-region toolpath deposition. Do not fake masks by painting whole walls.
2. Compose MakerVault's independently proven modifier, negative,
   support, seam, fuzzy and variable-layer features in a single native
   project without dropping requested operations; test representative
   combinations, one by one, against genuine G-code.
3. Reconcile the per-object and global MakerVault settings schemas and
   model limits, then verify the existing mobile/desktop editor and
   imported profile selection rather than adding a separate Prusa UI.
4. Finish the common slicer-to-printer UX (modal close, preview, actual
   printer start acknowledgement) in a manner that does not bypass
   native firmware/toolchange qualification. The lack of physical Prusa
   hardware must remain an explicit final physical validation criterion.
5. Pass all exact-head Prusa, Orca, shared worker, frontend and Django
   workflows, plus a staging UI pass. Merge **only after** every MakerVault
   feature row is supported, or the user explicitly approves a tightly
   documented, genuine upstream incompatibility.

Older PR #199 native experiments and their historical notes are kept in
`docs/development/prusaslicer-engine.md`. The exact restored production
branch remains untouched by this draft.
