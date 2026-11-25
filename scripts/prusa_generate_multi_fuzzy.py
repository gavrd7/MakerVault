"""Isolate selective Prusa fuzzy skin between two printable 3MF objects."""
from pathlib import Path
import sys

from core.slicer_prusa_3mf import build_prusa_native_3mf
from core.slicer_native_support_paint import _fingerprint
from core.slicer_plate_3mf import _triangles
from scripts.prusa_real_binary_smoke import cube_stl


def main(destination):
    folder=Path(destination)
    folder.mkdir(parents=True,exist_ok=True)
    source=cube_stl()
    tris=list(_triangles(source))
    minimum=[min(p[i] for t in tris for p in t) for i in range(3)]
    maximum=[max(p[i] for t in tris for p in t) for i in range(3)]
    pivot=((minimum[0]+maximum[0])/2,
           (minimum[1]+maximum[1])/2,minimum[2])
    local=[[tuple(p[i]-pivot[i] for i in range(3)) for p in face] for face in tris]
    face_ids=[i for i,face in enumerate(local)
              if all(abs(v[1]+10)<1e-5 for v in face)]
    if len(face_ids)!=2:
        raise ValueError("Fuzzy skin fixture needs two front-wall facets.")
    paint={"version":2,"signature":_fingerprint(local),
           "regions":[{"slot":0,"patches":[
               {"face":i,"polygon":[list(vertex) for vertex in local[i]]}
               for i in face_ids]}]}
    left={"asset_id":"owned-left","x_mm":-35,"y_mm":0,"z_mm":0,
          "rotation_deg":0,"scale_percent":100}
    right={"asset_id":"owned-right","x_mm":35,"y_mm":0,"z_mm":0,
           "rotation_deg":0,"scale_percent":100}
    for name,selected in (("baseline",None),("left",0),("right",1)):
        rows=[(dict(left),source),(dict(right),source)]
        if selected is not None:
            row=dict(rows[selected][0])
            row["fuzzy_skin_paint"]=paint
            rows[selected]=(row,source)
        (folder/(name+".3mf")).write_bytes(build_prusa_native_3mf(
            rows,bed_width=250,bed_depth=210))


if __name__=="__main__":
    main(sys.argv[1])
