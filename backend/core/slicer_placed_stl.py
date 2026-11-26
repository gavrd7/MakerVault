"""Engine-independent placement-baked STL preparation for native CLI adapters.

Only applies to plain single-material plates; native annotations and modifiers
stay on the validated project routes. Prusa integration is intentionally separate.
"""
import hashlib
import math
import struct
from .slicer_plate_3mf import _triangles, _transform
from .slicer_mesh import inspect_stl, MeshInspectionError
from .slicer_profiles import SlicerProfileError
from .slicer_resource_budget import (plate_triangle_budget, input_model_budget, source_input_budget)

def build_placed_stl(objects_with_stl, *, bed_width, bed_depth, _parallel=True):
    """Bake independently transformed source meshes into a bounded native STL.

    Visual coordinates are centred on the bed; individual source meshes use
    the same XY-midpoint and Z-bottom pivot as MakerVault's 3MF preview.
    We stream facets instead of retaining hundreds of thousands of triangles
    and transformed copies in Django memory.
    """
    if not isinstance(objects_with_stl, list) or not 1 <= len(objects_with_stl) <= 200:
        raise SlicerProfileError("native plate needs one to 200 verified source STLs.")
    if not all(isinstance(n, (float, int)) and not isinstance(n, bool)
               and math.isfinite(n) and 1 <= n <= 1000 for n in (bed_width, bed_depth)):
        raise SlicerProfileError("native plate requires verified native build dimensions.")
    if _parallel and len(objects_with_stl) > 1:
        from .slicer_parallel_geometry import prepared_mesh_batches
        # Validate aggregate source and output budgets before spawning children.
        sources = []
        seen = {}
        total_faces = 0
        for index, pair in enumerate(objects_with_stl):
            if (not isinstance(pair, tuple) or len(pair) != 2
                    or not isinstance(pair[0], dict) or not isinstance(pair[1], bytes)):
                raise SlicerProfileError("Invalid native plate source.")
            item, raw = pair
            identity = (len(raw), hashlib.sha256(raw).digest())
            if identity not in seen:
                try:
                    seen[identity] = inspect_stl(raw)["triangles"]
                except MeshInspectionError as exc:
                    raise SlicerProfileError("native plate contains an invalid STL.") from exc
            total_faces += seen[identity]
            sources.append((index, raw, {"item": item, "bed_width": bed_width,
                                         "bed_depth": bed_depth}))
        if (sum(identity[0] for identity in seen) >
                source_input_budget(upper_cap=input_model_budget()) or
                total_faces > plate_triangle_budget() or
                84 + 50 * total_faces > input_model_budget()):
            raise SlicerProfileError("native plate geometry exceeds the native STL limit.")
        estimate = 128 * 1024**2 + max(len(raw) for _, raw, _ in sources) * 16
        with prepared_mesh_batches(sources, estimated_bytes_per_worker=estimate,
                                   mode="stl") as prepared:
            first = next(prepared)
            if first[2] is not None:
                from itertools import chain
                merged = bytearray(first[2][:84])
                for index, raw, data in chain((first,), prepared):
                    expected = seen[(len(raw), hashlib.sha256(raw).digest())]
                    if (data is None or len(data) != 84 + 50 * expected
                            or struct.unpack_from("<I", data, 80)[0] != expected):
                        raise SlicerProfileError("Invalid parallel placed STL output.")
                    merged.extend(memoryview(data)[84:])
                struct.pack_into("<I", merged, 80, total_faces)
                return bytes(merged)
        # Single-core fallback retains the efficient per-source pivot cache.
    output = bytearray(b"MakerVault native single-material placed plate".ljust(80, b"\0")
                       + b"\0" * 4)
    count = 0
    source_bytes = 0
    seen_source = set()
    source_geometry = {}
    source_limit = source_input_budget(upper_cap=input_model_budget())
    facet_limit = plate_triangle_budget()
    byte_limit = input_model_budget()
    for index, pair in enumerate(objects_with_stl, 1):
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise SlicerProfileError("Invalid native plate source.")
        item, raw = pair
        if not isinstance(item, dict) or not isinstance(raw, bytes):
            raise SlicerProfileError("Invalid native plate source.")
        identity = (len(raw), hashlib.sha256(raw).digest())
        if identity not in seen_source:
            source_bytes += len(raw)
            seen_source.add(identity)
        if source_bytes > source_limit:
            raise SlicerProfileError("native plate source bytes exceed the safe limit.")
        if (item.get("modifier_volumes") or item.get("process_overrides")
                or (item.get("colour_paint") or {}).get("regions")
                or (item.get("colour_paint") or {}).get("faces")
                or (item.get("support_paint") or {}).get("regions")
                or (item.get("seam_paint") or {}).get("regions")
                or (item.get("fuzzy_skin_paint") or {}).get("regions")
                or (item.get("variable_layer_profile") or {}).get("bands")):
            raise SlicerProfileError("Unsupported native object settings cannot be discarded.")
        if identity not in source_geometry:
            try:
                inspected = inspect_stl(raw)
                expected_faces = inspected["triangles"]
            except MeshInspectionError as exc:
                raise SlicerProfileError("native plate contains an invalid STL.") from exc
            # Exact source bounds are needed: the inspection summary rounds to
            # three decimal places, whereas preview pivots are calculated from
            # the actual source vertices.
            minimum = [float("inf")] * 3
            maximum = [float("-inf")] * 3
            seen = 0
            for triangle in _triangles(raw, inspected_format=inspected["format"]):
                seen += 1
                for point in triangle:
                    for axis in range(3):
                        value = float(point[axis])
                        if not math.isfinite(value) or abs(value) > 1_000_000:
                            raise SlicerProfileError("native source coordinates are unsafe.")
                        minimum[axis] = min(minimum[axis], value)
                        maximum[axis] = max(maximum[axis], value)
            if seen != expected_faces:
                raise SlicerProfileError("native input STL triangle count changed.")
            pivot = ((minimum[0] + maximum[0]) / 2,
                     (minimum[1] + maximum[1]) / 2, minimum[2])
            source_geometry[identity] = (inspected, expected_faces, pivot)
        inspected, expected_faces, pivot = source_geometry[identity]
        if count + expected_faces > facet_limit or 84 + 50 * (count + expected_faces) > byte_limit:
            raise SlicerProfileError("native plate geometry exceeds the native STL limit.")
        try:
            matrix = [float(v) for v in _transform(item, bed_width / 2, bed_depth / 2).split()]
        except (ValueError, TypeError, KeyError) as exc:
            raise SlicerProfileError("native object placement is invalid.") from exc
        if len(matrix) != 12 or any(not math.isfinite(v) for v in matrix):
            raise SlicerProfileError("Invalid native object transform.")
        if float(item.get("z_mm", 0)) != 0:
            raise SlicerProfileError("native elevated or stacked objects are not yet approved.")

        def mapped(point):
            x, y, z = (float(point[i]) - pivot[i] for i in range(3))
            return (matrix[0]*x + matrix[3]*y + matrix[6]*z + matrix[9],
                    matrix[1]*x + matrix[4]*y + matrix[7]*z + matrix[10],
                    matrix[2]*x + matrix[5]*y + matrix[8]*z)

        lower = [float("inf")] * 3
        upper = [float("-inf")] * 3
        for triangle in _triangles(raw, inspected_format=inspected["format"]):
            for point in triangle:
                coords = mapped(point)
                for axis in range(3):
                    lower[axis] = min(lower[axis], coords[axis])
                    upper[axis] = max(upper[axis], coords[axis])
        if (not all(math.isfinite(v) for v in lower + upper) or
                lower[0] < -0.05 or upper[0] > bed_width + 0.05 or
                lower[1] < -0.05 or upper[1] > bed_depth + 0.05):
            raise SlicerProfileError(
                "native model %d extends beyond the native build plate." % index)
        dz = -lower[2]
        for triangle in _triangles(raw, inspected_format=inspected["format"]):
            coords = [(x, y, z + dz) for x, y, z in (mapped(point) for point in triangle)]
            (ax, ay, az), (bx, by, bz), (cx, cy, cz) = coords
            ux, uy, uz = bx-ax, by-ay, bz-az
            vx, vy, vz = cx-ax, cy-ay, cz-az
            nx, ny, nz = uy*vz-uz*vy, uz*vx-ux*vz, ux*vy-uy*vx
            norm = math.hypot(nx, ny, nz)
            normal = (nx/norm, ny/norm, nz/norm) if norm > 1e-12 else (0., 0., 0.)
            flat = (*normal, *coords[0], *coords[1], *coords[2])
            if any(not math.isfinite(v) or abs(v) > 1_000_000 for v in flat):
                raise SlicerProfileError("native transformed geometry is not finite.")
            output.extend(struct.pack("<12fH", *flat, 0))
            count += 1
    if not 0 < count <= facet_limit or len(output) > byte_limit:
        raise SlicerProfileError("native model plate exceeds native STL limit.")
    struct.pack_into("<I", output, 80, count)
    return bytes(output)
