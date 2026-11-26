"""Stream plain single-material multi-source Orca plates into one core 3MF mesh.

Unlike the regular DOM/compound exporter, this route holds at most one
individually verified source mesh in Python memory. It preserves every
instance's exact baked transform, even when all source STLs are different.
The worker's dedicated streamed-core validator checks the result again.
"""
import io
import math
import tempfile
import zipfile
from xml.etree import ElementTree as ET
from defusedxml import ElementTree as SafeET

from .slicer_plate_3mf import NS, build_plate_3mf, _bake_native_instance_transform
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
    memory = _available_bytes()
    if memory is None:
        raise SlicerProfileError("Available memory cannot be verified for a large Orca plate.")
    # Budget native mesh construction independently of compact ZIP size. This
    # is admission based on actual headroom rather than a hardcoded face cap.
    budget = max(0, memory - 256 * 1024 * 1024) // 4
    estimated = 0
    offset = 0
    compressed = io.BytesIO()
    q = "{" + NS + "}"
    with tempfile.TemporaryFile(mode="w+b") as faces:
        with zipfile.ZipFile(compressed, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6, allowZip64=True) as archive:
            with archive.open("3D/3dmodel.model", "w", force_zip64=True) as stream:
                stream.write((
                    '<?xml version="1.0" encoding="utf-8"?>'
                    '<model xmlns="' + NS + '" unit="millimeter" xml:lang="en-US">'
                    '<resources><object id="1" type="model"><mesh><vertices>'
                ).encode())
                for index, (item, raw) in enumerate(objects_with_stl, 1):
                    # Existing single-object path preserves exactly the
                    # inspected pivot, transforms, bounds and float rounding.
                    source = build_plate_3mf(
                        [(item, raw)], bed_width=bed_width, bed_depth=bed_depth)
                    with zipfile.ZipFile(io.BytesIO(source)) as packaged:
                        root = SafeET.fromstring(packaged.read("3D/3dmodel.model"))
                    obj = root.find("./"+q+"resources/"+q+"object")
                    placement = root.find("./"+q+"build/"+q+"item")
                    if obj is None or placement is None:
                        raise SlicerProfileError("Streamed Orca source has no verified mesh.")
                    _bake_native_instance_transform(obj, placement.attrib["transform"])
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
