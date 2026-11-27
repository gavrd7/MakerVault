"""Two-object support-paint research: each object has its own native facets."""
from pathlib import Path
import sys

from core.slicer_prusa_3mf import build_prusa_native_3mf
from scripts.prusa_generate_support_overhang import cantilever, support_mask


def main(destination):
    folder=Path(destination)
    folder.mkdir(parents=True,exist_ok=True)
    raw=cantilever()
    left={"asset_id":"verified-left","x_mm":-50,"y_mm":0,
          "z_mm":0,"rotation_deg":0,"scale_percent":100}
    right={"asset_id":"verified-right","x_mm":50,"y_mm":0,
           "z_mm":0,"rotation_deg":0,"scale_percent":100}
    for label, painted in (("baseline",None),("left",0),("right",1)):
        parts=[(dict(left),raw),(dict(right),raw)]
        if painted is not None:
            entry=dict(parts[painted][0])
            entry["support_paint"]=support_mask(raw,0)
            parts[painted]=(entry,raw)
        archive=build_prusa_native_3mf(parts,bed_width=250,bed_depth=210)
        (folder/(label+".3mf")).write_bytes(archive)


if __name__=="__main__":
    main(sys.argv[1])
