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
| Primitive shapes, infill modifiers and negative volumes | Native 3MF modifiers and negative bodies | Independently proven effects. **Colour + Object settings + box infill modifier + separate negative box** generated genuine 2.9.7 G-code with retained T1 paint, inside-region E 90.89 -> 215.13 for modifier and 95.22 -> 0.00 in negative cavity (native run 46083553897). This exact MMU combination is now admitted through the shared workbench with both signed volume geometry and real positive-E/cavity audits on **every** slice; other shapes, overlapping volumes and mixed paint-channel combinations remain blocked |
| Single-material slicing + G-code / thumbnail / preview | Common slice worker and Library | Binary and storage paths covered; confirm full shared UI navigation and preview on staging |
| Global and per-object settings | Native numeric process + 3MF object config | Bounded speeds, walls, shells, infill, brim and skirt audited. **Painted native ModelPart now retains Object controls**; one versus five painted wall loops genuinely yielded 0 versus 6,434 internal-perimeter movements |
| Colour paint, material mapping and tool selection | Native TriangleSelector, MMU/XL/INDX material adapter | **MMU one-/two-swatch partial vertical faces, MMU one-swatch partial top faces, and XL5 partial vertical/horizontal top faces** have source-derived offline admission and mandatory native 2.9.7 deposition audits. MMU two independently split opposite walls: T1=122, T2=126, neither alternate tool leaked into another painted/unpainted region; tower T0=3,624/T1=1,858/T2=1,808 (run 46086291996). One-colour vertical MMU T1=64 with zero unpainted leakage (run 46083933214); horizontal XL5 T1=67 with zero unpainted leakage (run 46084811769). Genuine MMU horizontal top T1 painted=67/unpainted=0, T0 plain=376 and MMU T0/T1 tower purges=2,171/172 (run 46099342292). Existing complete walls, INDX T1–T7 and XL5 four complete faces remain supported. Genuine XL5 T1 partial angled planar brush: 19 T1 painted, 0 T1 unpainted and 80 T0 unpainted positive-E paths (run 46087014378). Multiple disjoint brush regions can share one native colour slot. Curved/nonplanar surfaces and non-T1 angled paint, multiple independently painted models and INDX partial paint remain unqualified |
| Printer filament list with >4 tools | Printer-derived native topology | MMU5 / XL5 and eight-head INDX proved in real CLI; verify saved and restored UI state and no extra fixed limit |
| Support painting | Native painted support and spatial audit | One selected painted model among up to 200 objects qualifies; simultaneous multi-object paint variants remain unqualified |
| Seam painting | Native facet seam states and G-code spatial audit | **15-model true per-object painted seams** proven with two different selected front/back faces: 95 independently correct seam starts on each; unpainted baseline rejected. Broader disjoint arbitrary seam masks still need native verification |
| Fuzzy skin painting | Native facet fuzz, owner geometry and G-code audit | **2–200 model plate, multiple independently painted models**; genuine fifteen-object native output deposited 2,603/2,625 short external moves on selected models, zero on thirteen plain neighbours |
| Variable layer height | Native layer range 3MF + object-local toolpath audit | **2–200 single-material objects**: genuine 15-model binary test proves a 0.12mm schedule on the selected model and 0.20mm on fourteen unaffected neighbours. MMU variable-Z native incompatibility remains unqualified |
| Prime tower, purge and independent heads | MMU directional purge; no tower on XL/INDX | Genuine binary tests for MMU, XL and official INDX exist |
| Print from slicer and printer start confirmation | Shared submission adapter; PrusaLink API | Offline G-code valid; native Prusa physical toolchange upload/start currently intentionally guarded. Do not present upload as print start confirmation |
| Mobile and desktop | Shared React components | Required manual visual/interaction pass on actual staging before ready-for-review |

## Native painting and composition qualification — 27 November 2026

- Native 2.9.7 **MMU split-vertical-wall painting** has completed genuine
  source-mask-to-G-code toolpath qualification: 64 positive-E T1 movements
  within painted facets, **zero T1 in unpainted facets**, 172 T0 in unpainted
  facets and 7 T0 foundation movements on painted facets. The same pinned
  run proved 1,836 T0 and 1,748 T1 positive-E wipe-tower movements. Source
  polygons are fingerprinted and checked again in the worker; G-code is
  independently audited before saving a private slice.
- Genuine native **XL5 split-vertical-wall painting** yielded the same
  independently counted T1/T0 surface isolation without MMU purging.
  Its separate offline route retains a no-tower worker audit. Other XL
  tool counts and INDX are **not automatically certified** for partial masks.
- Genuine pinned **XL5 partial horizontal top-face painting** has now
  passed the independent signed top-plane / positive-E auditor: 67 T1
  movements inside the selected brush region, zero T1 in the unpainted
  model top, 376 T0 in unpainted top geometry and only three T0 foundation
  movements inside paint. Authenticated worker and owner-side post-slice
  checks apply to this source-derived mode. Other independent
  head counts, angled and curved surfaces remain guarded.
- **Native MMU partial horizontal top-face painting:** pinned Prusa 2.9.7
  independently qualified the same signed top brush using its actual
  single-nozzle/MMU path: T1 painted=67/unpainted=0, T0 on unpainted
  top=376, and positive-E wipe tower moves T0=2,171/T1=172
  (run `46099342292`). The normal owner-scoped offline job and isolated
  worker now both require this spatial mask and *both* purge audits; the
  genuine-binary native test is mandatory. XL5 remains separately audited
  without MMU purging.
- **Single painted native infill modifiers** are no longer validated only by
  successful colour G-code. Every MMU and XL5 painted native project
  containing a modifier now also runs MakerVault's existing volumetric
  positive-E region auditor in both the isolated worker and owner post-slice
  acceptance. A requested modifier with no deposition is rejected, and
  subtraction inside qualified negative cavities remains strictly empty.
- MakerVault v2 paint may represent many independent regions with the same
  palette slot. Prusa workbench binding now uses the **distinct slots**
  rather than treating each brush stroke as a separate tool. Overlapping
  facets remain rejected by the native polygon splitter.
- **Two independently split MMU colour walls:** pinned 2.9.7 genuine
  three-tool deposition proved 122 correct T1 painted-wall movements, 126
  T2 painted-wall movements, no T1/T2 cross-wall or unpainted-region
  deposition, and T0/T1/T2 wipe tower paths 3,624/1,858/1,808
  respectively (run 46086291996). Signed native 3MF determines tool order;
  both backend and isolated worker audit every actual G-code result. The
  desktop/mobile workbench uses its existing swatch-tool selector.
- **Scoped colour + Object settings + infill box + disjoint cavity is
  now live for authenticated MMU offline slicing.** On each job the worker
  derives exact typed box geometry from native 3MF, verifies one full T1
  wall swatch, rejects overlapping/unknown shapes, audits T0/T1 wipe-tower
  + painted deposition and uses MakerVault's shared native volumetric
  positive-E auditor. Owner-side post-slice repeats those audits before
  storing the private G-code. Genuine 2.9.7 evidence: 6,333 paths in
  modifier region and **zero inside cavity** (run 46086097259). The
  combined real-binary test is mandatory in CI. No printer-start
  qualification is implied.
- **Native MMU colour plus selective fuzzy on the opposite wall:**
  genuine pinned PrusaSlicer 2.9.7 preserved T1 front coloured wall
  deposition (369 control/370 combined) while producing **3,091** moving
  short T0 perimeter paths on the independently fuzzy-painted back wall
  versus **zero** in the colour-only control; the front's short-wall paths
  remained 376 in both cases (native run `46099472545`). The normal
  MakerVault colour job now retains native fuzzy facet attributes, and both
  isolated worker and owner post-slice paths require the signed complete
  opposite wall plus moving positive-E texture checks. Support, seam,
  variable Z, extra native regions and other toolhead topologies remain
  gated for this precise combination; genuine binary verification is
  mandatory in CI.
- A research-only native project now preserves **four overlapping paint
  channels** (colour/support/seam/fuzzy) and both modifier and negative
  volume meshes, plus Object process controls, without colour states on
  nonprinting modifier geometry. The independent strict validator accepts
  only explicitly flagged research files, never production colour admission.
- Genuine G-code proves the narrower combination **colour + Object + one
  box infill modifier + one disjoint negative box**: inside positive-E in
  the modifier footprint increased about 90.89 -> 215.13; in the cavity
  it dropped from about 95.22 to zero; T1 coloured front-wall deposition
  persisted. This **does not yet lift ordinary mixed-edit admission** for
  arbitrary geometries or overlapping facets. Inspect recorded CI run
  `46083553897` and required current-head run for source proof.
- Even fully audited offline G-code is not evidence of a printer accepting
  native toolchange commands. All Prusa native physical upload/start remains
  guarded until real firmware capability and print-start ACK qualification.

- **Native XL5 T1 partial angled planar paint:** a rotated 30-degree
  single-model test on pinned PrusaSlicer 2.9.7 produced 19 positive-E
  external-perimeter movements within the signed angled patch, **zero**
  T1 deposition on its unpainted portion, and 80 T0 movements outside
  the patch (run 46087014378). The authenticated worker independently
  reconstructs the 3-D source plane, indexes its triangular surface in a
  balanced spatial tree, and checks deposited paths against painted and
  unpainted source facets. Only XL5 T1 single-model planar angled masks
  are admitted; curved/nonplanar masks, other tool counts and multi-model
  paint remain guarded. The genuine binary test is mandatory.

### Staging desktop/mobile and printer workflow sign-off

Use the **existing** MakerVault interface on both viewport sizes, no Prusa-only
UI: choose printer and process/filament catalogue profile; verify filament
manufacturer list and profile pagination; add, transform and assemble models;
select native tools beyond four; save/reload a painted draft and visually
compare regions, object tree and modifiers; complete a qualified offline
slice and open its full-quality G-code preview; add to Library and confirm
that the preview remains visible after submission modal closure. Verify that
a dispatched but unacknowledged print is labelled pending, never "started".
Exercise a real PrusaLink printer for physical start confirmation **only**
after native toolchange firmware qualification; do not bypass the guard for
this checklist. No real-hardware sign-off is claimed by automation.

## High-priority remaining integration gaps

1. Extend proven **one/two-swatch MMU partial vertical walls** and **XL5 vertical/top partial masks** to curved/nonplanar surfaces and other-tool angled masks, non-opposing multi-colour masks, multiple independently painted models and separately qualified INDX partial masks. Audit real G-code spatial tool deposition for each independent region; never substitute whole-wall rectangles for split masks.
2. Expand the now-verified **MMU colour + Object + infill box + disjoint
   negative box** and separately qualified **MMU T1 front colour + opposite
   T0 selective fuzzy** to arbitrary native shapes and simultaneous support,
   seam, variable-layer and other paint edits without dropping requested
   operations; qualify each native combination against genuine spatial G-code
   and worker audits.
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
