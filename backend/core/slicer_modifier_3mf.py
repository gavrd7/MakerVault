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
from .slicer_plate_3mf import build_plate_3mf, _transform, _triangles, NS
from .slicer_resource_budget import project_archive_budget
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


def _modifier_parent_transform(item, raw, bed_width, bed_depth):
    """Match native STL centring and THREE's XYZ rotation/XYZ scaling/Z bed lift.

    The normal plate builder bakes the fully posed parent mesh. Do not place
    modifiers from its world-axis bounding-box centre: that loses rotation,
    tilt, non-uniform scaling and the lowest-vertex bed adjustment.
    """
    low = [math.inf] * 3
    high = [-math.inf] * 3
    for tri in _triangles(raw):
        for point in tri:
            for axis in range(3):
                low[axis] = min(low[axis], point[axis])
                high[axis] = max(high[axis], point[axis])
    if any(not math.isfinite(value) for value in low + high):
        raise SlicerProfileError("Modifier parent has invalid source geometry.")
    origin = ((low[0] + high[0]) / 2, (low[1] + high[1]) / 2, low[2])
    matrix = tuple(float(v) for v in _transform(
        item, bed_width / 2, bed_depth / 2).split())
    lowest_rotated = math.inf
    for tri in _triangles(raw):
        for point in tri:
            local = tuple(point[i] - origin[i] for i in range(3))
            rotated_z = sum(matrix[2 + 3 * i] * local[i] for i in range(3))
            lowest_rotated = min(lowest_rotated, rotated_z)
    if not math.isfinite(lowest_rotated):
        raise SlicerProfileError("Modifier parent transform is invalid.")
    return matrix, float(item.get("z_mm", 0)) - lowest_rotated


def _add_child_mesh(resources, identifier, modifier, parent_bounds, matrix, bed_z, bed_width, bed_depth):
    verts, faces = _primitive_geometry(modifier)
    centre = (modifier["x_mm"], modifier["y_mm"], modifier["z_mm"])
    positioned = []
    if modifier.get("coordinate_space") == "world":
        # An independent modifier is positioned in plate space and must not
        # inherit the associated model's movement, rotation or scale.
        own_pose = {
            "x_mm": centre[0], "y_mm": centre[1], "z_mm": centre[2],
            "rotation_deg": modifier["rotation_xyz_deg"][2],
            "rotation_xyz_deg": modifier["rotation_xyz_deg"][:2],
            "scale_xyz_percent": modifier["scale_xyz_percent"],
        }
        own_matrix = tuple(float(v) for v in _transform(
            own_pose, bed_width / 2, bed_depth / 2).split())
        for vertex in verts:
            positioned.append(tuple(
                sum(own_matrix[axis + 3 * i] * vertex[i] for i in range(3))
                + own_matrix[9 + axis]
                for axis in range(3)))
    else:
        # Existing draft fixtures remain in parent-local coordinates.
        for vertex in verts:
            local = tuple(vertex[i] + centre[i] for i in range(3))
            positioned.append(tuple(
                sum(matrix[axis + 3 * i] * local[i] for i in range(3)) +
                (matrix[9 + axis] if axis < 2 else bed_z)
                for axis in range(3)))
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


def _export_composite_volume_plate(objects_with_stl, *, bed_width, bed_depth):
    """Build an assembly with several printable parts and plate-space regions.

    All printable meshes remain separate `normal_part` components. Each
    non-printing region is emitted exactly once as a sibling of every printable
    part, so overlapping models are affected without copying or welding STL
    sources. This format still requires pinned worker and G-code acceptance.
    """
    if not 2 <= len(objects_with_stl) <= 12:
        raise SlicerProfileError("Composite native volumes support 2–12 printable models.")
    if any(item.get("process_overrides") for item, _ in objects_with_stl):
        raise SlicerProfileError("Composite modifier and per-model process combinations require independent verification.")
    if any(volume.get("coordinate_space") != "world"
           for item, _ in objects_with_stl
           for volume in validate_modifier_volumes(item.get("modifier_volumes"))):
        raise SlicerProfileError("All composite volumes must have independent plate-space poses.")
    count = sum(len(validate_modifier_volumes(item.get("modifier_volumes")))
                for item, _ in objects_with_stl)
    if not 1 <= count <= MAX_TOTAL_MODIFIERS:
        raise SlicerProfileError("Composite plate has no non-printing volumes or exceeds the limit.")
    original = build_plate_3mf(
        objects_with_stl, bed_width=bed_width, bed_depth=bed_depth,
        allow_modifier_fixture=True)
    with zipfile.ZipFile(io.BytesIO(original), "r") as source:
        members = {name: source.read(name) for name in source.namelist()}
    root = SafeET.fromstring(members["3D/3dmodel.model"])
    resources = root.find(f"{{{NS}}}resources")
    build = root.find(f"{{{NS}}}build")
    if resources is None or build is None:
        raise SlicerProfileError("Invalid compound native source.")
    printable = list(resources.findall(f"{{{NS}}}object"))
    if len(printable) != len(objects_with_stl) or any(
            obj.find(f"{{{NS}}}mesh") is None for obj in printable):
        raise SlicerProfileError("Native composite source has unexpected geometry.")
    for child in list(resources):
        resources.remove(child)
    for child in list(build):
        build.remove(child)
    identity = "1 0 0 0 1 0 0 0 1 0 0 0"
    identity4 = "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"
    parent = ET.SubElement(resources, f"{{{NS}}}object", {"id": "1", "type": "model"})
    components = ET.SubElement(parent, f"{{{NS}}}components")
    ET.SubElement(build, f"{{{NS}}}item", {"objectid": "1", "transform": identity})
    manifest = ET.Element("config")
    settings = ET.SubElement(manifest, "object", {"id": "1"})
    bounds = []
    for index, mesh_obj in enumerate(printable, start=2):
        mesh = mesh_obj.find(f"{{{NS}}}mesh")
        points = [tuple(float(vertex.attrib[axis]) for axis in ("x", "y", "z"))
                  for vertex in mesh.findall(f"{{{NS}}}vertices/{{{NS}}}vertex")]
        if not points:
            raise SlicerProfileError("Missing printable composite mesh vertices.")
        bounds.append(tuple((min(point[axis] for point in points),
                             max(point[axis] for point in points))
                            for axis in range(3)))
        child = ET.SubElement(resources, f"{{{NS}}}object",
                              {"id": str(index), "type": "model"})
        child.append(mesh)
        ET.SubElement(components, f"{{{NS}}}component",
                      {"objectid": str(index), "transform": identity})
        part = ET.SubElement(settings, "part",
                             {"id": str(index), "subtype": "normal_part"})
        ET.SubElement(part, "metadata",
                      {"key": "name", "value": f"Printable model {index-1}"})
        ET.SubElement(part, "metadata", {"key": "matrix", "value": identity4})
    envelope = tuple((min(box[axis][0] for box in bounds),
                      max(box[axis][1] for box in bounds)) for axis in range(3))
    next_id = len(printable) + 2
    for item, _raw in objects_with_stl:
        for volume in validate_modifier_volumes(item.get("modifier_volumes")):
            identifier = next_id
            next_id += 1
            _add_child_mesh(resources, identifier, volume, envelope,
                            None, None, bed_width, bed_depth)
            region_mesh=resources[-1].find(f"{{{NS}}}mesh")
            if region_mesh is None:
                raise SlicerProfileError("Missing non-printing composite mesh.")
            region_points=[tuple(float(node.attrib[axis]) for axis in ("x","y","z"))
                           for node in region_mesh.findall(f"{{{NS}}}vertices/{{{NS}}}vertex")]
            if not region_points:
                raise SlicerProfileError("Empty non-printing composite volume.")
            region_box=tuple((min(point[axis] for point in region_points),
                              max(point[axis] for point in region_points))
                             for axis in range(3))
            if not any(all(region_box[axis][0] < box[axis][1] and
                           box[axis][0] < region_box[axis][1]
                           for axis in range(3)) for box in bounds):
                raise SlicerProfileError(
                    "A non-printing volume does not intersect any printable model.")
            ET.SubElement(components, f"{{{NS}}}component",
                          {"objectid": str(identifier), "transform": identity})
            subtype = ("negative_part" if volume["kind"] == "negative"
                       else "modifier_part")
            part = ET.SubElement(settings, "part",
                                 {"id": str(identifier), "subtype": subtype})
            ET.SubElement(part, "metadata", {
                "key": "name",
                "value": f"{volume['shape'].title()} {volume['kind']}",
            })
            ET.SubElement(part, "metadata", {"key": "matrix", "value": identity4})
            for key, value in sorted(volume["settings"].items()):
                suffix = "%" if PROCESS_FIELDS[key][2] == "%" else ""
                ET.SubElement(part, "metadata",
                              {"key": key, "value": f"{value}{suffix}"})
    plate = ET.SubElement(manifest, "plate")
    ET.SubElement(plate, "metadata", {"key": "plater_id", "value": "1"})
    instance = ET.SubElement(plate, "model_instance")
    for key, value in (("object_id", "1"), ("instance_id", "0"),
                       ("identify_id", "1")):
        ET.SubElement(instance, "metadata", {"key": key, "value": value})
    ET.register_namespace("", NS)
    members["3D/3dmodel.model"] = ET.tostring(
        root, encoding="utf-8", xml_declaration=True)
    members["Metadata/model_settings.config"] = ET.tostring(
        manifest, encoding="utf-8", xml_declaration=True)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=False) as result:
        for name, payload in members.items():
            result.writestr(name, payload)
    data = output.getvalue()
    if len(data) > project_archive_budget():
        raise SlicerProfileError("Native composite project exceeds upload limits.")
    return data


def export_modifier_3mf_fixture(objects_with_stl, *, bed_width, bed_depth):
    """Produce native-looking nested volume fixture, never bypass runtime gates."""
    if not isinstance(objects_with_stl, list):
        raise SlicerProfileError("Invalid modifier plate.")
    if len(objects_with_stl) > 1:
        return _export_composite_volume_plate(
            objects_with_stl, bed_width=bed_width, bed_depth=bed_depth)
    count = sum(len(validate_modifier_volumes(item.get("modifier_volumes")))
                for item, _ in objects_with_stl)
    if not count or count > MAX_TOTAL_MODIFIERS:
        raise SlicerProfileError("No valid modifiers or too many modifier regions.")
    original = build_plate_3mf(objects_with_stl, bed_width=bed_width, bed_depth=bed_depth,
                               allow_modifier_fixture=True);
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
        parent_transform, parent_bed_z = _modifier_parent_transform(
            item, objects_with_stl[index - 1][1], bed_width, bed_depth)
        for number, modifier in enumerate(modifiers, start=1):
            modifier_id = next_id
            next_id += 1
            _add_child_mesh(resources, modifier_id, modifier, parent_bounds,
                            parent_transform, parent_bed_z, bed_width, bed_depth)
            ET.SubElement(components, f"{{{NS}}}component", {
                "objectid": str(modifier_id), "transform": identity,
            })
            part = ET.SubElement(settings, "part", {
                "id": str(modifier_id),
                "subtype": "negative_part" if modifier["kind"] == "negative" else "modifier_part",
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
    if len(data) > project_archive_budget():
        raise SlicerProfileError("Modifier project exceeds the worker upload limit.")
    return data
