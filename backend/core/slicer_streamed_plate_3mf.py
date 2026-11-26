"""Stream plain single-material multi-source Orca plates into one core 3MF mesh.

Unlike the regular DOM/compound exporter, this route holds at most one
individually verified source mesh in Python memory. It preserves every
instance's exact baked transform, even when all source STLs are different.
The worker's dedicated streamed-core validator checks the result again.
"""
import io
import hashlib
import copy
import math
import tempfile
import zipfile
from xml.etree import ElementTree as ET

from .slicer_plate_3mf import (NS, _render_mesh, _validated_mesh_placement,
    _bake_native_instance_transform)
from .slicer_resource_budget import input_model_budget, source_input_budget, plate_triangle_budget
from .slicer_profiles import SlicerProfileError
from .slicer_resource_budget import _cgroup_available_bytes, _host_available_bytes

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
    '</Types>'
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
    'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
    '</Relationships>'
)


def _available_bytes():
    values = [v for v in (_cgroup_available_bytes(), _host_available_bytes())
              if v is not None]
    return min(values) if values else None


def build_streamed_compound_3mf(objects_with_stl, *, bed_width, bed_depth):
    """Return a compressed, placement-baked 3MF using O(one mesh) XML memory.

    All geometries are validated via the existing per-source exporter. No
    fixed *total* plate triangle or expanded-XML ceiling applies here; the
    estimated native processing memory must fit the observed local headroom.
    """
    if not isinstance(objects_with_stl, list) or not 2 <= len(objects_with_stl) <= 200:
        raise SlicerProfileError("Streamed Orca plate needs two to 200 models.")
    if any(not isinstance(pair, tuple) or len(pair) != 2
           or not isinstance(pair[0], dict) or not isinstance(pair[1], bytes)
           or any(pair[0].get(k) for k in (
               "modifier_volumes", "process_overrides", "colour_paint",
               "support_paint", "seam_paint", "fuzzy_skin_paint",
               "variable_layer_profile")) for pair in objects_with_stl):
        raise SlicerProfileError("Streamed Orca geometry requires plain single-material models.")
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
               and math.isfinite(v) and 1 <= v <= 1000 for v in (bed_width, bed_depth)):
        raise SlicerProfileError("Verified positive build plate size is required.")
    memory = _available_bytes()
    if memory is None:
        raise SlicerProfileError("Available memory cannot be verified for a large Orca plate.")
    # Budget native mesh construction independently of compact ZIP size. This
    # is admission based on actual headroom rather than a hardcoded face cap.
    budget = max(0, memory - 256 * 1024 * 1024) // 4
    estimated = 0
    source_budget = source_input_budget(upper_cap=input_model_budget())
    last_identity = None
    template = None
    offset = 0
    compressed = io.BytesIO()
    q = "{" + NS + "}"
    with tempfile.TemporaryFile(mode="w+b") as faces:
        with zipfile.ZipFile(compressed, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=1, allowZip64=True) as archive:
            with archive.open("3D/3dmodel.model", "w", force_zip64=True) as stream:
                stream.write((
                    '<?xml version="1.0" encoding="utf-8"?>'
                    '<model xmlns="' + NS + '" unit="millimeter" xml:lang="en-US">'
                    '<resources><object id="1" type="model"><mesh><vertices>'
                ).encode())
                for index, (item, raw) in enumerate(objects_with_stl, 1):
                    # Cache only the most recent unplaced mesh, keeping the
                    # working set bounded even for entirely distinct sources.
                    if estimated >= budget:
                        raise SlicerProfileError(
                            "Full-plate geometry exceeds available native slicing memory.")
                    identity = (len(raw), hashlib.sha256(raw).digest())
                    if len(raw) > source_budget:
                        raise SlicerProfileError("Source model exceeds available preparation memory.")
                    if identity != last_identity:
                        template = None
                        template = ET.Element(q + "object")
                        count, _, _ = _render_mesh(raw, template)
                        if count > plate_triangle_budget():
                            raise SlicerProfileError("Source mesh exceeds available preparation memory.")
                        last_identity = identity
                    obj = copy.deepcopy(template)
                    placement = _validated_mesh_placement(
                        obj, item, bed_width, bed_depth, index)
                    _bake_native_instance_transform(obj, placement)
                    vertices = obj.findall("./"+q+"mesh/"+q+"vertices/"+q+"vertex")
                    triangles = obj.findall("./"+q+"mesh/"+q+"triangles/"+q+"triangle")
                    estimated += len(vertices) * 120 + len(triangles) * 240
                    if estimated > budget:
                        raise SlicerProfileError(
                            "Full-plate geometry exceeds available native slicing memory.")
                    for vertex in vertices:
                        coords = [vertex.attrib[a] for a in ("x", "y", "z")]
                        if not all(math.isfinite(float(v)) for v in coords):
                            raise SlicerProfileError("Non-finite streamed Orca vertex.")
                        stream.write(('<vertex x="' + coords[0] + '" y="' + coords[1]
                                      + '" z="' + coords[2] + '"/>').encode())
                    for face in triangles:
                        try:
                            ids = [int(face.attrib[a]) for a in ("v1", "v2", "v3")]
                        except (ValueError, KeyError):
                            raise SlicerProfileError("Invalid streamed Orca triangle.") from None
                        if any(v < 0 or v >= len(vertices) for v in ids):
                            raise SlicerProfileError("Out-of-range streamed Orca vertex reference.")
                        faces.write(('<triangle v1="%d" v2="%d" v3="%d"/>' %
                                     tuple(v + offset for v in ids)).encode())
                    offset += len(vertices)
                if offset == 0:
                    raise SlicerProfileError("Empty streamed Orca plate.")
                stream.write(b'</vertices><triangles>')
                faces.seek(0)
                while chunk := faces.read(256 * 1024):
                    stream.write(chunk)
                stream.write(
                    b'</triangles></mesh></object></resources><build>'
                    b'<item objectid="1" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>'
                    b'</build></model>'
                )
            archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
            archive.writestr("_rels/.rels", _RELS)
    result = compressed.getvalue()
    # This estimate includes the ZIP, base64/JSON envelope and in-flight
    # worker buffers. It is intentionally independent of source model count.
    if len(result) * 8 > budget:
        raise SlicerProfileError("Full-plate transport exceeds available preparation memory.")
    return result
