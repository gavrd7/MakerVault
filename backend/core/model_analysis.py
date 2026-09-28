"""Geometry analysis for MakerVault STL and 3MF model assets."""

from __future__ import annotations

import json
import math
import re
import struct
import zipfile
from io import BytesIO
from pathlib import Path
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException


MAX_ANALYSIS_BYTES = 250 * 1024 * 1024
MAX_3MF_XML_BYTES = 64 * 1024 * 1024
ANALYSIS_VERSION = 3
MAX_3MF_METADATA_FILE_BYTES = 4 * 1024 * 1024
MAX_3MF_METADATA_TOTAL_BYTES = 12 * 1024 * 1024
MAX_TOPOLOGY_TRIANGLES = 500_000
OVERHANG_ANGLE_DEGREES = 45.0

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


def _length(vector):
    return math.sqrt(_dot(vector, vector))


def _normal_and_area(a, b, c):
    cross = _cross(_sub(b, a), _sub(c, a))
    magnitude = _length(cross)
    return cross, magnitude * 0.5


def _vertex_key(point):
    # STL commonly repeats nominally identical vertices. Rounding keeps the
    # topology check useful without treating sub-micron float noise as a crack.
    return tuple(round(float(value), 6) for value in point)


def _mesh_quality(triangles):
    if not triangles:
        return {
            "status": "empty",
            "watertight": False,
            "checked": True,
            "boundary_edges": 0,
            "non_manifold_edges": 0,
            "degenerate_triangles": 0,
        }
    if len(triangles) > MAX_TOPOLOGY_TRIANGLES:
        return {
            "status": "unchecked",
            "watertight": None,
            "checked": False,
            "boundary_edges": None,
            "non_manifold_edges": None,
            "degenerate_triangles": None,
            "reason": (
                f"Topology checking is skipped above "
                f"{MAX_TOPOLOGY_TRIANGLES:,} triangles to bound analysis memory use."
            ),
        }

    edges = {}
    degenerate = 0
    for a, b, c in triangles:
        _cross_value, area = _normal_and_area(a, b, c)
        if area <= 1e-10:
            degenerate += 1
            continue
        keys = (_vertex_key(a), _vertex_key(b), _vertex_key(c))
        for start, end in ((keys[0], keys[1]), (keys[1], keys[2]), (keys[2], keys[0])):
            edge = tuple(sorted((start, end)))
            edges[edge] = edges.get(edge, 0) + 1

    boundary_edges = sum(1 for count in edges.values() if count == 1)
    non_manifold_edges = sum(1 for count in edges.values() if count > 2)
    watertight = boundary_edges == 0 and non_manifold_edges == 0 and degenerate == 0
    if non_manifold_edges:
        status = "non_manifold"
    elif boundary_edges:
        status = "open"
    elif degenerate:
        status = "degenerate"
    else:
        status = "watertight"
    return {
        "status": status,
        "watertight": watertight,
        "checked": True,
        "boundary_edges": int(boundary_edges),
        "non_manifold_edges": int(non_manifold_edges),
        "degenerate_triangles": int(degenerate),
    }


_ORIENTATIONS = (
    ("z+", "Current · Z up", (0.0, 0.0, 1.0), 2, (0, 1)),
    ("z-", "Upside down · Z down", (0.0, 0.0, -1.0), 2, (0, 1)),
    ("x+", "X side · X up", (1.0, 0.0, 0.0), 0, (1, 2)),
    ("x-", "Opposite X side · X down", (-1.0, 0.0, 0.0), 0, (1, 2)),
    ("y+", "Y side · Y up", (0.0, 1.0, 0.0), 1, (0, 2)),
    ("y-", "Opposite Y side · Y down", (0.0, -1.0, 0.0), 1, (0, 2)),
)


def _orientation_analysis(triangles, mins, maxs, dimensions, surface_area, signed_volume):
    if not triangles or surface_area <= 1e-9:
        return None

    support_threshold = -math.sin(math.radians(OVERHANG_ANGLE_DEGREES))
    winding_sign = -1.0 if signed_volume < 0 else 1.0
    max_dimension = max(dimensions) or 1.0
    tolerance = max(0.02, max_dimension * 1e-5)
    candidates = []

    for key, label, up, height_axis, bed_axes in _ORIENTATIONS:
        support_area = 0.0
        contact_area = 0.0
        if up[height_axis] > 0:
            bed_plane = mins[height_axis]
        else:
            bed_plane = -maxs[height_axis]

        for a, b, c in triangles:
            normal_raw, area = _normal_and_area(a, b, c)
            if area <= 1e-10:
                continue
            normal_length = _length(normal_raw)
            normal = tuple(winding_sign * value / normal_length for value in normal_raw)
            facing = _dot(normal, up)
            if facing < support_threshold:
                support_area += area

            projections = (_dot(a, up), _dot(b, up), _dot(c, up))
            if max(abs(value - bed_plane) for value in projections) <= tolerance:
                # Projected contact area is more meaningful than sloped surface area.
                contact_area += area * abs(facing)

        support_pct = (support_area / surface_area) * 100.0
        bed_width = dimensions[bed_axes[0]]
        bed_depth = dimensions[bed_axes[1]]
        height = dimensions[height_axis]
        candidates.append({
            "key": key,
            "label": label,
            "height_mm": _round(height),
            "bed_width_mm": _round(bed_width),
            "bed_depth_mm": _round(bed_depth),
            "bed_contact_area_mm2": _round(contact_area, 2),
            "support_risk_area_mm2": _round(support_area, 2),
            "support_risk_pct": _round(support_pct, 2),
        })

    # This is deliberately an axis-aligned heuristic rather than a slicer.
    # First minimise strongly downward-facing area, then prefer more bed contact
    # and finally a shorter build height.
    ranked = sorted(
        candidates,
        key=lambda item: (
            item["support_risk_pct"],
            -item["bed_contact_area_mm2"],
            item["height_mm"],
        ),
    )
    recommended = dict(ranked[0])
    current = next(item for item in candidates if item["key"] == "z+")
    return {
        "method": "axis-aligned-45deg-overhang-estimate",
        "overhang_angle_degrees": OVERHANG_ANGLE_DEGREES,
        "recommended": recommended,
        "current": dict(current),
        "recommended_is_current": recommended["key"] == "z+",
        "candidates": candidates,
        "note": (
            "Orientation is an axis-aligned geometry estimate. A slicer remains "
            "authoritative for supports, adhesion and final print orientation."
        ),
    }


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


def _result(*, fmt, source_units, size_bytes, vertices, triangles, triangle_count, surface_area, signed_volume, object_count=1, warnings=None, encoding="", vertex_count=None):
    mins, maxs, dimensions = _bounds(vertices)
    volume = abs(signed_volume)
    mesh_quality = _mesh_quality(triangles)
    orientation = _orientation_analysis(
        triangles,
        mins,
        maxs,
        dimensions,
        surface_area,
        signed_volume,
    )
    analysis_warnings = list(warnings or [])
    if mesh_quality.get("checked"):
        if mesh_quality.get("boundary_edges"):
            analysis_warnings.append(
                f"Mesh topology contains {mesh_quality['boundary_edges']:,} boundary edge(s); "
                "support and volume estimates may be less reliable."
            )
        if mesh_quality.get("non_manifold_edges"):
            analysis_warnings.append(
                f"Mesh topology contains {mesh_quality['non_manifold_edges']:,} non-manifold edge(s)."
            )
        if mesh_quality.get("degenerate_triangles"):
            analysis_warnings.append(
                f"Mesh contains {mesh_quality['degenerate_triangles']:,} degenerate triangle(s)."
            )
    elif mesh_quality.get("reason"):
        analysis_warnings.append(mesh_quality["reason"])

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
        "mesh_quality": mesh_quality,
        "orientation": orientation,
        "warnings": analysis_warnings + [
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
    triangles = []
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
        triangles.append((a, b, c))
        area, volume = _triangle_metrics(a, b, c)
        area_total += area
        volume_total += volume
        offset += 50

    return _result(
        fmt="stl",
        source_units="unitless-assumed-mm",
        size_bytes=len(data),
        vertices=vertices,
        triangles=triangles,
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
    triangles = []
    area_total = 0.0
    volume_total = 0.0
    for match in matches:
        vertices.append(tuple(float(match.group(i)) for i in (1, 2, 3)))

    for index in range(0, len(vertices), 3):
        a, b, c = vertices[index:index + 3]
        triangles.append((a, b, c))
        area, volume = _triangle_metrics(a, b, c)
        area_total += area
        volume_total += volume

    return _result(
        fmt="stl",
        source_units="unitless-assumed-mm",
        size_bytes=len(data),
        vertices=vertices,
        triangles=triangles,
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


def _normalise_meta_key(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _flatten_metadata(value, *, prefix="", out=None, limit=800):
    if out is None:
        out = {}
    if len(out) >= limit:
        return out
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            _flatten_metadata(item, prefix=child, out=out, limit=limit)
            if len(out) >= limit:
                break
    elif isinstance(value, list):
        if all(not isinstance(item, (dict, list)) for item in value):
            out[prefix] = value
        else:
            for index, item in enumerate(value[:50]):
                _flatten_metadata(item, prefix=f"{prefix}.{index}", out=out, limit=limit)
                if len(out) >= limit:
                    break
    elif prefix:
        out[prefix] = value
    return out


def _parse_metadata_text(raw):
    text = raw.decode("utf-8", errors="replace").lstrip("\ufeff").strip()
    if not text:
        return {}
    if text[:1] in {"{", "["}:
        try:
            return _flatten_metadata(json.loads(text))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    if text.startswith("<"):
        try:
            root = ET.fromstring(text)
            parsed = {}
            for element in root.iter():
                key = (
                    element.attrib.get("key")
                    or element.attrib.get("name")
                    or element.attrib.get("id")
                )
                value = element.attrib.get("value")
                if value is None and element.text and element.text.strip():
                    value = element.text.strip()
                if key and value not in (None, ""):
                    parsed[str(key)] = value
            if parsed:
                return parsed
        except (ET.ParseError, DefusedXmlException):
            pass

    parsed = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";", "//", "[")):
            continue
        separator = "=" if "=" in line else ":" if ":" in line else None
        if not separator:
            continue
        key, value = line.split(separator, 1)
        key = key.strip()
        value = value.strip().strip('"')
        if key and value:
            parsed[key] = value
    return parsed


def _metadata_lookup(flat, *aliases):
    normalised_aliases = {_normalise_meta_key(alias) for alias in aliases}
    for key, value in flat.items():
        key_text = str(key)
        candidates = {
            _normalise_meta_key(key_text),
            _normalise_meta_key(key_text.split(".")[-1]),
            _normalise_meta_key(key_text.split(":")[-1]),
        }
        if candidates & normalised_aliases and value not in (None, "", []):
            return value
    return None


def _coerce_metadata_number(value):
    if isinstance(value, list):
        value = next((item for item in value if item not in (None, "")), None)
    if value in (None, ""):
        return None
    match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", str(value))
    if not match:
        return None
    try:
        return _round(float(match.group(0)))
    except ValueError:
        return None


def _coerce_metadata_bool(value):
    if isinstance(value, list):
        value = next((item for item in value if item not in (None, "")), None)
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled", "none"}:
        return False
    return None


def _metadata_display(value):
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    if value in (None, ""):
        return None
    return str(value)


def _detect_slicer_application(core_metadata, flat):
    values = [str(value) for value in core_metadata.values()]
    values.extend(str(value) for value in flat.values() if not isinstance(value, (dict, list)))
    haystack = " ".join(values).lower()
    if "orcaslicer" in haystack or "orca slicer" in haystack:
        return "OrcaSlicer"
    if "bambustudio" in haystack or "bambu studio" in haystack:
        return "Bambu Studio"
    if "prusaslicer" in haystack or "prusa slicer" in haystack:
        return "PrusaSlicer"
    if "slic3r" in haystack:
        return "Slic3r"
    if "cura" in haystack:
        return "Cura"
    app = (
        core_metadata.get("Application")
        or core_metadata.get("application")
        or _metadata_lookup(flat, "application", "generator")
    )
    return str(app).strip() if app else ""


def _extract_3mf_slicer_metadata(package, model_roots):
    core_metadata = {}
    for root in model_roots:
        for element in root.iter():
            if _local_name(element.tag) != "metadata":
                continue
            name = str(element.attrib.get("name") or "").strip()
            value = (element.text or "").strip()
            if name and value and name not in core_metadata:
                core_metadata[name] = value

    flat = {}
    metadata_files = []
    total_bytes = 0
    for info in package.infolist():
        lower_name = info.filename.lower()
        suffix = Path(lower_name).suffix
        interesting = (
            lower_name.startswith("metadata/")
            or "slic3r" in lower_name
            or "prusaslicer" in lower_name
            or "orcaslicer" in lower_name
            or "bambu" in lower_name
        )
        if not interesting or suffix not in {".config", ".ini", ".json", ".txt", ".xml"}:
            continue
        if info.file_size <= 0 or info.file_size > MAX_3MF_METADATA_FILE_BYTES:
            continue
        if total_bytes + info.file_size > MAX_3MF_METADATA_TOTAL_BYTES:
            break
        try:
            parsed = _parse_metadata_text(package.read(info))
        except (KeyError, RuntimeError, ValueError):
            continue
        if not parsed:
            continue
        total_bytes += info.file_size
        metadata_files.append(info.filename)
        for key, value in parsed.items():
            flat.setdefault(f"{info.filename}:{key}", value)

    for key, value in core_metadata.items():
        flat.setdefault(f"3mf:{key}", value)

    application = _detect_slicer_application(core_metadata, flat)
    printer_profile = _metadata_display(_metadata_lookup(
        flat, "printer_settings_id", "printer_profile", "printer_model", "machine_name"
    ))
    print_profile = _metadata_display(_metadata_lookup(
        flat, "print_settings_id", "process_settings_id", "process_profile", "print_profile"
    ))
    filament_profile = _metadata_display(_metadata_lookup(
        flat, "filament_settings_id", "filament_profile", "filament_type", "filament_types"
    ))

    settings = {
        "layer_height_mm": _coerce_metadata_number(_metadata_lookup(flat, "layer_height")),
        "first_layer_height_mm": _coerce_metadata_number(_metadata_lookup(
            flat, "initial_layer_print_height", "first_layer_height", "initial_layer_height"
        )),
        "nozzle_diameter_mm": _coerce_metadata_number(_metadata_lookup(flat, "nozzle_diameter")),
        "infill_density": _metadata_display(_metadata_lookup(
            flat, "sparse_infill_density", "fill_density", "infill_density"
        )),
        "infill_pattern": _metadata_display(_metadata_lookup(
            flat, "sparse_infill_pattern", "fill_pattern", "infill_pattern"
        )),
        "perimeters": _coerce_metadata_number(_metadata_lookup(flat, "wall_loops", "perimeters")),
        "top_layers": _coerce_metadata_number(_metadata_lookup(flat, "top_shell_layers", "top_solid_layers")),
        "bottom_layers": _coerce_metadata_number(_metadata_lookup(flat, "bottom_shell_layers", "bottom_solid_layers")),
        "supports_enabled": _coerce_metadata_bool(_metadata_lookup(
            flat, "enable_support", "support_material", "support_enable"
        )),
        "brim_type": _metadata_display(_metadata_lookup(flat, "brim_type")),
        "brim_width_mm": _coerce_metadata_number(_metadata_lookup(flat, "brim_width")),
    }
    settings = {key: value for key, value in settings.items() if value is not None}

    detected = bool(application or printer_profile or print_profile or filament_profile or settings or metadata_files)
    return {
        "detected": detected,
        "application": application,
        "profiles": {
            "printer": printer_profile,
            "print": print_profile,
            "filament": filament_profile,
        },
        "settings": settings,
        "metadata_files": metadata_files,
        "metadata_items": len(flat),
        "note": (
            "Slicer settings are read from metadata stored inside the 3MF package. "
            "MakerVault does not run a slicer and does not treat these values as authoritative "
            "unless the source 3MF was saved by a compatible slicer."
        ),
    }


def analyse_3mf(data):
    try:
        package = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ModelAnalysisError("The 3MF package is not a valid ZIP container.") from exc

    model_files = [info for info in package.infolist() if info.filename.lower().endswith(".model")]
    if not model_files:
        raise ModelAnalysisError("The 3MF package does not contain a .model geometry document.")
    total_model_bytes = sum(info.file_size for info in model_files)
    if total_model_bytes > MAX_3MF_XML_BYTES:
        raise ModelAnalysisError(
            f"3MF geometry expands beyond the {MAX_3MF_XML_BYTES // 1024 // 1024} MB analysis safety limit."
        )

    all_vertices = []
    all_triangles = []
    triangle_count = 0
    object_count = 0
    area_total = 0.0
    volume_total = 0.0
    source_units = set()
    model_roots = []
    has_components = False
    has_build_transforms = False

    for model_info in model_files:
        model_name = model_info.filename
        try:
            root = ET.fromstring(package.read(model_info))
        except (ET.ParseError, DefusedXmlException, KeyError) as exc:
            raise ModelAnalysisError(f"Could not parse 3MF geometry document {model_name}.") from exc

        model_roots.append(root)
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
                all_triangles.append((a, b, c))
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

    slicer_metadata = _extract_3mf_slicer_metadata(package, model_roots)
    package.close()

    result = _result(
        fmt="3mf",
        source_units=", ".join(sorted(source_units)) or "millimeter",
        size_bytes=len(data),
        vertices=all_vertices,
        triangles=all_triangles,
        triangle_count=triangle_count,
        surface_area=area_total,
        signed_volume=volume_total,
        object_count=object_count,
        encoding="zip/xml",
        warnings=warnings,
    )
    result["slicer_metadata"] = slicer_metadata
    return result


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
