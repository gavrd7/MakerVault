"""Creality 7.3.1 verified single-material, multi-model placed STL adapter.

Distinct from its CFS and native modifier project paths.
"""
from .slicer_placed_stl import build_placed_stl


def build_creality_single_filament_plate(objects_with_stl, *, bed_width, bed_depth):
    return build_placed_stl(
        objects_with_stl, bed_width=bed_width, bed_depth=bed_depth)
