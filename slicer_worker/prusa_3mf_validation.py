"""Strict Prusa 2.9.7 generated-project dialect. No arbitrary project input."""
import io
import math
import re
import zipfile
from xml.etree import ElementTree as ET

from .runner import WorkerError

NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
CONFIG = "Metadata/Slic3r_PE_model.config"
LAYER_RANGES = "Metadata/Prusa_Slicer_layer_config_ranges.xml"
PARTS = {"3D/3dmodel.model", CONFIG, "[Content_Types].xml", "_rels/.rels"}
LIMIT = 500_000
PAINT_NS = "{http://schemas.slic3r.org/3mf/2017/06}"
PAINT_HEADERS = {
    PAINT_NS + "custom_supports": "slic3rpe:FdmSupportsPaintingVersion",
    PAINT_NS + "custom_seam": "slic3rpe:SeamPaintingVersion",
    PAINT_NS + "fuzzy_skin": "slic3rpe:FuzzySkinPaintingVersion",
}


def _require(condition):
    if not condition:
        raise WorkerError("Invalid or unsupported native Prusa 3MF project.")


def _xml(raw):
    _require(b"<!" not in raw and b"\x00" not in raw)
    return ET.fromstring(raw)


def _integer(value, maximum):
    _require(isinstance(value, str) and re.fullmatch(r"[0-9]{1,7}", value) is not None)
    number = int(value)
    _require(0 <= number <= maximum)
    return number


def _settings(nodes, kind, allowed):
    result = {}
    for node in nodes:
        _require(node.tag == "metadata" and not len(node) and
                 set(node.attrib) == {"type", "key", "value"} and node.get("type") == kind)
        key, val = node.get("key"), node.get("value")
        _require(key in allowed and key not in result)
        if key == "volume_type":
            _require(val in {"ModelPart", "ParameterModifier", "NegativeVolume"})
        elif key == "perimeters":
            _require(1 <= _integer(val, 12) <= 12)
        elif key in {"top_solid_layers", "bottom_solid_layers"}:
            _require(0 <= _integer(val, 20) <= 20)
        elif key == "fill_density":
            _require(re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{1,4})?%", val) is not None
                     and 0 <= float(val[:-1]) <= 100)
        elif key in {"external_perimeter_speed", "perimeter_speed",
                     "infill_speed", "top_solid_infill_speed"}:
            _require(isinstance(val, str) and
                     re.fullmatch(r"[0-9]{1,3}(?:\\.[0-9]{1,4})?", val) is not None and
                     5 <= float(val) <= 350)
        result[key] = val
    return result



def _validate_layer_ranges(root, object_count):
    _require(root.tag == "objects" and not root.attrib and not (root.text or "").strip())
    _require(1 <= len(root) <= object_count)
    previous_id = 0
    total = 0
    for obj in root:
        _require(obj.tag == "object" and set(obj.attrib) == {"id"})
        ident = _integer(obj.get("id"), object_count)
        _require(previous_id < ident and 1 <= ident <= object_count and 1 <= len(obj) <= 80)
        previous_id = ident
        previous_end = -1.
        for interval in obj:
            _require(interval.tag == "range" and set(interval.attrib) == {"min_z", "max_z"}
                     and len(interval) == 1)
            lo = float(interval.get("min_z"))
            hi = float(interval.get("max_z"))
            _require(math.isfinite(lo) and math.isfinite(hi) and
                     0 <= lo < hi <= 1000 and lo >= previous_end)
            previous_end = hi
            option = interval[0]
            _require(option.tag == "option" and option.attrib == {"opt_key": "layer_height"}
                     and not len(option))
            value = float(option.text)
            _require(math.isfinite(value) and .05 <= value <= .5)
            total += 1
            _require(total <= 80)
    return total


def validate_prusa_native_3mf(data):
    _require(isinstance(data, bytes) and 0 < len(data) <= 32 * 1024 * 1024)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos = z.infolist()
            names = {i.filename for i in infos}
            _require(len(infos) == len(names) and names in (PARTS, PARTS | {LAYER_RANGES}))
            _require(all(0 < i.file_size <= (80 * 1024 * 1024 if i.filename == "3D/3dmodel.model"
                                             else 65536) and not i.is_dir() for i in infos))
            layer_root = _xml(z.read(LAYER_RANGES)) if LAYER_RANGES in names else None
            model = _xml(z.read("3D/3dmodel.model"))
            config = _xml(z.read(CONFIG))
            # These are fixed exporter literals; refuse external relationships,
            # extra content types, and duplicate or alternate model references.
            rel = _xml(z.read("_rels/.rels"))
            ct = _xml(z.read("[Content_Types].xml"))
            rel_ns = "{http://schemas.openxmlformats.org/package/2006/relationships}"
            ct_ns = "{http://schemas.openxmlformats.org/package/2006/content-types}"
            _require(rel.tag == rel_ns + "Relationships" and not rel.attrib and len(rel) == 1)
            _require(rel[0].tag == rel_ns + "Relationship" and not len(rel[0]) and
                     rel[0].attrib == {"Target": "/3D/3dmodel.model", "Id": "rel0",
                         "Type": "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"})
            _require(ct.tag == ct_ns + "Types" and not ct.attrib and len(ct) == 3)
            types = {"rels": "application/vnd.openxmlformats-package.relationships+xml",
                     "model": "application/vnd.ms-package.3dmanufacturing-3dmodel+xml",
                     "config": "application/xml"}
            for node in ct:
                _require(node.tag == ct_ns + "Default" and not len(node) and
                         set(node.attrib) == {"Extension", "ContentType"} and
                         types.pop(node.get("Extension"), None) == node.get("ContentType"))
        _require(model.tag == NS + "model" and model.attrib == {"unit": "millimeter"})
        entries = list(model)
        _require(3 <= len(entries) <= 6 and
                 entries[-2].tag == NS + "resources" and entries[-1].tag == NS + "build")
        meta, resources, build = entries[0], entries[-2], entries[-1]
        _require(meta.tag == NS + "metadata" and
                 meta.attrib == {"name": "slic3rpe:Version3mf"} and
                 meta.text == "1" and not len(meta))
        declared_paints = set()
        for header in entries[1:-2]:
            _require(header.tag == NS + "metadata" and not len(header) and
                     set(header.attrib) == {"name"} and (header.text or "").strip() == "2")
            name = header.get("name")
            _require(name in PAINT_HEADERS.values() and name not in declared_paints)
            declared_paints.add(name)
        _require(not resources.attrib and not build.attrib and 1 <= len(resources) <= 12
                 and len(build) == len(resources))
        _require(config.tag == "config" and not config.attrib and len(config) == len(resources))
        count = 0
        regions = 0
        observed_paints = set()
        for index, (obj, item, cfg) in enumerate(zip(resources, build, config), 1):
            oid = str(index)
            _require(obj.tag == NS + "object" and obj.attrib == {"id": oid, "type": "model"} and len(obj) == 1)
            _require(item.tag == NS + "item" and item.attrib == {"objectid": oid} and not len(item))
            mesh = obj[0]
            _require(mesh.tag == NS + "mesh" and not mesh.attrib and
                     [n.tag for n in mesh] == [NS + "vertices", NS + "triangles"])
            verts, faces = mesh
            _require(not verts.attrib and not faces.attrib and 3 <= len(verts) <= 3*LIMIT and len(faces) > 0)
            count += len(faces)
            _require(count <= LIMIT)
            for vertex in verts:
                _require(vertex.tag == NS + "vertex" and not len(vertex) and set(vertex.attrib) == {"x", "y", "z"})
                _require(all(math.isfinite(float(v)) and abs(float(v)) <= 20000 for v in vertex.attrib.values()))
            for face in faces:
                _require(face.tag == NS + "triangle" and not len(face) and
                         {"v1", "v2", "v3"}.issubset(face.attrib) and
                         set(face.attrib) <= {"v1", "v2", "v3", *PAINT_HEADERS})
                ids = [_integer(face.get(v), len(verts)-1) for v in ("v1", "v2", "v3")]
                _require(len(set(ids)) == 3)
                for key, val in face.attrib.items():
                    if key in PAINT_HEADERS:
                        _require(val in (("4",) if key.endswith("fuzzy_skin") else ("4", "8")))
                        observed_paints.add(PAINT_HEADERS[key])
            _require(cfg.tag == "object" and cfg.attrib == {"id": oid, "instances_count": "1"})
            metadata = [n for n in cfg if n.tag == "metadata"]
            volumes = [n for n in cfg if n.tag == "volume"]
            _require(len(metadata) + len(volumes) == len(cfg) and 1 <= len(volumes) <= 13)
            _settings(metadata, "object", {
                "perimeters", "fill_density", "top_solid_layers",
                "bottom_solid_layers", "external_perimeter_speed",
                "perimeter_speed", "infill_speed", "top_solid_infill_speed",
            })
            regions += len(volumes) - 1
            _require(regions <= 48)
            next_face = 0
            next_vertex = 0
            for n, vol in enumerate(volumes):
                _require(set(vol.attrib) == {"firstid", "lastid"})
                first = _integer(vol.get("firstid"), len(faces)-1)
                last = _integer(vol.get("lastid"), len(faces)-1)
                _require(first == next_face and first <= last)
                next_face = last + 1
                # A volume must own a disjoint contiguous vertex range.
                # Painted facet state attributes are NOT vertex references.
                ids = {int(face.get(axis)) for face in faces[first:last+1]
                       for axis in ("v1", "v2", "v3")}
                _require(min(ids) == next_vertex and len(ids) == max(ids)-min(ids)+1)
                next_vertex = max(ids)+1
                values = _settings(vol, "volume", {"volume_type", "perimeters", "fill_density", "top_solid_layers", "bottom_solid_layers"})
                role = values.pop("volume_type", None)
                _require((n == 0 and role == "ModelPart" and not values) or
                         (n > 0 and role == "NegativeVolume" and not values) or
                         (n > 0 and role == "ParameterModifier" and bool(values)))
            _require(next_face == len(faces) and next_vertex == len(verts))
        _require(observed_paints == declared_paints)
        layer_count = _validate_layer_ranges(layer_root, len(resources)) if layer_root is not None else 0
        return {"objects": len(resources), "triangles": count, "regions": regions,
                "layer_ranges": layer_count, "paint_channels": sorted(observed_paints)}
    except WorkerError:
        raise
    except (ValueError, TypeError, KeyError, OSError, RuntimeError, zipfile.BadZipFile, ET.ParseError):
        raise WorkerError("Invalid native Prusa 3MF archive.") from None
