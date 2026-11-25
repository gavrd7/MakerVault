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
from .slicer_prusa_process_settings import apply_prusa_process_overrides, FIELDS
from .slicer_prusa_native_resolution import parse_prusa_profile
from .slicer_profiles import SlicerProfileError

OBJECT_KEYS = frozenset({"wall_loops", "sparse_infill_density"})
CONFIG_PATH = "Metadata/Slic3r_PE_model.config"
BASE = b"layer_height = 0.2\nperimeters = 2\nfill_density = 15%\n"


def build_prusa_native_3mf(rows, *, bed_width, bed_depth):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 12:
        raise SlicerProfileError("Prusa native project requires one to twelve objects.")
    ET.register_namespace("", NS)
    model = ET.Element(f"{{{NS}}}model", {"unit": "millimeter", "xmlns:slic3rpe": "http://schemas.slic3r.org/3mf/2017/06"})
    ET.SubElement(model, f"{{{NS}}}metadata", {"name": "slic3rpe:Version3mf"}).text = "1"
    resources = ET.SubElement(model, f"{{{NS}}}resources")
    build = ET.SubElement(model, f"{{{NS}}}build")
    config = ET.Element("config")
    total_bytes = total_faces = 0
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
        baked = build_prusa_placed_stl([(geometry_item, raw)], bed_width=bed_width, bed_depth=bed_depth)
        count = struct.unpack_from("<I", baked, 80)[0]
        total_faces += count
        if total_faces > MAX_TRIANGLES:
            raise SlicerProfileError("Prusa native project triangle limit exceeded.")
        obj = ET.SubElement(resources, f"{{{NS}}}object", {"id": str(index), "type": "model"})
        mesh = ET.SubElement(obj, f"{{{NS}}}mesh")
        vertices = ET.SubElement(mesh, f"{{{NS}}}vertices")
        triangles = ET.SubElement(mesh, f"{{{NS}}}triangles")
        indexed = {}
        for tri in struct.iter_unpack("<12fH", baked[84:]):
            ids = []
            for offset in (3, 6, 9):
                point = tuple(tri[offset:offset+3])
                if point not in indexed:
                    indexed[point] = len(indexed)
                    ET.SubElement(vertices, f"{{{NS}}}vertex", dict(zip(("x", "y", "z"), map(str, point))))
                ids.append(indexed[point])
            ET.SubElement(triangles, f"{{{NS}}}triangle", dict(zip(("v1", "v2", "v3"), map(str, ids))))
        ET.SubElement(build, f"{{{NS}}}item", {"objectid": str(index)})
        settings = ET.SubElement(config, "object", {"id": str(index), "instances_count": "1"})
        for key in sorted(overrides):
            native_key = FIELDS[key][0]
            ET.SubElement(settings, "metadata", {"type": "object", "key": native_key, "value": native[native_key]})
        ET.SubElement(settings, "volume", {"firstid": "0", "lastid": str(count - 1)})
    model_xml = ET.tostring(model, encoding="utf-8", xml_declaration=True)
    if len(model_xml) > 96 * 1024 * 1024:
        raise SlicerProfileError("Prusa native project XML exceeds limit.")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=False) as package:
        package.writestr("3D/3dmodel.model", model_xml)
        package.writestr(CONFIG_PATH, ET.tostring(config, encoding="utf-8", xml_declaration=True))
        package.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/><Default Extension="config" ContentType="application/xml"/></Types>')
        package.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    data = output.getvalue()
    if len(data) > MAX_PROJECT_BYTES:
        raise SlicerProfileError("Prusa native project archive exceeds limit.")
    return data
