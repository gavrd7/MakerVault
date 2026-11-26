"""Creality single-material multi-model plate encoded as placed native STL.

Creality Print 7.3.1 rejects the generic core 3MF path with external filament
presets (CLI validation exit 205). For plain single-material plates only,
re-use the independently tested bounded STL facet transformer. This deliberately
does not alter the native Creality 3MF modifier/CFS/painting paths, nor the
single untransformed STL fast path.

The historical Prusa helper is a geometry-only encoder: it uses MakerVault's
engine-neutral STL inspection and bed-centred scene transformations and emits a
standard binary STL. Its native CLI arrangement policy is NOT reused.
"""
from .slicer_prusa_plate import build_prusa_placed_stl


def build_creality_single_filament_plate(objects_with_stl, *, bed_width, bed_depth):
    """Bake independently validated models with unchanged MakerVault positions."""
    return build_prusa_placed_stl(
        objects_with_stl, bed_width=bed_width, bed_depth=bed_depth,
        max_faces=1_500_000, max_stl_bytes=32 * 1024 * 1024)
