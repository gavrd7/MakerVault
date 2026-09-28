"""Geometry analysis for MakerVault STL and 3MF model assets."""

from __future__ import annotations

import math
import re
import struct
import zipfile
from io import BytesIO
from pathlib import Path
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException


MAX_ANALYSIS_BYTES = 250 * 1024 * 1024
ANALYSIS_VERSION = 1

_UNIT_TO_MM = {
    "micron": 0.001,
    "millimeter": 1.0,
    "centimeter": 10.0,
    "inch": 25.4,
    "foot": 304.8,
    "meter": 1000.0,
}

_VERTEX_RE = re.compile(
    rb"\bvertex\s+"
    rb"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s+"
    rb"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s+"
    rb"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)",
    re.IGNORECASE,
)


class ModelAnalysisError(RuntimeError):
    pass


def _round(value, places=3):
    if value is None:
        return None
    return round(float(value), places)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _triangle_metrics(a, b, c):
    cross = _cross(_sub(b, a), _sub(c, a))
    area = 0.5 * math.sqrt(_dot(cross, cross))
    signed_volume = _dot(a, _cross(b, c)) / 6.0
    return area, signed_volume


def _bounds(points):
    if not points:
        raise ModelAnalysisError("The model does not contain any readable vertices.")
    mins = [float("inf"), float("inf"), float("inf")]
    maxs = [float("-inf"), float("-inf"), float("-inf")]
    for point in points:
        for axis in range(3):
            mins[axis] = min(mins[axis], point[axis])
            maxs[axis] = max(maxs[axis], point[axis])
    dimensions = [maxs[i] - mins[i] for i in range(3)]
    return mins, maxs, dimensions


def _complexity(triangles):
    if triangles < 100_000:
        return "low"
    if triangles < 500_000:
        return "medium"
    return "high"


def _result(*, fmt, source_units, size_bytes, vertices, triangle_count, surface_area, signed_volume, object_count=1, warnings=None, encoding="", vertex_count=None):
    mins, maxs, dimensions = _bounds(vertices)
    volume = abs(signed_volume)
    return {
        "analysis_version": ANALYSIS_VERSION,
        "format": fmt,
        "encoding": encoding,
        "units": "mm",
        "source_units": source_units,
        "size_bytes": int(size_bytes),
        "vertex_count": int(vertex_count if vertex_count is not None else len(vertices)),
        "triangle_count": int(triangle_count),
        "object_count": int(object_count),
        "complexity": _complexity(int(triangle_count)),
        "dimensions_mm": {
            "x": _round(dimensions[0]),
            "y": _round(dimensions[1]),
            "z": _round(dimensions[2]),
        },
        "bounds_mm": {
            "min": {"x": _round(mins[0]), "y": _round(mins[1]), "z": _round(mins[2])},
            "max": {"x": _round(maxs[0]), "y": _round(maxs[1]), "z": _round(maxs[2])},
        },
        "surface_area_mm2": _round(surface_area, 2),
        "volume_mm3": _round(volume, 2) if volume > 1e-9 else None,
        "volume_cm3": _round(volume / 1000.0, 3) if volume > 1e-9 else None,
        "warnings": list(warnings or []) + [
            "Volume is an approximate mesh calculation and is most meaningful for closed, consistently oriented geometry."
        ],
    }


def _analyse_binary_stl(data):
    if len(data) < 84:
        raise ModelAnalysisError("The STL file is too short to contain binary geometry.")
    triangle_count = struct.unpack_from("<I", data, 80)[0]
    expected = 84 + triangle_count * 50
    if expected > len(data):
        raise ModelAnalysisError("The binary STL triangle table is truncated.")

    vertices = []
    area_total = 0.0
    volume_total = 0.0
    offset = 84
    for _ in range(triangle_count):
        # 12 floats: normal then three XYZ vertices; final uint16 is attributes.
        record = struct.unpack_from("<12fH", data, offset)
        a = (record[3], record[4], record[5])
        b = (record[6], record[7], record[8])
        c = (record[9], record[10], record[11])
        vertices.extend((a, b, c))
        area, volume = _triangle_metrics(a, b, c)
        area_total += area
        volume_total += volume
        offset += 50

    return _result(
        fmt="stl",
        source_units="unitless-assumed-mm",
        size_bytes=len(data),
        vertices=vertices,
        triangle_count=triangle_count,
        surface_area=area_total,
        signed_volume=volume_total,
        encoding="binary",
        vertex_count=len(set(vertices)),
        warnings=[
            "STL does not store physical units; MakerVault assumes millimetres.",
        ],
    )


def _analyse_ascii_stl(data):
    matches = list(_VERTEX_RE.finditer(data))
    if len(matches) < 3 or len(matches) % 3:
        raise ModelAnalysisError("MakerVault could not read complete ASCII STL triangles.")

    vertices = []
    area_total = 0.0
    volume_total = 0.0
    for match in matches:
        vertices.append(tuple(float(match.group(i)) for i in (1, 2, 3)))

    for index in range(0, len(vertices), 3):
        a, b, c = vertices[index:index + 3]
        area, volume = _triangle_metrics(a, b, c)
        area_total += area
        volume_total += volume

    return _result(
        fmt="stl",
        source_units="unitless-assumed-mm",
        size_bytes=len(data),
        vertices=vertices,
        triangle_count=len(vertices) // 3,
        surface_area=area_total,
        signed_volume=volume_total,
        encoding="ascii",
        vertex_count=len(set(vertices)),
        warnings=[
            "STL does not store physical units; MakerVault assumes millimetres.",
        ],
    )


def analyse_stl(data):
    # Binary STL length is deterministic and is more reliable than checking
    # whether the header happens to begin with the word 'solid'.
    if len(data) >= 84:
        triangle_count = struct.unpack_from("<I", data, 80)[0]
        expected = 84 + triangle_count * 50
        if triangle_count > 0 and expected <= len(data):
            return _analyse_binary_stl(data)
    return _analyse_ascii_stl(data)


def _local_name(tag):
    return tag.rsplit("}", 1)[-1]


def analyse_3mf(data):
    try:
        package = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ModelAnalysisError("The 3MF package is not a valid ZIP container.") from exc

    model_files = [name for name in package.namelist() if name.lower().endswith(".model")]
    if not model_files:
        raise ModelAnalysisError("The 3MF package does not contain a .model geometry document.")

    all_vertices = []
    triangle_count = 0
    object_count = 0
    area_total = 0.0
    volume_total = 0.0
    source_units = set()
    has_components = False
    has_build_transforms = False

    for model_name in model_files:
        try:
            root = ET.fromstring(package.read(model_name))
        except (ET.ParseError, DefusedXmlException, KeyError) as exc:
            raise ModelAnalysisError(f"Could not parse 3MF geometry document {model_name}.") from exc

        unit = str(root.attrib.get("unit") or "millimeter").lower()
        scale = _UNIT_TO_MM.get(unit)
        if scale is None:
            scale = 1.0
        source_units.add(unit)

        for element in root.iter():
            name = _local_name(element.tag)
            if name == "component":
                has_components = True
            elif name == "item" and element.attrib.get("transform"):
                has_build_transforms = True

        for obj in (element for element in root.iter() if _local_name(element.tag) == "object"):
            mesh = next((child for child in obj if _local_name(child.tag) == "mesh"), None)
            if mesh is None:
                continue
            vertices_element = next((child for child in mesh if _local_name(child.tag) == "vertices"), None)
            triangles_element = next((child for child in mesh if _local_name(child.tag) == "triangles"), None)
            if vertices_element is None:
                continue

            local_vertices = []
            for vertex in vertices_element:
                if _local_name(vertex.tag) != "vertex":
                    continue
                try:
                    point = (
                        float(vertex.attrib["x"]) * scale,
                        float(vertex.attrib["y"]) * scale,
                        float(vertex.attrib["z"]) * scale,
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                local_vertices.append(point)
                all_vertices.append(point)

            object_count += 1
            if triangles_element is None:
                continue
            for triangle in triangles_element:
                if _local_name(triangle.tag) != "triangle":
                    continue
                try:
                    indices = [int(triangle.attrib[key]) for key in ("v1", "v2", "v3")]
                    a, b, c = (local_vertices[index] for index in indices)
                except (KeyError, IndexError, TypeError, ValueError):
                    continue
                area, volume = _triangle_metrics(a, b, c)
                area_total += area
                volume_total += volume
                triangle_count += 1

    warnings = []
    if len(source_units) > 1:
        warnings.append("The 3MF package contains geometry documents with different source units.")
    if has_components:
        warnings.append("3MF component assemblies were detected; component transforms are not yet applied to geometry statistics.")
    if has_build_transforms:
        warnings.append("3MF build-item transforms were detected; build placement transforms are not yet applied to geometry statistics.")

    return _result(
        fmt="3mf",
        source_units=", ".join(sorted(source_units)) or "millimeter",
        size_bytes=len(data),
        vertices=all_vertices,
        triangle_count=triangle_count,
        surface_area=area_total,
        signed_volume=volume_total,
        object_count=object_count,
        encoding="zip/xml",
        warnings=warnings,
    )


def _asset_filename(asset):
    metadata = asset.metadata or {}
    return (
        str(metadata.get("original_name") or "").strip()
        or (Path(asset.file.name).name if asset.file else "")
        or asset.name
    )


def analyse_file_asset(asset):
    if not asset.file:
        raise ModelAnalysisError("The selected MakerVault file has no stored file content.")

    filename = _asset_filename(asset)
    extension = Path(filename).suffix.lower()
    if extension not in {".stl", ".3mf"}:
        raise ModelAnalysisError("Model intelligence currently supports STL and 3MF geometry.")

    try:
        size = int(asset.file.size)
    except (OSError, ValueError, TypeError):
        size = 0
    if size and size > MAX_ANALYSIS_BYTES:
        raise ModelAnalysisError(
            f"Model analysis is limited to {MAX_ANALYSIS_BYTES // 1024 // 1024} MB per file in this development build."
        )

    try:
        asset.file.open("rb")
        data = asset.file.read(MAX_ANALYSIS_BYTES + 1)
    except (OSError, ValueError) as exc:
        raise ModelAnalysisError("MakerVault could not read the stored model file.") from exc
    finally:
        try:
            asset.file.close()
        except (OSError, ValueError):
            pass

    if len(data) > MAX_ANALYSIS_BYTES:
        raise ModelAnalysisError(
            f"Model analysis is limited to {MAX_ANALYSIS_BYTES // 1024 // 1024} MB per file in this development build."
        )

    analysis = analyse_stl(data) if extension == ".stl" else analyse_3mf(data)
    analysis.update({
        "filename": filename,
        "source_asset_id": str(asset.id),
        "source_sha256": asset.sha256 or "",
    })
    return analysis
