"""Strictly bounded 3MF package generator for prepared multi-STL plates.

The output contains only standard core 3MF mesh/build data. It does not
propagate engine-specific settings or silently submit to a printer.
"""
import io
import math
import re
import struct
import zipfile
from xml.etree import ElementTree as ET

from .slicer_mesh import MeshInspectionError
from .slicer_profiles import SlicerProfileError

NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
MAX_TRIANGLES = 150_000
MAX_SOURCE_TOTAL = 48 * 1024 * 1024
MAX_PROJECT_BYTES = 32 * 1024 * 1024

def _triangles(raw):
    from slicer_worker.stl_validation import validate_stl, StlValidationError
    try:
        fmt = validate_stl(raw)["format"]
    except StlValidationError as exc:
        raise SlicerProfileError("Invalid source STL for build plate.") from exc
    if fmt == "binary":
        for tri in struct.iter_unpack("<12fH", raw[84:]):
            yield [tri[3:6], tri[6:9], tri[9:12]]
    else:
        current = []
        for line in raw.decode("ascii").splitlines():
            parts = line.strip().split()
            if len(parts) == 4 and parts[0].lower() == "vertex":
                current.append(tuple(float(v) for v in parts[1:]))
                if len(current) == 3:
                    yield current
                    current = []


def _render_mesh(raw, element):
    triangles = list(_triangles(raw))
    if not triangles or len(triangles) > MAX_TRIANGLES:
        raise SlicerProfileError("STL triangle count exceeds the 3MF plate limit.")
    points = [point for tri in triangles for point in tri]
    minimum = [min(p[i] for p in points) for i in range(3)]
    maximum = [max(p[i] for p in points) for i in range(3)]
    origin = ((minimum[0] + maximum[0]) / 2,
              (minimum[1] + maximum[1]) / 2,
              minimum[2])
    mesh = ET.SubElement(element, f"{{{NS}}}mesh")
    vertices = ET.SubElement(mesh, f"{{{NS}}}vertices")
    faces = ET.SubElement(mesh, f"{{{NS}}}triangles")
    # Weld identical vertices to keep generated 3MF files compact.
    indexed = {}
    for tri in triangles:
        ids = []
        for point in tri:
            centred = tuple(round(point[i] - origin[i], 6) for i in range(3))
            if centred not in indexed:
                index = len(indexed)
                indexed[centred] = index
                ET.SubElement(vertices, f"{{{NS}}}vertex", {
                    k: format(value, ".6f") for k, value in zip(("x", "y", "z"), centred)
                })
            ids.append(indexed[centred])
        ET.SubElement(faces, f"{{{NS}}}triangle",
                      {"v1": str(ids[0]), "v2": str(ids[1]), "v3": str(ids[2])})
    return len(triangles)


def _transform(item, offset_x, offset_y):
    scale = float(item["scale_percent"]) / 100
    angle = math.radians(float(item["rotation_deg"]))
    cos = scale * math.cos(angle)
    sin = scale * math.sin(angle)
    # 3MF stores a 4x3 row-vector matrix: translation is the final triple.
    values = (cos, sin, 0, -sin, cos, 0, 0, 0, scale,
              offset_x + float(item["x_mm"]), offset_y + float(item["y_mm"]), 0)
    if any(not math.isfinite(value) or abs(value) > 10000 for value in values):
        raise SlicerProfileError("Invalid 3MF object placement.")
    return " ".join(format(value, ".6f") for value in values)


def build_plate_3mf(objects_with_stl, *, bed_width, bed_depth):
    """Render [(validated_plate_item_dict, owned_STL_bytes)] as one core 3MF.

    Preview coordinates are centred around the bed. Shift all instances by the
    explicitly validated bed half-extent to place them in its positive quadrant.
    """
    if not isinstance(objects_with_stl, list) or not 1 <= len(objects_with_stl) <= 12:
        raise SlicerProfileError("A plate needs one to twelve STL models.")
    if (not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                and math.isfinite(v) and 1 <= v <= 1000
                for v in (bed_width, bed_depth))):
        raise SlicerProfileError("Verified positive build plate size is required.")
    ET.register_namespace("", NS)
    model = ET.Element(f"{{{NS}}}model", {"unit": "millimeter", "{http://www.w3.org/XML/1998/namespace}lang": "en-US"})
    resources = ET.SubElement(model, f"{{{NS}}}resources")
    build = ET.SubElement(model, f"{{{NS}}}build")
    total_bytes = 0
    total_triangles = 0
    for index, pair in enumerate(objects_with_stl, start=1):
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise SlicerProfileError("Invalid 3MF plate input.")
        item, raw = pair
        if not isinstance(item, dict) or not isinstance(raw, bytes):
            raise SlicerProfileError("Invalid STL plate entry.")
        total_bytes += len(raw)
        if total_bytes > MAX_SOURCE_TOTAL:
            raise SlicerProfileError("Total plate model size exceeds the limit.")
        obj = ET.SubElement(resources, f"{{{NS}}}object", {"id": str(index), "type": "model"})
        total_triangles += _render_mesh(raw, obj)
        if total_triangles > MAX_TRIANGLES:
            raise SlicerProfileError("Total plate triangles exceed the limit.")
        ET.SubElement(build, f"{{{NS}}}item", {
            "objectid": str(index),
            "transform": _transform(item, bed_width / 2, bed_depth / 2),
        })
    model_xml = ET.tostring(model, encoding="utf-8", xml_declaration=True)
    if len(model_xml) > 96 * 1024 * 1024:
        raise SlicerProfileError("The generated 3MF mesh is too large.")
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=False) as package:
        package.writestr("3D/3dmodel.model", model_xml)
        package.writestr("[Content_Types].xml",
                         '<?xml version="1.0" encoding="UTF-8"?>'
                         '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                         '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                         '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
                         '</Types>')
        package.writestr("_rels/.rels",
                         '<?xml version="1.0" encoding="UTF-8"?>'
                         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                         '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
                         'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
                         '</Relationships>')
    archive = output.getvalue()
    if len(archive) > MAX_PROJECT_BYTES:
        raise SlicerProfileError("Generated 3MF exceeds the worker upload limit.")
    return archive
