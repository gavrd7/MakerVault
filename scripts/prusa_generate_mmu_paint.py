"""Research-only Prusa 2.9.7 MMU facet-paint projects.

Use the actual Prusa triangle state namespace and the common fingerprint-
checked maker patch splitter. These archives are intentionally rejected by
the production single-material worker until native tool/filament mapping and
purge/print submission are independently accepted.
"""
import io
from pathlib import Path
import struct
import sys
import zipfile
from defusedxml import ElementTree as SafeET
from xml.etree import ElementTree as ET

from core.slicer_native_support_paint import (
    _fingerprint, native_combined_paint_triangles,
)
from core.slicer_plate_3mf import _triangles
from core.slicer_prusa_3mf import build_prusa_native_3mf
from scripts.prusa_real_binary_smoke import cube_stl

M = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
P = "{http://schemas.slic3r.org/3mf/2017/06}"


def fixture(*, include_paint=False):
    source = cube_stl()
    triangles = list(_triangles(source))
    lower = [min(p[i] for tri in triangles for p in tri) for i in range(3)]
    upper = [max(p[i] for tri in triangles for p in tri) for i in range(3)]
    centre = ((lower[0]+upper[0])/2, (lower[1]+upper[1])/2, lower[2])
    local = [[tuple(p[i]-centre[i] for i in range(3)) for p in tri]
             for tri in triangles]
    patches = [{"face": i, "polygon": [[float(v[j]) for j in range(3)]
                                      for v in face]}
               for i,face in enumerate(local)
               if all(abs(vertex[1]+10)<1e-5 for vertex in face)]
    if len(patches)!=2:
        raise ValueError("MMU paint fixture must contain exactly two front wall facets.")
    paint = {"version": 2, "signature": _fingerprint(local),
             "palette": [{"color": "#ff8000", "label": "native tool 0"},
                         {"color": "#3ec0ff", "label": "native tool 1"}],
             "regions": [{"slot": 1, "patches": patches}]}
    painted = native_combined_paint_triangles(
        triangles, colour=paint, colour_tool_indices={1:1})
    out = bytearray(b"MakerVault native Prusa MMU painted fixture".ljust(80,b"\0"))
    out.extend(struct.pack("<I",len(painted)))
    attrs=[]
    for triangle,tags in painted:
        out.extend(struct.pack("<12fH",0,0,0,
                   *(float(n) for vertex in triangle for n in vertex),0))
        attrs.append(tags)
    result = (source, bytes(out), attrs)
    return (*result, paint) if include_paint else result


def append_native_colour(source, attrs):
    result=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source)) as zin, zipfile.ZipFile(result,"w",
                     compression=zipfile.ZIP_DEFLATED) as zout:
        for name in zin.namelist():
            raw=zin.read(name)
            if name == "3D/3dmodel.model":
                model=SafeET.fromstring(raw)
                # ElementTree drops unused namespace declarations on parse.
                # Retain the exact prefix required by Prusa Expat import.
                model.set("xmlns:slic3rpe", "http://schemas.slic3r.org/3mf/2017/06")
                before=model.find(M+"resources")
                if before is None:
                    raise ValueError("Missing Prusa resource table")
                index=list(model).index(before)
                meta=ET.Element(M+"metadata", {"name":"slic3rpe:MmPaintingVersion"})
                meta.text="2"
                model.insert(index,meta)
                triangles=model.findall("./"+M+"resources/"+M+"object/"+M+"mesh/"+M+"triangles/"+M+"triangle")
                if len(triangles)!=len(attrs):
                    raise ValueError("MMU native paint triangulation mismatch.")
                for face,tags in zip(triangles,attrs):
                    value=tags.get("paint_color")
                    if value is not None:
                        # Prusa 2.9.7 TriangleStateType::Extruder2 = 2,
                        # with the unsplit leaf nibble 2 << 2 = 0x8.
                        # ModelVolume::get_extruders_from_multi_material_painting
                        # maps state index 2 to zero-based tool T1, not T0.
                        # Keep the literal slic3rpe prefix for Prusa's importer.
                        face.set("slic3rpe:mmu_segmentation", value)
                raw=ET.tostring(model,encoding="utf-8",xml_declaration=True)
            if name=="Metadata/Slic3r_PE_model.config":
                root=SafeET.fromstring(raw)
                vol=root.find("./object/volume")
                if vol is None:
                    raise ValueError("Prusa object volume missing")
                ET.SubElement(vol,"metadata",{"type":"volume","key":"extruder","value":"1"})
                raw=ET.tostring(root,encoding="utf-8",xml_declaration=True)
            zout.writestr(name,raw)
    return result.getvalue()


def main(dest):
    folder=Path(dest)
    folder.mkdir(parents=True,exist_ok=True)
    base,painted,states,paint=fixture(include_paint=True)
    row={"asset_id":"synthetic-mm3-painted","x_mm":0,"y_mm":0,"z_mm":0,
         "rotation_deg":0,"scale_percent":100}
    control=build_prusa_native_3mf([(row,base)],bed_width=250,bed_depth=210)
    from core.slicer_prusa_colour_project import build_prusa_colour_candidate
    candidate=build_prusa_colour_candidate(
        {**row,"colour_paint":paint},base,
        printer_ini=(b"bed_shape = 0x0,250x0,250x210,0x210\n"
                     b"nozzle_diameter = 0.4,0.4,0.4,0.4,0.4\n"
                     b"single_extruder_multi_material = 1\n"),
        colour_tool_indices={1:1},bed_width=250,bed_depth=210)
    (folder/"baseline.3mf").write_bytes(control)
    (folder/"colour.3mf").write_bytes(candidate)
    print("Generated native Prusa MMU colour mask over",sum(
        "paint_color" in state for state in states),"triangle facets.")


if __name__=="__main__":
    main(sys.argv[1])
