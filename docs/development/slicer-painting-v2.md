# MakerVault painting v2: surface regions rather than original STL faces

Status: **Painting v2 and draft/project persistence are implemented. Native OrcaSlicer
2.5.0 colour facet conversion is available in the explicit offline multi-material
test/export route. Physical printer submission remains blocked pending acceptance.**

- New painting uses a versioned, mesh-fingerprinted, ordered clipped-polygon
  representation. Existing v1 face-colour drafts remain editable in legacy mode
  until an explicit migration exists.
- Brush, circle, sphere, height-range, fill and smart-fill tools now route
  new edits through v2 surface patches. Convex overlap subtraction supports
  targeted erasing and recolouring rather than whole-facet erasure.
- Region overlays are independent of printable STL geometry. Workspace
  history provides undo/redo for immutable region edits.
- Draft validation is implemented in both frontend and backend. MakerVault
  project 3MF export/import stores v2 regions as validated, bounded sidecars,
  preserving the real polygon coordinates across a round-trip.
- These sidecars are **MakerVault-specific editable metadata**. The explicit
  offline Orca multi-material test converts validated v2 patches into
  `paint_color` annotations using a verified logical filament palette;
  standard single-filament slicing does **not** compile the paint.
- Shared support enforcer/blocker surface-region painting now uses the v2 selector and
  independent action annotations, with Erase, Clear all, brush, sphere, fill
  and height-range UI. MakerVault drafts and MakerVault project 3MF sidecars
  retain support regions; previews use separate green/red overlays.
- Native support/seam/fuzzy facets have passed the separate single-filament
  acceptance slice. Combined support + variable layering requires compatible
  normal/manual supports. Cross-feature multi-material printing has **not**
  been accepted for printer submission.
- Remaining: staging acceptance tests, cross-engine native material export,
  proof of 200k+ facet responsiveness, spatial indexing/large-mesh latency,
  improved adaptive topology, geometry validation hardening and future
  support enforcer/blocker use.

## Offline multi-colour acceptance, 17 November 2026

The current dev branch offers a deliberately gated native Orca test for
two-filament **single-model painted** or multiple assigned model plates.
It is not an unrestricted printer-print workflow.

1. Colour paint v2 polygons are clipped into native facet geometry; original
   STL coordinates, fingerprint and unpainted surfaces are preserved.
2. A colour palette swatch must explicitly reference a loaded slot on the
   selected printer. The slot must have a verified engine/version-matched
   native filament profile. Bay numbers and swatch RGB values do not imply
   tool numbers. Other loaded but unused bays are ignored.
3. Ordered native tool indices start at zero with the chosen main filament
   preset. MakerVault emits Orca `paint_color` leaf states 4 / 8 / 0C / 1C
   and an object default extruder. Legacy whole-face painting remains blocked
   until converted explicitly. Editable MakerVault project sidecars are kept
   independent of this conversion.
4. The worker accepts only exact finite 3MF geometry and bounded paint codes
   from the declared native palette. The generated G-code must contain
   positive extrusion evidence and explicit selection for all intended tools.
5. **Upload and start remain blocked** for test G-code, irrespective of
   success. A visual match is not evidence of firmware slot mapping, purge
   safety, material compatibility or a suitable prime tower.

Next test on staging: paint one Benchy in two loaded K2 CFS colours, select
matching native profiles for both slots and the main filament, press **Slice**. MakerVault automatically selects the offline multi-material route,
then inspect the G-code and T0/T1 extrusion audit.
If Orca's CLI rejects `paint_color` or omits a tool, do not disable the
validator; investigate its native project metadata and pinned binary.
Also verify mixed-colour per-object placement and geometry preservation.

Flushing configuration: single-nozzle native multi-material tests may carry
a validated custom flush multiplier while retaining Orca's original native
matrix. Directional volume overrides require a verified tool-indexed matrix
or complete explicit transitions; no zero-volume defaults are invented. The
3MF geometry-only export does not carry process flushing changes. The
single **Slice** action selects the offline test route automatically when
two distinct native filaments are used (including one colour-painted model).
The model's colour overlay remains visible outside painting mode.

Remaining for release: stable real-engine acceptance, physical CFS slot→tool
mapping verified at print submission, purge/flush and changeover sequencing,
G-code colour preview, print permissions across adapters, and full
cross-feature/regression tests. Do not mark these as implemented.

## Problem confirmed by staging (13 November 2026)

Current MakerVault `colour_paint.version=1` stores sparse original STL
triangle indexes, drawn with per-face colours. A circular brush crossing
a triangle boundary colours **the entire triangle**. A height band
selects intersecting triangles but cannot colour only the portion inside
the band. Increasing polygon hit detection cannot make this accurate.
Coarse or long triangles make the problem particularly apparent.

Changing the preview without changing the saved representation would be
misleading; the preview and persisted draft must express the same regions.

## Reference: OrcaSlicer v2.5.0

- `src/libslic3r/TriangleSelector.hpp`, `TriangleSelector.cpp`: adaptive
  triangle splitting (`select_patch` with `triangle_splitting`) and
  distinct Circle, Sphere and HeightRange cursors.
- `src/slic3r/GUI/Gizmos/GLGizmoPainterBase.cpp`: painting mouse
  processing, per-model selectors, seed fill and cursor previews.
- `src/slic3r/GUI/Gizmos/GLGizmoMmuSegmentation.cpp`: filament painting.
- `src/slic3r/GUI/Gizmos/GLGizmoFdmSupports.cpp`: shared painting
  foundations for support enforcers/blockers.

Reference URLs:
https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.5.0/src/libslic3r/TriangleSelector.hpp
https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.5.0/src/libslic3r/TriangleSelector.cpp
https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.5.0/src/slic3r/GUI/Gizmos/GLGizmoPainterBase.cpp
https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.5.0/src/slic3r/GUI/Gizmos/GLGizmoMmuSegmentation.cpp
https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.5.0/src/slic3r/GUI/Gizmos/GLGizmoFdmSupports.cpp

## Required design

1. Make one shared **surface painting selector** with independent
   brush geometry and assignment state. Modes: visible-surface brush,
   radius-bounded sphere, orientation-constrained fill, height range.
   Later: support enforcer/blocker painting; no second geometry engine.
2. Use adaptive **boundary splitting** around affected original
   triangles, not global subdivision of the entire STL. For a brush,
   intersect the locally projected disc with the surface; for height
   painting, clip each intersecting triangle against exact Z planes.
   Triangulate the resulting polygons for the render overlay.
3. Store `colour_paint.version=2` as validated, ordered editable regions
   or deterministic subtriangle trees, each anchored to immutable model
   mesh fingerprint and transforms, rather than original face-only flags.
   Ensure undo, erasure, draft save/reopen and 3MF export preserve the
   *same actual regions*. Old v1 drafts must remain loadable.
4. Keep original model geometry unchanged: derived overlay/subtriangles
   must never replace the printable geometry or generate incorrect
   project asset IDs. Bound subdivision complexity, memory and event
   latency; use an adaptive edge-length floor (Orca's selector uses a
   configurable edge limit) and spatial indexes for large STLs.
5. A v2 slicer adapter must map these exact regions to the appropriate
   native engine-supported paint representation, with explicit CFS
   slot-to-tool validation. Until then painting stays **preview only**.
6. Apply shared geometry and persistence to support-painting states
   (enforce, block, auto). Avoid conflating per-slot filament assignments
   with support tags.

## Acceptance gates

- Brush over a large planar triangle has a circular, not triangular,
  boundary; both preview and reopened draft preserve that boundary.
- Height range exactly terminates at both Z planes across sloped and
  vertical triangles, including holes, rotated instances and negative
  geometry. No missing rows or painted outside-band strips.
- Fill ends at intended geometric boundaries without cascading around a
  connected shell or jumping between disconnected islands.
- Paint/erase/undo/redo, mobile touch navigation, 3MF round-trip and
  selected-slot colour all produce identical results.
- 200k+ facet model remains responsive, with bounded memory and
  no per-pointer-motion full-mesh copy.
- **No physical multi-colour start** before native region/tool encoding,
  printer live mapping and purge validation are exercised end-to-end.

## Interim v1 maintenance

The existing v1 frontend can improve intersection detection and coverage,
but **cannot eliminate jagged face boundaries**. Do not describe those
improvements as smooth brush painting or complete support painting.

## Support-painting acceptance (first integration pass)

- **Enforce supports** and **Block supports** are mutually exclusive semantic
  annotations; neither value is a physical spool slot or a nozzle/tool index.
- The colour and support surfaces are independent. Support overlay drawing
  does not alter source STL geometry or existing filament painting.
- Brush, sphere, fill and height paint reuse the same clipped polygons and
  mesh fingerprints; an eraser removes only selected support paint.
- Paint, erase, undo/redo, draft save/reopen and MakerVault project-3MF
  round-trip must retain the same regions on both desktop and mobile.
- **Do not slice or print a support-painted draft** until the selected engine
  can encode the exact regions as its supported enforcer/blocker metadata.
- Next verification: load the staging UI, test both annotation types, restore
  a saved draft and exported 3MF, verify erase plus selection history, and
  assert native slicing is rejected with a clear explanatory error.
