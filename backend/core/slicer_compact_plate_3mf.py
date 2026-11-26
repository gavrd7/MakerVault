"""Compact Orca single-material 3MF for repeated instances of one verified STL.

A 3MF component object references one mesh resource for each separately placed
instance. This avoids Python/XML expansion proportional to instance count.
Only the ordinary, unpainted single-material Orca route may use this producer.
"""
import io
import math
import zipfile
from xml.etree import ElementTree as ET
from defusedxml import ElementTree as SafeET

from .slicer_profiles import SlicerProfileError
from .slicer_plate_3mf import NS, _transform, build_plate_3mf


def compact_repeated_plate(objects_with_stl, *, bed_width, bed_depth):
    if (not isinstance(objects_with_stl, list)
            or not 2 <= len(objects_with_stl) <= 200):
        return None
    first = objects_with_stl[0]
    if not isinstance(first, tuple) or len(first) != 2 or not isinstance(first[1], bytes):
        return None
    raw = first[1]
    if any(not isinstance(row, tuple) or len(row) != 2
           or not isinstance(row[0], dict) or row[1] != raw
           for row in objects_with_stl):
        return None
    # Individual object settings require their own resource identity.
    for item, _raw in objects_with_stl:
        if any(item.get(key) for key in (
                "modifier_volumes", "process_overrides", "colour_paint",
                "support_paint", "seam_paint", "fuzzy_skin_paint",
                "variable_layer_profile")):
            return None
    # Single-source rendering retains the already-reviewed STL parser, welded
    # vertices, dimensions and bounded source geometry validation.
    source = build_plate_3mf([first], bed_width=bed_width, bed_depth=bed_depth)
    with zipfile.ZipFile(io.BytesIO(source)) as archive:
        root = SafeET.fromstring(archive.read("3D/3dmodel.model"))
        content_types = archive.read("[Content_Types].xml")
        relationships = archive.read("_rels/.rels")
    q = "{" + NS + "}"
    mesh_object = root.find("./" + q + "resources/" + q + "object")
    if mesh_object is None:
        raise SlicerProfileError("Missing verified compact mesh resource.")
    vertices = mesh_object.findall("./" + q + "mesh/" + q + "vertices/" + q + "vertex")
    if not vertices:
        raise SlicerProfileError("Empty verified compact mesh resource.")
    positions = [tuple(float(vertex.attrib[axis]) for axis in ("x", "y", "z"))
                 for vertex in vertices]
    ET.register_namespace("", NS)
    out = ET.Element(q + "model", {
        "unit": "millimeter", "{http://www.w3.org/XML/1998/namespace}lang": "en-US"
    })
    resources = ET.SubElement(out, q + "resources")
    resources.append(mesh_object)
    compound = ET.SubElement(resources, q + "object", {"id": "2", "type": "model"})
    components = ET.SubElement(compound, q + "components")
    for index, (item, _raw) in enumerate(objects_with_stl, start=1):
        matrix = [float(v) for v in _transform(item, bed_width / 2, bed_depth / 2).split()]
        placed = [
            (matrix[0]*x + matrix[3]*y + matrix[6]*z + matrix[9],
             matrix[1]*x + matrix[4]*y + matrix[7]*z + matrix[10],
             matrix[2]*x + matrix[5]*y + matrix[8]*z)
            for x, y, z in positions
        ]
        minimum = [min(point[axis] for point in placed) for axis in range(3)]
        maximum = [max(point[axis] for point in placed) for axis in range(3)]
        if (not all(math.isfinite(n) for n in minimum + maximum)
                or minimum[0] < -0.05 or maximum[0] > bed_width + 0.05
                or minimum[1] < -0.05 or maximum[1] > bed_depth + 0.05):
            raise SlicerProfileError("Repeated model %d extends beyond the build plate." % index)
        z = float(item.get("z_mm", 0))
        if not math.isfinite(z) or not 0 <= z <= 1000:
            raise SlicerProfileError("Invalid repeated model elevation.")
        matrix[11] = z - minimum[2]
        ET.SubElement(components, q + "component", {
            "objectid": "1",
            "transform": " ".join(format(v, ".6f") for v in matrix),
        })
    build = ET.SubElement(out, q + "build")
    ET.SubElement(build, q + "item", {
        "objectid": "2", "transform": "1 0 0 0 1 0 0 0 1 0 0 0"
    })
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=False) as archive:
        archive.writestr("3D/3dmodel.model", ET.tostring(
            out, encoding="utf-8", xml_declaration=True))
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", relationships)
    data = result.getvalue()
    if len(data) > 32 * 1024 * 1024:
        raise SlicerProfileError("Compact 3MF transfer exceeds the worker input budget.")
    return data
