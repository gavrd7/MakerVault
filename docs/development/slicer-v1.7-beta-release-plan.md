# MakerVault v1.7.0 — Slicer Beta release scope and integration checklist

Status: proposed release plan, **not a release approval**. Owner-selected sequence:
**v1.7.0** ships a working Bambu Studio alongside OrcaSlicer and Creality
Print, with the slicer explicitly labelled **Beta**. Further engines can be
introduced incrementally in **v1.7.1, v1.7.2, ...** as the owner prefers,
with separate compatibility notes and pinned binaries.

## Reviewed branch state (21 November 2026)

- PR [#171](https://github.com/gavrd7/MakerVault/pull/171) is a large,
  long-lived **draft** foundation branch. The comparison with main was
  **3,456 commits ahead, 11 behind** and the API's first 300 changed-file
  entries already included unrelated camera, power, Home Assistant and
  dashboard changes. Those are not all slicer-release code. The result
  requires integration-branch reconciliation and independent release
  scope review before any merge.
- The owner reports earlier successful MakerVault physical multi-colour
  Creality/K2 test cubes. Preserve that working route. Current Creality
  multiplier, directional flush matrix and project override code exists;
  source diagnostics showed a response to an experimental multicolour
  machine capability activation. Do **not** call this a production
  flushing-volume end-to-end print approval without the matching evidence.
- Latest targeted tests: **61/61** Creality safety/profile regressions and
  **4/4** cross-printer topology tests passed on Debian staging; painting/
  spatial tests previously passed. Do not rerun old fixture matrices
  merely for documentation or a Beta label.
- The worker currently admits **OrcaSlicer, Creality Print, PrusaSlicer**.
  **Bambu Studio does not yet have an executable runner, allowlisted
  worker contract, installed/pinned binary or G-code extraction adapter.**
  Its existing official upstream catalogue is read-only *model artwork*
  metadata, not importable native printer/process/filament preset chains.
  Therefore Bambu Studio is **not yet a working engine** and must not be
  advertised as such.

## v1.7.0 delivery boundary

| Area | Release requirement | Current disposition |
| --- | --- | --- |
| MakerVault Slicer UI | Load models, edit/arrange plate, select supported engine, profiles, filament assignments, slice and preview | Implemented on foundation; release regression needed after branch cleanup |
| OrcaSlicer | Pinned binary, verified native profiles, supported single- and multi-material routes | Existing integration; retain actual feature-by-version evidence |
| Creality Print | Preserve owner-confirmed physical multicolour workflow; native plate/painting/flushing integration; visibly scoped beta limitations | Implemented and extensively tested, but some offline-only flags remain; reconcile against confirmed printed jobs before promoting |
| Bambu Studio | Exact reviewed release/binary, sandboxed native 3MF/STL slicing, official full machine/process/filament profile resolution, bounded output extraction and independent toolpath audit | **Not implemented; required before v1.7.0** |
| Printer safety | No silent print start, preserve original vendor macros, explicit physical printer identity/material mapping, valid ownership and operator approval | Retain and test; don't suppress merely to label Beta |
| Distribution | Install/upgrade/rollback pinned multi-engine worker; architecture, licensing notices, Docker/host install verification | Must pass full integration smoke on supported self-hosted deployment |
| Documentation | Beta limitations matrix, supported engine versions, known printer/topology restrictions, rollback guidance | Needs release-page and docs pass |
| PR scope | Reconcile main, isolate unrelated changes, review migrations and perform one full release build/check pass | **Not ready for merge** |

The earlier user-confirmed multicolour prints and subsequent synthetic
fixtures have different evidentiary scope. A failed or inactive stock-profile
flushing probe does not negate an earlier working CFS print; conversely a
working CFS print does not prove every user-selected flush-volume override
is applied end-to-end.

## Cleanup decisions

1. **Retain** real security and safety protections: exact binary/container
   hashes, profile ownership and inheritance, engine/version compatibility,
   G-code bounds, physical tool/slot mapping, printer dispatch and
   explicit confirmation. A `Beta` badge is not permission to bypass them.
2. **Remove or retire** outdated *diagnostic-only* instructions and
   duplicate staging scripts from the release documentation after
   mapping each to current production functionality. Keep standalone
   regression tools accessible for maintainers; do not delete tests for
   still-supported behaviour.
3. **Reconcile Creality execution/test-only semantics** with previously
   successful real jobs. Do not automatically enable
   `multicolor_method=1` on a stock/vendor profile; don't require the
   experimental value for unrelated machines, and do not change
   manufacturer tool-change macros.
4. **Advertise capabilities truthfully**: engine availability reflects
   an approved installed engine; feature status reflects native verified
   engine/version/geometry boundaries. Unsupported operations should
   state *which* capability is missing, not silently flatten edits.
5. **Split the integration change set**: compare every touched file
   against main, separate unrelated camera/Home Assistant changes and
   investigate branch divergence, keep migrations in dependency order.
   Do not squash or force-push #171 without an explicit branch recovery
   plan and review of all dependent changes.

## Next engine: Bambu Studio v02.09.01.70 baseline

Begin from the existing pinned **v02.09.01.70** official metadata
reference, not an unreviewed latest release. Bambu's official CLI
documents `--load-settings`, `--load-filaments`, `--slice`,
`--export-3mf` and `--outputdir` flows; a 3MF with G-code must be
handled as a native archive and verified before converting any output
into MakerVault's independent G-code library.

- Review source licence/packaging and build a pinned Linux binary in
  the isolated engine store with a checked executable digest and native
  resource bundle; no runtime downloads or host PATH lookup.
- Add a standalone Bambu runner and only then add `bambustudio` to
  engine-registry, worker payload admission, dispatch and error
  mapping. Do not alias Bambu to the Orca runner without verifying the
  exact CLI/output contract.
- Implement full *leaf + inherited* machine/process/filament profile
  resolution, including referenced custom G-code/include files where
  required. The current `slicer_bambu_official_profiles.py` provides
  printer-model metadata only.
- First accept a small verified **single-material** Bambu Studio slice,
  then multi-material with native tool/filament mapping (when exact
  topology/firmware is known). A working engine is required for v1.7.0;
  it is acceptable to explicitly mark more advanced tools
  *unavailable in Bambu Beta* rather than blocking the release.
- Bambu printer LAN/cloud delivery is a **separate** printer adapter
  feature; a functioning Bambu slicer does not require the application
  to upload or start files on a Bambu printer.
- A single representative pinned-binary G-code acceptance, targeted
  code tests and one final full integration/regression run after
  implementation are preferable to endless ad hoc fixture rounds.

Official CLI reference: https://github.com/bambulab/BambuStudio/wiki/Command-Line-Usage

## Post-v1.7.0

Ship the next reviewed slicer engine in **v1.7.1** (candidate:
PrusaSlicer, since there is already a restricted worker runner),
followed by separate increments for Snapmaker Orca and remaining
engines. Release notes must distinguish *slicer slicing support* from
manufacturer *printer-control* support and mark exact engine versions,
supported operations and beta caveats.
