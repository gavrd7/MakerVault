"""Candidate native Prusa 2.9.7 3MF exporter; not an execution admission gate.

Format reference: upstream src/libslic3r/Format/3mf.cpp at 450d70dd.
Each resource owns its mesh and native object configuration. No external
paths, embedded print profiles, executable directives or arbitrary metadata.
"""
import io
import struct
import zipfile
from xml.etree import ElementTree as ET

from .slicer_plate_3mf import NS, MAX_PROJECT_BYTES, MAX_TRIANGLES, MAX_SOURCE_TOTAL
from .slicer_prusa_plate import build_prusa_placed_stl
from .slicer_modifier_volumes import (validate_modifier_volumes, MAX_TOTAL_MODIFIERS,
                                      assert_native_plate_volume_coverage)
from .slicer_modifier_3mf import _modifier_parent_transform, _add_child_mesh
from .slicer_prusa_process_settings import apply_prusa_process_overrides, FIELDS
from .slicer_prusa_native_resolution import parse_prusa_profile
from .slicer_profiles import SlicerProfileError
from .slicer_prusa_layer_ranges import prusa_layer_config_ranges, PATH as LAYER_RANGES_PATH
from .slicer_prusa_paint import native_prusa_painted_stl, HEADERS as PAINT_HEADERS

OBJECT_KEYS = frozenset({"wall_loops", "sparse_infill_density",
                         "top_shell_layers", "bottom_shell_layers"})
CONFIG_PATH = "Metadata/Slic3r_PE_model.config"
BASE = (b"layer_height = 0.2\nperimeters = 2\nfill_density = 15%\n"
        b"top_solid_layers = 3\nbottom_solid_layers = 3\n")


def build_prusa_native_3mf(rows, *, bed_width, bed_depth):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 12:
        raise SlicerProfileError("Prusa native project requires one to twelve objects.")
    ET.register_namespace("", NS)
    model = ET.Element(f"{{{NS}}}model", {"unit": "millimeter", "xmlns:slic3rpe": "http://schemas.slic3r.org/3mf/2017/06"})
    ET.SubElement(model, f"{{{NS}}}metadata", {"name": "slic3rpe:Version3mf"}).text = "1"
    # Native Prusa 2.9.7 requires versioned painting metadata before resources.
    headers = {name for pair in rows if isinstance(pair, tuple) and isinstance(pair[0], dict)
               for key, name in PAINT_HEADERS.items()
               if isinstance(pair[0].get(key), dict) and pair[0][key].get("regions")}
    for name in sorted(headers):
        ET.SubElement(model, f"{{{NS}}}metadata", {"name": name}).text = "2"
    resources = ET.SubElement(model, f"{{{NS}}}resources")
    build = ET.SubElement(model, f"{{{NS}}}build")
    config = ET.Element("config")
    total_bytes = total_faces = total_modifiers = 0
    seen_modifiers = set()
    layer_ranges = prusa_layer_config_ranges(rows)
    for index, pair in enumerate(rows, 1):
        if not isinstance(pair, tuple) or len(pair) != 2 or not isinstance(pair[0], dict) or not isinstance(pair[1], bytes):
            raise SlicerProfileError("Invalid Prusa native project object.")
        item, raw = pair
        total_bytes += len(raw)
        if total_bytes > MAX_SOURCE_TOTAL:
            raise SlicerProfileError("Prusa native project source limit exceeded.")
        overrides = item.get("process_overrides") or {}
        if not isinstance(overrides, dict) or set(overrides) - OBJECT_KEYS:
            raise SlicerProfileError("Unsupported Prusa per-object settings.")
        native = parse_prusa_profile(apply_prusa_process_overrides(BASE, overrides), "process")
        geometry_item = dict(item)
        geometry_item.pop("process_overrides", None)
        geometry_item.pop("variable_layer_profile", None)
        for channel in PAINT_HEADERS:
            geometry_item.pop(channel, None)
        modifiers = validate_modifier_volumes(geometry_item.pop("modifier_volumes", None))
        total_modifiers += len(modifiers)
        if total_modifiers > MAX_TOTAL_MODIFIERS:
            raise SlicerProfileError("Prusa native volume limit exceeded.")
        for modifier in modifiers:
            if modifier["id"] in seen_modifiers:
                raise SlicerProfileError("Duplicate Prusa modifier identity.")
            seen_modifiers.add(modifier["id"])
            # Each native Prusa resource owns its volume ranges. This allows
            # standalone two-parent fixtures without propagating an unrelated
            # modifier onto another model; scheduling remains separately gated.
        painted_raw, facet_tags, required_headers = native_prusa_painted_stl(item, raw)
        if not required_headers.issubset(headers):
            raise SlicerProfileError("Prusa painted metadata is incomplete.")
        baked = build_prusa_placed_stl([(geometry_item, painted_raw)], bed_width=bed_width, bed_depth=bed_depth)
        count = struct.unpack_from("<I", baked, 80)[0]
        total_faces += count
        if total_faces > MAX_TRIANGLES:
            raise SlicerProfileError("Prusa native project triangle limit exceeded.")
        obj = ET.SubElement(resources, f"{{{NS}}}object", {"id": str(index), "type": "model"})
        mesh = ET.SubElement(obj, f"{{{NS}}}mesh")
        vertices = ET.SubElement(mesh, f"{{{NS}}}vertices")
        triangles = ET.SubElement(mesh, f"{{{NS}}}triangles")
        indexed = {}
        if facet_tags is not None and len(facet_tags) != count:
            raise SlicerProfileError("Prusa native painted facet count changed during placement.")
        for face_index, tri in enumerate(struct.iter_unpack("<12fH", baked[84:])):
            ids = []
            for offset in (3, 6, 9):
                point = tuple(tri[offset:offset+3])
                if point not in indexed:
                    indexed[point] = len(indexed)
                    ET.SubElement(vertices, f"{{{NS}}}vertex", dict(zip(("x", "y", "z"), map(str, point))))
                ids.append(indexed[point])
            attrs = dict(zip(("v1", "v2", "v3"), map(str, ids)))
            if facet_tags is not None:
                attrs.update(facet_tags[face_index])
            ET.SubElement(triangles, f"{{{NS}}}triangle", attrs)
        ET.SubElement(build, f"{{{NS}}}item", {"objectid": str(index)})
        settings = ET.SubElement(config, "object", {"id": str(index), "instances_count": "1"})
        for key in sorted(overrides):
            native_key = FIELDS[key][0]
            ET.SubElement(settings, "metadata", {"type": "object", "key": native_key, "value": native[native_key]})
        printable = ET.SubElement(settings, "volume", {"firstid": "0", "lastid": str(count - 1)})
        ET.SubElement(printable, "metadata", {"type": "volume", "key": "volume_type", "value": "ModelPart"})
        if modifiers:
            matrix, bed_z = _modifier_parent_transform(item, raw, bed_width, bed_depth)
            parent_bounds = [(min(p[i] for p in indexed), max(p[i] for p in indexed)) for i in range(3)]
            for modifier in modifiers:
                scratch = ET.Element(f"{{{NS}}}resources")
                child = _add_child_mesh(scratch, 1, modifier, parent_bounds, matrix, bed_z, bed_width, bed_depth)
                child_vertices = child.find(f"./{{{NS}}}mesh/{{{NS}}}vertices")
                child_triangles = child.find(f"./{{{NS}}}mesh/{{{NS}}}triangles")
                start_vertex, start_face = len(vertices), len(triangles)
                total_faces += len(child_triangles)
                if total_faces > MAX_TRIANGLES:
                    raise SlicerProfileError("Prusa native volume triangle limit exceeded.")
                # Prusa imports a contiguous face and vertex range per volume.
                # Never weld vertices across independently typed volumes.
                for vertex in child_vertices:
                    vertices.append(vertex)
                for face in child_triangles:
                    ET.SubElement(triangles, f"{{{NS}}}triangle", {
                        k: str(int(face.get(k)) + start_vertex) for k in ("v1", "v2", "v3")})
                volume = ET.SubElement(settings, "volume", {
                    "firstid": str(start_face), "lastid": str(len(triangles) - 1)})
                role = "NegativeVolume" if modifier["kind"] == "negative" else "ParameterModifier"
                ET.SubElement(volume, "metadata", {"type": "volume", "key": "volume_type", "value": role})
                overrides = modifier["settings"]
                native = parse_prusa_profile(apply_prusa_process_overrides(BASE, overrides), "process")
                for key in sorted(overrides):
                    native_key = FIELDS[key][0]
                    ET.SubElement(volume, "metadata", {"type": "volume", "key": native_key, "value": native[native_key]})
    model_xml = ET.tostring(model, encoding="utf-8", xml_declaration=True)
    if len(model_xml) > 96 * 1024 * 1024:
        raise SlicerProfileError("Prusa native project XML exceeds limit.")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=False) as package:
        package.writestr("3D/3dmodel.model", model_xml)
        package.writestr(CONFIG_PATH, ET.tostring(config, encoding="utf-8", xml_declaration=True))
        if layer_ranges is not None:
            package.writestr(LAYER_RANGES_PATH, layer_ranges)
        package.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/><Default Extension="config" ContentType="application/xml"/></Types>')
        package.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    data = output.getvalue()
    if len(data) > MAX_PROJECT_BYTES:
        raise SlicerProfileError("Prusa native project archive exceeds limit.")
    return data

def validate_prusa_project_admission(plate, settings, version):
    """Admit exactly the pinned Prusa single-material, single-parent region route.

    Shared BBS-family version gates deliberately remain unchanged. This gate
    covers Prusa's *different* native 3MF dialect and matches its validator.
    """
    if not isinstance(plate, list):
        return False
    if version != "2.9.7":
        raise ValueError("Native Prusa project requires the qualified PrusaSlicer 2.9.7 runtime.")
    if not isinstance(settings, dict):
        raise ValueError("Invalid native Prusa plate settings.")
    assert_native_plate_volume_coverage(plate, settings)
    if not 1 <= len(plate) <= 12 or any(not isinstance(row, dict) for row in plate):
        raise ValueError("Native Prusa plate requires one to twelve printable objects.")
    if any(settings.get(key) for key in (
            "multi_material_test", "material_tool_bindings", "slot_filament_profiles",
            "prime_tower")) or settings.get("flush_settings") is not None:
        raise ValueError("Native Prusa project cannot combine unqualified multi-material settings.")
    if settings.get("creality_auto_arrange_offline"):
        raise ValueError("Native Prusa project cannot use Creality auto-arrangement.")
    seen = set()
    total = 0
    for row in plate:
        overrides = row.get("process_overrides") or {}
        if not isinstance(overrides, dict) or set(overrides) - OBJECT_KEYS:
            raise ValueError("Unsupported native Prusa object process settings.")
        apply_prusa_process_overrides(BASE, overrides)
        if ((row.get("colour_paint") or {}).get("regions") or
                (row.get("colour_paint") or {}).get("faces")):
            raise ValueError("Prusa colour painting needs audited native material routing.")
        if (row.get("seam_paint") or {}).get("regions"):
            if len(plate) != 1:
                raise ValueError("Prusa front seam painting requires one native object.")
            from .slicer_prusa_seam_audit import prusa_qualified_seam_direction
            prusa_qualified_seam_direction(row)
        elif (row.get("seam_paint") or {}).get("faces"):
            raise ValueError("Prusa seam paint requires fingerprinted 3MF facets.")
        support = (row.get("support_paint") or {}).get("regions") or []
        fuzzy = (row.get("fuzzy_skin_paint") or {}).get("regions") or []
        if ((row.get("support_paint") or {}).get("faces") or
                (row.get("fuzzy_skin_paint") or {}).get("faces")):
            raise ValueError("Prusa requires fingerprinted native facet regions.")
        if support or fuzzy:
            two_fuzzy = len(plate) == 2 and bool(fuzzy) and not support and (
                sum(bool((entry.get("fuzzy_skin_paint") or {}).get("regions"))
                    for entry in plate) == 1)
            multi_support = 2 <= len(plate) <= 12 and bool(support) and not fuzzy and (
                sum(bool((entry.get("support_paint") or {}).get("regions"))
                    for entry in plate) == 1)
            if multi_support:
                from .slicer_prusa_support_audit import validate_prusa_multi_support_plate
                validate_prusa_multi_support_plate(plate)
            if ((len(plate) != 1 and not two_fuzzy and not multi_support) or overrides or
                    row.get("modifier_volumes") or
                    (row.get("variable_layer_profile") or {}).get("bands")):
                raise ValueError("Prusa painted facets with other object extensions are not yet verified.")
            if two_fuzzy and any(other.get("process_overrides") or
                                 other.get("modifier_volumes") or
                                 (other.get("support_paint") or {}).get("regions") or
                                 (other.get("variable_layer_profile") or {}).get("bands")
                                 for other in plate):
                raise ValueError("Prusa two-object fuzzy skin cannot combine other regional extensions.")
            if support and fuzzy:
                raise ValueError("Combined support and fuzzy skin require a regional G-code fixture.")
            if not isinstance(support, list) or not isinstance(fuzzy, list) or any(
                    not isinstance(region, dict) or region.get("slot") not in (0, 1)
                    for region in support) or any(
                    not isinstance(region, dict) or region.get("slot") != 0
                    for region in fuzzy):
                raise ValueError("Invalid Prusa native support/fuzzy paint state.")
        if row.get("negative_volumes"):
            raise ValueError("Legacy negative volumes need explicit native volume representation.")
        volumes = validate_modifier_volumes(row.get("modifier_volumes"))
        total += len(volumes)
        if total > MAX_TOTAL_MODIFIERS:
            raise ValueError("Prusa native modifier count exceeds the limit.")
        # The pinned mixed-object spatial fixture separately verifies a
        # parameter modifier on one model and a process override on another.
        # The same-model stack, and negative cavities mixed with Object
        # settings, still need their own native deposition qualification.
        if len(plate) > 1 and volumes and any(model.get("process_overrides")
                                                for model in plate) and (
                overrides or any(v["kind"] == "negative" for v in volumes)):
            raise ValueError(
                "Native per-object overrides cannot share a modifier model or "
                "mix with negative cavities without separate G-code proof.")
        for volume in volumes:
            if volume["id"] in seen:
                raise ValueError("Duplicate Prusa native volume identity.")
            seen.add(volume["id"])
            if volume["kind"] == "negative" and volume.get("coordinate_space") != "world":
                raise ValueError("Prusa negative volumes require independent plate coordinates.")
    if total and any((row.get("variable_layer_profile") or {}).get("bands")
                     for row in plate):
        raise ValueError("Native Prusa modifier and variable-layer combinations need separate G-code proof.")
    # Bounded native layer config ranges are a separate, upstream Prusa XML
    # feature, already checked against actual Prusa 2.9.7 Z steps.
    prusa_layer_config_ranges([(row, b"") for row in plate])
    return total > 0
