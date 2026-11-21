# PR #171 — foundation integration review handoff

**State:** branch reconciled with `main`, draft PR pending review and final staging acceptance.
**Do not merge or mark ready solely from this document.**

## Reconciliation completed

| Check | Result |
| --- | --- |
| `main` ancestry | Merge commit `684b98694176a178385efa64bc21a5e48125a5cc`; comparison afterwards showed **0 behind** |
| Current reviewed CI files | Main's revised Orca dependency/build cache workflow preserved |
| Project/support docs | Latest README, SUPPORT, development partners and cover artwork preserved |
| Slicer implementation | Feature source unchanged by reconciliation |
| Bambu change scope | PR #191 remains separate, based on this feature branch |
| PR description | Updated to reflect actual November 21 state, not outdated 6 November prototype |

## Scope audit

PR #171 has **441 changed files** at the reconciliation checkpoint. It is a
long-lived integrated feature branch, not a minimal isolated slicer change.
The following paths must be reviewed independently before merging, even
though they coexist with the slicer:

- Camera and relay: `backend/core/camera_relay.py`,
  `backend/core/camera_views.py`, new `diagnose_camera_*` commands and
  tests, `frontend/src/components/PrinterCamera.jsx`,
  `PrinterCameras.jsx`, `cameraPlayback.js`, `cameraWebRTC.js`.
- Home Assistant printer power and safety:
  `backend/core/home_assistant_api.py`,
  `backend/core/home_assistant_power.py`,
  `frontend/src/components/PrinterPowerAssignment.jsx`,
  `PrinterPowerButton.jsx`, `homeAssistantPower.css`,
  and their regression tests.
- Printer monitoring and UI:
  `backend/core/printer_connectivity.py`,
  `backend/core/printer_controls.py`,
  `frontend/src/components/Dashboard.jsx`,
  `PrintingPage.jsx`, `SettingsPage.jsx`, plus affected tests.

Do not delete these as “unrelated cleanup”: `0081_home_assistant_printer_power_provider.py`
sits between slicer schema migration `0080_slicer_profile_defaults`
and dependent `0082_slicer_profile_source_scope`. There are other
integration edges through printer models and UI. Extracting them would
require verifying and, where necessary, deliberately rewriting both
migration ordering and cross-feature tests.

## Schema review

The visible slicer migrations are 0076–0080, 0082–0085; the Home
Assistant provider migration is 0081 and the slicer/CFS submission
audit migration is 0086. Their sequential dependencies were reviewed
for order. **Actual Django migration application / check and rollback
behaviour are not established by source inspection alone**.

## Feature and safety review

- Existing real-world Creality multicolour cube prints are owner-confirmed;
  no claim of lost functionality should be made without reviewing their
  saved jobs. New native directional flushing/multiplier controls have
  offline fixture evidence but not a blanket guarantee for the stock
  machine's inactive multicolour setting.
- `backend/core/slicer_capabilities.py` and
  `backend/core/slicer_output.py` still declare some
  variable-layer/support/seam/fuzzy/colour and multi-material
  pathways `test_only` and mark printer submissions unverified.
  Do not reinterpret this as a regression in previously
  demonstrated generic CFS print jobs. Retain the scope limitations
  unless matching end-to-end evidence justifies upgrading each.
- Native engine installation remains owner/admin controlled and
  version/digest pinned. Do not auto-enable Bambu or any other
  missing binary or rewrite vendor toolchange macros.
- Multi-material printer delivery has K2-specific CFS mapping
  checks in `printer_gcode_submission.py`; that restriction is
  *delivery-adapter scope*, not a Creality Print slicer engine
  manufacturer allowlist. Future printer adapters require their
  own verified physical mapping.
- Existing G-code submissions require user approval; the worker
  does not silently print or deduct filament.

## Review acceptance still required

1. GitHub Actions status for the reconciled head, including
   worker-contract, application CI, documentation and Orca real-smoke
   workflow. Require successful required checks; investigate actual
   failures rather than rerunning old synthetic paint matrices.
2. One full app integration acceptance on a disposable/staging
   database, including `manage.py check`, `makemigrations --check --dry-run`,
   `migrate --plan`, backend/frontend suites and Compose syntax.
   No physical printer start or worker refresh required for review.
3. Focused independent review of the camera/Home Assistant/power
   scope, including credential handling, permissions, boundaries
   and printer-safety changes. Do not claim full independent security
   review just because CI passed.
4. Check user-facing Beta status and feature capability messages.
   Known test-only modes must remain visibly identified; existing
   verified normal slicer routes must not be hidden by a global
   `test_only` badge.
5. Once green, mark PR #171 ready for code review; merge only after
   review/owner approval. PR #191 can then target `main`
   and be completed for v1.7.0.

## Cross-reference

- [v1.7.0 Slicer Beta release plan](slicer-v1.7-beta-release-plan.md)
- [Cross-printer slicer compatibility](../slicer-printer-compatibility-contract.md)
- [Bambu Studio dependent PR #191](https://github.com/gavrd7/MakerVault/pull/191)
