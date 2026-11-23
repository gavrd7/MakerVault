"""Offline BBS-family 3MF modifier fixtures; NOT production slice admission.

The root build contains only the parent model; modifier children are nested
component volumes marked `modifier_part` in model_settings.config. This
format must pass actual Orca/Creality/Bambu binary slicing before activation.
"""
import io
import math
import zipfile
from xml.etree import ElementTree as ET
from defusedxml import ElementTree as SafeET

from .slicer_modifier_volumes import validate_modifier_volumes, MAX_TOTAL_MODIFIERS
from .slicer_plate_3mf import build_plate_3mf, NS, MAX_PROJECT_BYTES
from .slicer_process_settings import PROCESS_FIELDS
from .slicer_profiles import SlicerProfileError


def _primitive_geometry(modifier):
    """Bounded closed triangle meshes with coordinates relative to modifier centre."""
    w, d, h = (modifier[key] for key in ("width_mm", "depth_mm", "height_mm"))
    shape = modifier["shape"]
    vertices, triangles = [], []

    if shape == "box":
        vertices = [
            (x, y, z) for z in (-h / 2, h / 2)
            for y in (-d / 2, d / 2) for x in (-w / 2, w / 2)
        ]
        triangles = [
            (0, 2, 1), (1, 2, 3), (4, 5, 6), (5, 7, 6),
            (0, 1, 4), (1, 5, 4), (2, 6, 3), (3, 6, 7),
            (0, 4, 2), (2, 4, 6), (1, 3, 5), (3, 7, 5),
        ]
    elif shape in {"cylinder", "disc", "cone"}:
        count = 24
        for index in range(count):
            angle = 2 * math.pi * index / count
            vertices.append((w / 2 * math.cos(angle), d / 2 * math.sin(angle), -h / 2))
        base_center = len(vertices)
        vertices.append((0.0, 0.0, -h / 2))
        if shape == "cone":
            apex = len(vertices)
            vertices.append((0.0, 0.0, h / 2))
            for index in range(count):
                nxt = (index + 1) % count
                triangles.extend(((base_center, nxt, index), (index, nxt, apex)))
        else:
            # Disc is a bounded, explicitly thick disk, not a zero-volume plane.
            top = len(vertices)
            for index in range(count):
                angle = 2 * math.pi * index / count
                vertices.append((w / 2 * math.cos(angle), d / 2 * math.sin(angle), h / 2))
            cap = len(vertices)
            vertices.append((0.0, 0.0, h / 2))
            for index in range(count):
                nxt = (index + 1) % count
                triangles.extend((
                    (base_center, nxt, index), (cap, top + index, top + nxt),
                    (index, nxt, top + nxt), (index, top + nxt, top + index),
                ))
    elif shape == "sphere":
        segments, latitudes = 24, 12
        vertices.append((0.0, 0.0, -h / 2))
        for latitude in range(1, latitudes):
            theta = -math.pi / 2 + math.pi * latitude / latitudes
            for longitude in range(segments):
                angle = 2 * math.pi * longitude / segments
                vertices.append((w / 2 * math.cos(theta) * math.cos(angle),
                                 d / 2 * math.cos(theta) * math.sin(angle),
                                 h / 2 * math.sin(theta)))
        top = len(vertices)
        vertices.append((0.0, 0.0, h / 2))
        for longitude in range(segments):
            nxt = (longitude + 1) % segments
            triangles.append((0, 1 + nxt, 1 + longitude))
            triangles.append((top, 1 + (latitudes - 2) * segments + longitude,
                              1 + (latitudes - 2) * segments + nxt))
        for latitude in range(latitudes - 2):
            lower = 1 + latitude * segments
            upper = lower + segments
            for longitude in range(segments):
                nxt = (longitude + 1) % segments
                triangles.extend((
                    (lower + longitude, lower + nxt, upper + nxt),
                    (lower + longitude, upper + nxt, upper + longitude),
                ))
    elif shape == "torus":
        rings, sides = 32, 16
        for major in range(rings):
            angle = 2 * math.pi * major / rings
            for minor in range(sides):
                phi = 2 * math.pi * minor / sides
                vertices.append((
                    (0.30 + 0.20 * math.cos(phi)) * w * math.cos(angle),
                    (0.30 + 0.20 * math.cos(phi)) * d * math.sin(angle),
                    h / 2 * math.sin(phi),
                ))
        for major in range(rings):
            for minor in range(sides):
                a = major * sides + minor
                b = major * sides + (minor + 1) % sides
                c = ((major + 1) % rings) * sides + (minor + 1) % sides
                d_index = ((major + 1) % rings) * sides + minor
                triangles.extend(((a, b, c), (a, c, d_index)))
    else:
        raise SlicerProfileError("Unknown modifier primitive.")
    return vertices, triangles


def _add_child_mesh(resources, identifier, modifier, parent_bounds):
    verts, faces = _primitive_geometry(modifier)
    centre = (
        (parent_bounds[0][0] + parent_bounds[0][1]) / 2 + modifier["x_mm"],
        (parent_bounds[1][0] + parent_bounds[1][1]) / 2 + modifier["y_mm"],
        parent_bounds[2][0] + modifier["z_mm"],
    )
    positioned = [tuple(point[i] + centre[i] for i in range(3)) for point in verts]
    if any(not math.isfinite(v) or abs(v) > 20000 for point in positioned for v in point):
        raise SlicerProfileError("Modifier geometry exceeds safe bounds.")
    # A modifier that does not overlap the parent cannot alter native toolpaths.
    if any(max(point[i] for point in positioned) <= parent_bounds[i][0] or
           min(point[i] for point in positioned) >= parent_bounds[i][1]
           for i in range(3)):
        raise SlicerProfileError("Parameter modifier does not intersect its parent model.")
    obj = ET.SubElement(resources, f"{{{NS}}}object", {"id": str(identifier), "type": "model"})
    mesh = ET.SubElement(obj, f"{{{NS}}}mesh")
    vertex_node = ET.SubElement(mesh, f"{{{NS}}}vertices")
    for point in positioned:
        ET.SubElement(vertex_node, f"{{{NS}}}vertex",
                      {axis: f"{point[i]:.6f}" for i, axis in enumerate(("x", "y", "z"))})
    triangle_node = ET.SubElement(mesh, f"{{{NS}}}triangles")
    for a, b, c in faces:
        ET.SubElement(triangle_node, f"{{{NS}}}triangle", {
            "v1": str(a), "v2": str(b), "v3": str(c),
        })
    return obj


def export_modifier_3mf_fixture(objects_with_stl, *, bed_width, bed_depth):
    """Produce native-looking nested volume fixture, never bypass runtime gates."""
    if not isinstance(objects_with_stl, list):
        raise SlicerProfileError("Invalid modifier plate.")
    count = sum(len(validate_modifier_volumes(item.get("modifier_volumes")))
                for item, _ in objects_with_stl)
    if not count or count > MAX_TOTAL_MODIFIERS:
        raise SlicerProfileError("No valid modifiers or too many modifier regions.")
    original = build_plate_3mf(objects_with_stl, bed_width=bed_width, bed_depth=bed_depth)
    with zipfile.ZipFile(io.BytesIO(original), "r") as source:
        members = {name: source.read(name) for name in source.namelist()}
    root = SafeET.fromstring(members["3D/3dmodel.model"])
    resources = root.find(f"{{{NS}}}resources")
    parent_objects = list(resources.findall(f"{{{NS}}}object"))
    manifest = (SafeET.fromstring(members["Metadata/model_settings.config"])
                if "Metadata/model_settings.config" in members else ET.Element("config"))
    if manifest.find("plate") is None:
        plate = ET.SubElement(manifest, "plate")
        ET.SubElement(plate, "metadata", {"key": "plater_id", "value": "1"})
        for index in range(1, len(objects_with_stl) + 1):
            instance = ET.SubElement(plate, "model_instance")
            for key, value in (("object_id", str(index)),
                               ("instance_id", "0"), ("identify_id", str(index))):
                ET.SubElement(instance, "metadata", {"key": key, "value": value})
    next_id = len(parent_objects) + 1
    identity = "1 0 0 0 1 0 0 0 1 0 0 0"
    identity4 = "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"
    for index, ((item, _), parent) in enumerate(zip(objects_with_stl, parent_objects), start=1):
        modifiers = validate_modifier_volumes(item.get("modifier_volumes"))
        if not modifiers:
            continue
        mesh = parent.find(f"{{{NS}}}mesh")
        if mesh is None:
            raise SlicerProfileError("Cannot attach modifier to a non-mesh parent.")
        original_points = [
            tuple(float(vertex.attrib[key]) for key in ("x", "y", "z"))
            for vertex in mesh.findall(f"{{{NS}}}vertices/{{{NS}}}vertex")
        ]
        if not original_points:
            raise SlicerProfileError("Missing base model geometry.")
        parent_bounds = tuple((min(point[i] for point in original_points),
                               max(point[i] for point in original_points))
                              for i in range(3))
        parent.remove(mesh)
        components = ET.SubElement(parent, f"{{{NS}}}components")
        base_id = next_id
        next_id += 1
        base = ET.SubElement(resources, f"{{{NS}}}object", {"id": str(base_id), "type": "model"})
        base.append(mesh)
        ET.SubElement(components, f"{{{NS}}}component", {
            "objectid": str(base_id), "transform": identity,
        })
        settings = manifest.find(f"./object[@id='{index}']")
        if settings is None:
            settings = ET.Element("object", {"id": str(index)})
            manifest.insert(0, settings)
        base_part = ET.SubElement(settings, "part", {"id": str(base_id), "subtype": "normal_part"})
        ET.SubElement(base_part, "metadata", {"key": "name", "value": "Base model"})
        ET.SubElement(base_part, "metadata", {"key": "matrix", "value": identity4})
        for number, modifier in enumerate(modifiers, start=1):
            modifier_id = next_id
            next_id += 1
            _add_child_mesh(resources, modifier_id, modifier, parent_bounds)
            ET.SubElement(components, f"{{{NS}}}component", {
                "objectid": str(modifier_id), "transform": identity,
            })
            part = ET.SubElement(settings, "part", {
                "id": str(modifier_id), "subtype": "modifier_part",
            })
            for key, value in (("name", f"{modifier['shape'].title()} modifier {number}"),
                               ("matrix", identity4)):
                ET.SubElement(part, "metadata", {"key": key, "value": value})
            for key, value in sorted(modifier["settings"].items()):
                suffix = "%" if PROCESS_FIELDS[key][2] == "%" else ""
                ET.SubElement(part, "metadata", {"key": key, "value": f"{value}{suffix}"})
    ET.register_namespace("", NS)
    members["3D/3dmodel.model"] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    members["Metadata/model_settings.config"] = ET.tostring(
        manifest, encoding="utf-8", xml_declaration=True)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=False) as result:
        for name, payload in members.items():
            result.writestr(name, payload)
    data = output.getvalue()
    if len(data) > MAX_PROJECT_BYTES:
        raise SlicerProfileError("Modifier project exceeds the worker upload limit.")
    return data
