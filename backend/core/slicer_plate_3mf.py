"""Strictly bounded 3MF project generator for independently identified STL instances.

Optional, validated per-object process metadata is stored in Orca/Bambu
model_settings.config; this does not itself authorise worker execution.
"""
import io
import json
import math
import re
import struct
import zipfile
from xml.etree import ElementTree as ET
from defusedxml import ElementTree as SafeET

from .slicer_mesh import MeshInspectionError
from .slicer_profiles import SlicerProfileError
from .slicer_process_settings import PROCESS_FIELDS, validate_process_overrides

NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
# Match the validated source-STL limit. Generated XML/archive limits remain
# independent safety checks for highly detailed or poorly compressing meshes.
MAX_TRIANGLES = 500_000
MAX_SOURCE_TOTAL = 48 * 1024 * 1024
MAX_PROJECT_BYTES = 32 * 1024 * 1024

def _triangles(raw):
    from .slicer_mesh import inspect_stl
    try:
        fmt = inspect_stl(raw)["format"]
    except MeshInspectionError as exc:
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
    # Do not allocate a second 3*triangle-count list of vertex tuples.
    minimum = [min(point[i] for tri in triangles for point in tri) for i in range(3)]
    maximum = [max(point[i] for tri in triangles for point in tri) for i in range(3)]
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
    return len(triangles), maximum[0] - minimum[0], maximum[1] - minimum[1]


def _axis_scales(item):
    xyz = item.get("scale_xyz_percent")
    if xyz is None:
        factor = float(item["scale_percent"]) / 100
        return factor, factor, factor
    if (not isinstance(xyz, (list, tuple)) or len(xyz) != 3 or any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not 5 <= value <= 400 for value in xyz)):
        raise SlicerProfileError("Invalid individual model scale.")
    return tuple(float(value) / 100 for value in xyz)


def _transform(item, offset_x, offset_y):
    sx, sy, sz = _axis_scales(item)
    angle = math.radians(float(item["rotation_deg"]))
    rx, ry = (math.radians(float(value)) for value in
              item.get("rotation_xyz_deg", [0, 0]))
    cx, cy, cz = math.cos(rx), math.cos(ry), math.cos(angle)
    ax, ay, az = math.sin(rx), math.sin(ry), math.sin(angle)
    # THREE.Euler('XYZ') is Rx * Ry * Rz. Store 3MF row-major local axis
    # columns so the preview and exported geometry have identical orientation.
    r00, r01, r02 = cy * cz, -cy * az, ay
    r10, r11, r12 = cx * az + ax * ay * cz, cx * cz - ax * ay * az, -ax * cy
    r20, r21, r22 = ax * az - cx * ay * cz, ax * cz + cx * ay * az, cx * cy
    values = (sx * r00, sx * r10, sx * r20,
              sy * r01, sy * r11, sy * r21,
              sz * r02, sz * r12, sz * r22,
              offset_x + float(item["x_mm"]), offset_y + float(item["y_mm"]), float(item.get("z_mm", 0)))
    if any(not math.isfinite(value) or abs(value) > 10000 for value in values):
        raise SlicerProfileError("Invalid 3MF object placement.")
    return " ".join(format(value, ".6f") for value in values)


def _bake_native_instance_transform(obj, transform):
    """Apply the 3MF placement matrix to one mesh without merging objects.

    Orca's generic 3MF import can ignore separated *build-item* transforms
    during CLI slicing, yielding duplicate objects at one origin. Baking each
    transform into its own distinct resource preserves placement and identity.
    """
    values = [float(part) for part in transform.split()]
    if len(values) != 12 or any(not math.isfinite(value) for value in values):
        raise SlicerProfileError("Invalid independent model transformation.")
    mesh = obj.find(f"{{{NS}}}mesh")
    vertices = mesh.find(f"{{{NS}}}vertices")
    for vertex in vertices:
        x, y, z = (float(vertex.attrib[key]) for key in ("x", "y", "z"))
        mapped = (
            values[0] * x + values[3] * y + values[6] * z + values[9],
            values[1] * x + values[4] * y + values[7] * z + values[10],
            values[2] * x + values[5] * y + values[8] * z + values[11],
        )
        if any(not math.isfinite(coord) or abs(coord) > 10000 for coord in mapped):
            raise SlicerProfileError("Baked 3MF placement exceeds safe bounds.")
        for axis, value in zip(("x", "y", "z"), mapped):
            vertex.set(axis, format(value, ".6f"))


def build_plate_3mf(objects_with_stl, *, bed_width, bed_depth, native_tool_indices=None):
    """Render [(validated_plate_item_dict, owned_STL_bytes)] as one core 3MF.

    Preview coordinates are centred around the bed. Shift all instances by the
    explicitly validated bed half-extent to place them in its positive quadrant.
    """
    if not isinstance(objects_with_stl, list) or not 1 <= len(objects_with_stl) <= 200:
        raise SlicerProfileError("A plate needs one to 200 STL models.")
    # Native tool indices are zero-based at the routing boundary, but Orca's
    # per-object extruder metadata is one-based. Never infer these from slot
    # positions: the caller must supply verified native palette assignments.
    if native_tool_indices is not None and (
            not isinstance(native_tool_indices, (list, tuple)) or
            len(native_tool_indices) != len(objects_with_stl) or
            any(isinstance(tool, bool) or not isinstance(tool, int)
                or not 0 <= tool <= 63 for tool in native_tool_indices)):
        raise SlicerProfileError("Invalid verified native extruder indices.")
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
    # Only native per-object projects use baked individual placements. Existing
    # generic 3MF exports and their transform semantics remain unchanged.
    bake_native_positions = native_tool_indices is not None or any(
        isinstance(entry, tuple) and len(entry) == 2 and
        isinstance(entry[0], dict) and (
            bool(entry[0].get("process_overrides")) or
            abs(float(entry[0].get("z_mm", 0))) > 1e-7 or
            any(abs(float(v)) > 1e-7 for v in entry[0].get("rotation_xyz_deg", [0, 0]))
        )
        for entry in objects_with_stl
    )
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
        count, width, depth = _render_mesh(raw, obj)
        total_triangles += count
        # Transform the actual welded vertices, not only the original 2D
        # bounding rectangle: a tilted model has a different XY footprint.
        # Compute bottom clearance from the same matrix to ensure it rests at
        # Z=0 in both the 3MF exporter and the browser's 3D preview.
        provisional = [float(value) for value in
                       _transform(item, bed_width / 2, bed_depth / 2).split()]
        vertex_nodes = obj.findall(f"./{{{NS}}}mesh/{{{NS}}}vertices/{{{NS}}}vertex")
        placed = []
        for vertex in vertex_nodes:
            x, y, z = (float(vertex.attrib[key]) for key in ("x", "y", "z"))
            placed.append((
                provisional[0] * x + provisional[3] * y + provisional[6] * z + provisional[9],
                provisional[1] * x + provisional[4] * y + provisional[7] * z + provisional[10],
                provisional[2] * x + provisional[5] * y + provisional[8] * z,
            ))
        if not placed or any(not (0 <= x <= bed_width and 0 <= y <= bed_depth)
                             for x, y, _z in placed):
            raise SlicerProfileError("A model extends outside the verified build plate.")
        minimum_z = min(point[2] for point in placed)
        # Tilted STL always rests on its lowest vertex before applying the
        # explicitly requested elevation. Do not auto-drop stacked objects.
        desired_z = float(item.get("z_mm", 0))
        if not math.isfinite(desired_z) or not 0 <= desired_z <= 1000:
            raise SlicerProfileError("Invalid model elevation.")
        provisional[11] = desired_z - minimum_z
        placement = " ".join(format(value, ".6f") for value in provisional)
        if total_triangles > MAX_TRIANGLES:
            raise SlicerProfileError("Total plate triangles exceed the limit.")
        if bake_native_positions:
            _bake_native_instance_transform(obj, placement)
            placement = "1 0 0 0 1 0 0 0 1 0 0 0"
        ET.SubElement(build, f"{{{NS}}}item", {
            "objectid": str(index),
            "transform": placement,
        })
    model_xml = ET.tostring(model, encoding="utf-8", xml_declaration=True)
    if len(model_xml) > 96 * 1024 * 1024:
        raise SlicerProfileError("The generated 3MF mesh is too large.")
    # Preserve Orca's model IDs one-to-one with the 3MF resource IDs.
    # A distinct <object> entry holds validated native overrides. The
    # production worker still rejects execution of object-specific edits
    # until the unmerged-3MF real-binary fixture is approved.
    per_object = []
    for item, _raw in objects_with_stl:
        try:
            per_object.append(validate_process_overrides(item.get("process_overrides")))
        except ValueError as exc:
            raise SlicerProfileError("Invalid native per-object process setting.") from exc
    plate_xml = None
    if len(objects_with_stl) > 1 or any(per_object) or native_tool_indices is not None:
        manifest = ET.Element("config")
        for index, overrides in enumerate(per_object, start=1):
            if not overrides and native_tool_indices is None:
                continue
            obj_settings = ET.SubElement(manifest, "object", {"id": str(index)})
            if native_tool_indices is not None:
                ET.SubElement(obj_settings, "metadata", {
                    "key": "extruder", "value": str(native_tool_indices[index - 1] + 1),
                })
            for key, value in sorted(overrides.items()):
                unit = PROCESS_FIELDS[key][2] if key in PROCESS_FIELDS else ""
                value_str = str(value)
                if unit == "%":
                    value_str += "%"
                ET.SubElement(obj_settings, "metadata", {
                    "key": key, "value": value_str,
                })
        plate = ET.SubElement(manifest, "plate")
        ET.SubElement(plate, "metadata", {"key": "plater_id", "value": "1"})
        for index in range(1, len(objects_with_stl) + 1):
            instance = ET.SubElement(plate, "model_instance")
            for key, value in (("object_id", str(index)),
                               ("instance_id", "0"),
                               ("identify_id", str(index))):
                ET.SubElement(instance, "metadata", {"key": key, "value": value})
        plate_xml = ET.tostring(manifest, encoding="utf-8", xml_declaration=True)
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=False) as package:
        package.writestr("3D/3dmodel.model", model_xml)
        if plate_xml is not None:
            package.writestr("Metadata/model_settings.config", plate_xml)
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


def build_compound_plate_3mf(objects_with_stl, *, bed_width, bed_depth):
    """Single-material Orca-compatible plate with all STL transforms baked in.

    Upstream Orca 2.4.2 CLI does not reliably slice every object in a generic
    multi-item core 3MF. Merge geometrically separate shells into ONE mesh
    while preserving each STL's rotation, scale and XY offset. Individual
    physical materials / extruder assignments are NOT supported by this route.

    Each input still runs through build_plate_3mf's strict ownership-independent
    geometry, triangle-count, bed-fit and archive-size validations first.
    """
    if not isinstance(objects_with_stl, list) or not 1 <= len(objects_with_stl) <= 200:
        raise SlicerProfileError("A plate needs one to 200 STL models.")
    if len(objects_with_stl) == 1:
        return build_plate_3mf(objects_with_stl, bed_width=bed_width, bed_depth=bed_depth)
    source = build_plate_3mf(objects_with_stl, bed_width=bed_width, bed_depth=bed_depth)
    ns = "{" + NS + "}"
    with zipfile.ZipFile(io.BytesIO(source)) as archive:
        root = SafeET.fromstring(archive.read("3D/3dmodel.model"))
        types = archive.read("[Content_Types].xml")
        relationships = archive.read("_rels/.rels")
    original_objects = root.findall("./" + ns + "resources/" + ns + "object")
    original_instances = root.findall("./" + ns + "build/" + ns + "item")
    if len(original_objects) != len(objects_with_stl) or len(original_instances) != len(objects_with_stl):
        raise SlicerProfileError("The generated plate does not contain every source model.")
    composite = ET.Element(ns + "model", {
        "unit": "millimeter", "{http://www.w3.org/XML/1998/namespace}lang": "en-US"
    })
    resources = ET.SubElement(composite, ns + "resources")
    merged_mesh = ET.SubElement(
        ET.SubElement(resources, ns + "object", {"id": "1", "type": "model"}),
        ns + "mesh",
    )
    merged_vertices = ET.SubElement(merged_mesh, ns + "vertices")
    merged_faces = ET.SubElement(merged_mesh, ns + "triangles")
    for native_object, instance in zip(original_objects, original_instances):
        transform = [float(v) for v in instance.attrib["transform"].split()]
        if len(transform) != 12 or any(not math.isfinite(v) for v in transform):
            raise SlicerProfileError("Invalid source model transform.")
        vertices = native_object.findall("./" + ns + "mesh/" + ns + "vertices/" + ns + "vertex")
        triangles = native_object.findall("./" + ns + "mesh/" + ns + "triangles/" + ns + "triangle")
        vertex_offset = len(merged_vertices)
        for vertex in vertices:
            x, y, z = [float(vertex.attrib[axis]) for axis in ("x", "y", "z")]
            location = (
                transform[0] * x + transform[3] * y + transform[6] * z + transform[9],
                transform[1] * x + transform[4] * y + transform[7] * z + transform[10],
                transform[2] * x + transform[5] * y + transform[8] * z + transform[11],
            )
            if any(not math.isfinite(v) or abs(v) > 10000 for v in location):
                raise SlicerProfileError("Combined plate geometry exceeds the safe bounds.")
            ET.SubElement(merged_vertices, ns + "vertex", {
                axis: format(value, ".6f")
                for axis, value in zip(("x", "y", "z"), location)
            })
        for face in triangles:
            ET.SubElement(merged_faces, ns + "triangle", {
                key: str(vertex_offset + int(face.attrib[key]))
                for key in ("v1", "v2", "v3")
            })
    build = ET.SubElement(composite, ns + "build")
    ET.SubElement(build, ns + "item", {
        "objectid": "1", "transform": "1 0 0 0 1 0 0 0 1 0 0 0"
    })
    encoded = ET.tostring(composite, encoding="utf-8", xml_declaration=True)
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=False) as archive:
        archive.writestr("3D/3dmodel.model", encoded)
        archive.writestr("[Content_Types].xml", types)
        archive.writestr("_rels/.rels", relationships)
    data = output.getvalue()
    if not data or len(data) > MAX_PROJECT_BYTES:
        raise SlicerProfileError("Combined 3MF exceeds the safe worker upload limit.")
    return data


def build_makervault_project_3mf(plates_with_stl, *, bed_width, bed_depth, metadata):
    """Portable, editable 3MF with a native mesh scene and plate manifest.

    Every plate also has an independent ordinary 3MF inside the archive.
    The MakerVault manifest records true centred per-plate coordinates, labels,
    material preview colours, part settings and selected native profiles.
    The combined top-level 3MF arranges plates side by side for generic viewers.
    It is an export, not an assertion of verified Orca native project import.
    """
    if not isinstance(plates_with_stl, list) or not 1 <= len(plates_with_stl) <= 8:
        raise SlicerProfileError("Export supports one to eight project plates.")
    if not any(rows for _label, rows in plates_with_stl):
        raise SlicerProfileError("Add at least one STL before exporting a project.")
    if sum(len(rows) for _label, rows in plates_with_stl) > 200:
        raise SlicerProfileError("A project supports up to 200 instances.")
    ns = "{" + NS + "}"
    ET.register_namespace("", NS)
    combined = ET.Element(ns + "model", {
        "unit": "millimeter",
        "{http://www.w3.org/XML/1998/namespace}lang": "en-US"
    })
    resources = ET.SubElement(combined, ns + "resources")
    build = ET.SubElement(combined, ns + "build")
    embedded = {}
    source_stls = {}
    total_source_bytes = 0
    plate_manifest = ET.Element("config")
    global_index = 0
    for plate_number, (label, pairs) in enumerate(plates_with_stl, start=1):
        plate_element = ET.SubElement(plate_manifest, "plate")
        ET.SubElement(plate_element, "metadata", {
            "key": "plater_id", "value": str(plate_number)
        })
        ET.SubElement(plate_element, "metadata", {
            "key": "plate_name", "value": label
        })
        if not pairs:
            continue
        for item, raw in pairs:
            asset_id = str(item.get("asset_id", ""))
            if not re.fullmatch(r"[a-fA-F0-9-]{36}", asset_id):
                raise SlicerProfileError("Project source asset has no valid identifier.")
            if asset_id not in source_stls:
                source_stls[asset_id] = raw
                total_source_bytes += len(raw)
                if total_source_bytes > 64 * 1024 * 1024:
                    raise SlicerProfileError("Total project source STL size exceeds 64 MiB.")
        native = build_plate_3mf(pairs, bed_width=bed_width, bed_depth=bed_depth)
        embedded[f"Metadata/plates/plate-{plate_number}.3mf"] = native
        with zipfile.ZipFile(io.BytesIO(native)) as source:
            tree = SafeET.fromstring(source.read("3D/3dmodel.model"))
        objects = tree.findall("./" + ns + "resources/" + ns + "object")
        instances = tree.findall("./" + ns + "build/" + ns + "item")
        if len(objects) != len(pairs) or len(instances) != len(pairs):
            raise SlicerProfileError("Incomplete generated plate geometry.")
        for source_obj, instance in zip(objects, instances):
            global_index += 1
            source_obj.set("id", str(global_index))
            resources.append(source_obj)
            matrix = [float(v) for v in instance.attrib["transform"].split()]
            if len(matrix) != 12:
                raise SlicerProfileError("Invalid generated model transform.")
            matrix[9] += (plate_number - 1) * (bed_width + 20)
            ET.SubElement(build, ns + "item", {
                "objectid": str(global_index),
                "transform": " ".join(format(v, ".6f") for v in matrix)
            })
            row = ET.SubElement(plate_element, "model_instance")
            for key, value in (("object_id", str(global_index)),
                               ("instance_id", "0"),
                               ("identify_id", str(global_index))):
                ET.SubElement(row, "metadata", {"key": key, "value": value})
    # Large v2 surface-region data belongs in separate compressed project
    # sidecars, never inside the small 3MF metadata manifest or native toolpaths.
    paint_sidecars = {}
    portable_metadata = {**metadata, "plates": []}
    for plate in metadata.get("plates", []):
        portable_plate = {**plate, "objects": []}
        for row in plate.get("objects", []):
            paint = row.get("colour_paint")
            if isinstance(paint, dict) and paint.get("version") == 2:
                name = "Metadata/paint/paint-%04d.json" % (len(paint_sidecars) + 1)
                blob = json.dumps(paint, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                if len(blob) > 16 * 1024 * 1024:
                    raise SlicerProfileError("Painted model exceeds project 3MF region limit.")
                paint_sidecars[name] = blob
                portable_plate["objects"].append({
                    **{key: value for key, value in row.items() if key != "colour_paint"},
                    "paint_sidecar": name,
                })
            else:
                portable_plate["objects"].append(row)
        portable_metadata["plates"].append(portable_plate)
    if sum(map(len, paint_sidecars.values())) > 64 * 1024 * 1024:
        raise SlicerProfileError("Project painting regions exceed the export limit.")
    manifest = json.dumps(portable_metadata, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(manifest) > 131072:
        raise SlicerProfileError("Project metadata is too large.")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=False) as package:
        package.writestr("3D/3dmodel.model",
                         ET.tostring(combined, encoding="utf-8", xml_declaration=True))
        package.writestr("Metadata/model_settings.config",
                         ET.tostring(plate_manifest, encoding="utf-8", xml_declaration=True))
        package.writestr("Metadata/makervault-project.json", manifest)
        for name, data in embedded.items():
            package.writestr(name, data)
        for name, data in paint_sidecars.items():
            package.writestr(name, data)
        for asset_id, raw in source_stls.items():
            package.writestr("Metadata/sources/" + asset_id + ".stl", raw)
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
    result = output.getvalue()
    if len(result) > MAX_PROJECT_BYTES:
        raise SlicerProfileError("Project 3MF exceeds the safe export limit.")
    return result
