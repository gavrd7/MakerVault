"""Six upstream-compatible native primitive volume shapes, real CLI fixtures."""
from pathlib import Path
import sys
import uuid

from core.slicer_prusa_3mf import build_prusa_native_3mf
from core.slicer_modifier_volumes import PRIMITIVE_SHAPES
from scripts.prusa_real_binary_smoke import cube_stl

SHAPES=tuple(sorted(PRIMITIVE_SHAPES))


def main(folder):
    path=Path(folder)
    path.mkdir(parents=True,exist_ok=True)
    model=cube_stl()
    base={"asset_id":"owned-cube","x_mm":0,"y_mm":0,"z_mm":0,
          "scale_percent":100,"rotation_deg":0}
    (path/"baseline.3mf").write_bytes(build_prusa_native_3mf(
        [(base,model)],bed_width=250,bed_depth=210))
    for shape in SHAPES:
        for kind in ("modifier","negative"):
            modifier={
                "id":str(uuid.uuid5(uuid.NAMESPACE_DNS,"prusa-"+shape+"-"+kind)),
                "shape":shape,"kind":kind,
                "width_mm":12,"depth_mm":12,"height_mm":20,
                "x_mm":0,"y_mm":0,"z_mm":10,
                "settings":{"sparse_infill_density":85} if kind=="modifier" else {},
            }
            native=build_prusa_native_3mf([
                ({**base,"modifier_volumes":[modifier]},model)
            ],bed_width=250,bed_depth=210)
            (path/(shape+"-"+kind+".3mf")).write_bytes(native)


if __name__=="__main__":
    main(sys.argv[1])
