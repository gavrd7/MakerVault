# MakerVault painting v2: surface regions rather than original STL faces

Status: **incremental implementation in progress**. The v2 surface-region schema,
clipped-polygon preview renderer, frontend/backend validation and draft
round-trip foundation are committed. The interactive paint tools still
write v1 facet assignments; v2 editing, erasure/overlap resolution,
3MF round-trips and native engine export are **not yet connected**.
Do not enable physical multicolour slicing from painted regions.

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
