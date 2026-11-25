"""Deterministic watertight cantilever support painting native Prusa fixtures."""
import io
from pathlib import Path
import struct
import sys
import zipfile
from xml.etree import ElementTree as ET

from core.slicer_prusa_3mf import build_prusa_native_3mf
from core.slicer_native_support_paint import _fingerprint
from core.slicer_plate_3mf import _triangles


def cantilever():
    # L-section, elevated underside 10..30mm; slope intersects real slabs.
    outline = [(0., 0.), (10., 0.), (10., 19.), (30., 23.),
               (30., 25.), (0., 25.)]
    caps = ((0, 1, 2), (0, 2, 5), (2, 3, 4), (2, 4, 5))
    faces = []
    for a, b, c in caps:
        for y, nodes in ((0., (a, b, c)), (12., (c, b, a))):
            faces.append(tuple((outline[i][0], y, outline[i][1]) for i in nodes))
    for i, a in enumerate(outline):
        b = outline[(i+1) % len(outline)]
        a0,b0 = (a[0],0.,a[1]), (b[0],0.,b[1])
        a1,b1 = (a[0],12.,a[1]), (b[0],12.,b[1])
        faces.extend(((a0,b1,b0),(a0,a1,b1)))
    out = bytearray(b"Prusa support acceptance cantilever".ljust(80,b"\0"))
    out.extend(struct.pack("<I",len(faces)))
    for face in faces:
        out.extend(struct.pack("<12fH",0,0,0,
                  *(p for v in face for p in v),0))
    return bytes(out)


def support_mask(raw):
    tris = list(_triangles(raw))
    mins = [min(p[i] for t in tris for p in t) for i in range(3)]
    maxs = [max(p[i] for t in tris for p in t) for i in range(3)]
    pivot = ((mins[0]+maxs[0])/2,(mins[1]+maxs[1])/2,mins[2])
    local = [[tuple(p[i]-pivot[i] for i in range(3)) for p in face]
             for face in tris]
    patches = []
    for index, tri in enumerate(tris):
        # Only the sloping, downward cantilever underside faces.
        if not (all(p[0] >= 10-1e-5 and
                    abs(p[2] - (19+(p[0]-10)*.2)) < 1e-5 for p in tri)
                and sum(p[0] for p in tri)/3 > 13):
            continue
        a,b,c = tri
        if (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]) >= 0:
            continue
        center = [sum(p[i] for p in tri)/3 for i in range(3)]
        polygon = [[.98*vertex[i]+.02*center[i]-pivot[i] for i in range(3)]
                   for vertex in tri]
        patches.append({"face": index, "polygon": polygon})
    if len(patches) != 2:
        raise ValueError("Support fixture must paint two downward facets.")
    return {"version": 2, "signature": _fingerprint(local),
            "regions": [{"slot": 0, "patches": patches}]}


def unpainted_geometry_control(raw):
    src, dst = io.BytesIO(raw), io.BytesIO()
    ns = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
    pn = "{http://schemas.slic3r.org/3mf/2017/06}"
    with zipfile.ZipFile(src) as inp, zipfile.ZipFile(dst,"w") as out:
        for name in inp.namelist():
            data=inp.read(name)
            if name == "3D/3dmodel.model":
                model=ET.fromstring(data)
                for meta in model.findall(ns+"metadata"):
                    if meta.get("name")=="slic3rpe:FdmSupportsPaintingVersion":
                        model.remove(meta)
                for triangle in model.findall(".//"+ns+"triangle"):
                    triangle.attrib.pop(pn+"custom_supports",None)
                data=ET.tostring(model,encoding="utf-8",xml_declaration=True)
            out.writestr(name,data)
    return dst.getvalue()


def main(folder):
    output=Path(folder)
    output.mkdir(parents=True,exist_ok=True)
    source=cantilever()
    item={"asset_id":"cantilever","x_mm":0,"y_mm":0,"z_mm":0,
          "scale_percent":100,"rotation_deg":0}
    plain=build_prusa_native_3mf([(item,source)],bed_width=250,bed_depth=210)
    painted=build_prusa_native_3mf([({**item,"support_paint":support_mask(source)},source)],
                                   bed_width=250,bed_depth=210)
    (output/"baseline.3mf").write_bytes(plain)
    (output/"geometry-control.3mf").write_bytes(unpainted_geometry_control(painted))
    (output/"enforced.3mf").write_bytes(painted)


if __name__=="__main__":
    main(sys.argv[1])
