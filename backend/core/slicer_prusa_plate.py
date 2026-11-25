"""Prusa-only, single-material native STL plate with exact preview transforms.

This does not create a Prusa 3MF project, smuggle object settings into
profiles, or modify the established Orca/Creality/Bambu plate exporters.
All source STLs must already have passed owner and integrity checks.
"""
import math
import struct

from .slicer_plate_3mf import _triangles, _transform
from .slicer_mesh import inspect_stl, MeshInspectionError
from .slicer_profiles import SlicerProfileError

MAX_FACES = 500_000
MAX_STL_BYTES = 32 * 1024 * 1024


def build_prusa_placed_stl(objects_with_stl, *, bed_width, bed_depth):
    """Bake independently transformed meshes into ONE explicit-position STL.

    Input X/Y are bed-centred visual coordinates. Source meshes are centred
    about their XY bounding boxes and lowered to Z=0 before rotation, matching
    the MakerVault native 3MF preview/export transformation. Each object is
    checked against the selected native rectangular build area.
    """
    if not isinstance(objects_with_stl, list) or not 1 <= len(objects_with_stl) <= 12:
        raise SlicerProfileError("Prusa plate needs one to twelve verified source STLs.")
    if not all(isinstance(n, (float, int)) and not isinstance(n, bool)
               and math.isfinite(n) and 1 <= n <= 1000 for n in (bed_width, bed_depth)):
        raise SlicerProfileError("Prusa plate requires verified native build dimensions.")
    records = []
    faces = 0
    for index, pair in enumerate(objects_with_stl, 1):
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise SlicerProfileError("Invalid Prusa plate source.")
        item, raw = pair
        if not isinstance(item, dict) or not isinstance(raw, bytes):
            raise SlicerProfileError("Invalid Prusa plate source.")
        try:
            inspected = inspect_stl(raw)
            if inspected["triangles"] < 1:
                raise ValueError()
            tris = list(_triangles(raw))
        except (MeshInspectionError, ValueError, UnicodeDecodeError) as exc:
            raise SlicerProfileError("Prusa plate contains an invalid STL.") from exc
        faces += len(tris)
        if len(tris) != inspected["triangles"] or faces > MAX_FACES or 84 + 50 * faces > MAX_STL_BYTES:
            raise SlicerProfileError("Prusa plate geometry exceeds the native STL limit.")
        if (item.get("modifier_volumes") or item.get("process_overrides")
                or (item.get("colour_paint") or {}).get("regions")
                or (item.get("colour_paint") or {}).get("faces")
                or (item.get("support_paint") or {}).get("regions")
                or (item.get("seam_paint") or {}).get("regions")
                or (item.get("fuzzy_skin_paint") or {}).get("regions")
                or (item.get("variable_layer_profile") or {}).get("bands")):
            raise SlicerProfileError("Unsupported Prusa object settings cannot be discarded.")
        vertices = [v for tri in tris for v in tri]
        if any(not all(math.isfinite(float(n)) and abs(float(n)) < 1_000_000 for n in v) for v in vertices):
            raise SlicerProfileError("Prusa source STL coordinates are unsafe.")
        minimum = [min(v[axis] for v in vertices) for axis in range(3)]
        maximum = [max(v[axis] for v in vertices) for axis in range(3)]
        pivot = ((minimum[0] + maximum[0]) / 2,
                 (minimum[1] + maximum[1]) / 2, minimum[2])
        try:
            values = [float(v) for v in _transform(item, bed_width / 2, bed_depth / 2).split()]
        except (ValueError, TypeError, KeyError) as exc:
            raise SlicerProfileError("Prusa object placement is invalid.") from exc
        if len(values) != 12 or any(not math.isfinite(v) for v in values):
            raise SlicerProfileError("Invalid Prusa object transform.")
        if float(item.get("z_mm", 0)) != 0:
            raise SlicerProfileError("Prusa elevated or stacked objects are not yet approved.")
        def mapped(point):
            x, y, z = (float(point[i]) - pivot[i] for i in range(3))
            return (values[0]*x + values[3]*y + values[6]*z + values[9],
                    values[1]*x + values[4]*y + values[7]*z + values[10],
                    values[2]*x + values[5]*y + values[8]*z)
        converted = [[mapped(v) for v in tri] for tri in tris]
        coords = [v for tri in converted for v in tri]
        min_z = min(v[2] for v in coords)
        dz = -min_z
        coords_x = [v[0] for v in coords]
        coords_y = [v[1] for v in coords]
        # Retain the 0.05mm existing native 3MF tolerance for preview rounding.
        if (min(coords_x) < -0.05 or max(coords_x) > bed_width + 0.05
                or min(coords_y) < -0.05 or max(coords_y) > bed_depth + 0.05):
            raise SlicerProfileError("Prusa model %d extends beyond the native build plate." % index)
        for tri in converted:
            records.append(tuple((x, y, z + dz) for x, y, z in tri))
    header = b"MakerVault Prusa single-material placed plate".ljust(80, b"\0")
    output = bytearray(header + struct.pack("<I", len(records)))
    for tri in records:
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = tri
        # Native Prusa recalculates normals, but store a conventional finite
        # face normal so this is a portable, valid binary STL.
        ux, uy, uz = bx-ax, by-ay, bz-az
        vx, vy, vz = cx-ax, cy-ay, cz-az
        nx, ny, nz = uy*vz-uz*vy, uz*vx-ux*vz, ux*vy-uy*vx
        norm = math.hypot(nx, ny, nz)
        normal = (nx/norm, ny/norm, nz/norm) if norm > 1e-12 else (0., 0., 0.)
        flat = (*normal, *tri[0], *tri[1], *tri[2])
        if any(not math.isfinite(v) or abs(v) > 1_000_000 for v in flat):
            raise SlicerProfileError("Prusa transformed geometry is not finite.")
        output.extend(struct.pack("<12fH", *flat, 0))
    if len(output) > MAX_STL_BYTES:
        raise SlicerProfileError("Prusa model plate exceeds native STL limit.")
    return bytes(output)
