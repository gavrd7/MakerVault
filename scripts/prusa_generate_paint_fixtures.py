"""Generate isolated PrusaSlicer native painted facet import-acceptance cases."""
from pathlib import Path
import sys

from core.slicer_prusa_3mf import build_prusa_native_3mf
from core.slicer_plate_3mf import _triangles
from core.slicer_native_support_paint import _fingerprint
from scripts.prusa_real_binary_smoke import cube_stl


def main(directory):
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    raw = cube_stl()
    triangles = list(_triangles(raw))
    bounds = [
        (min(v[i] for tri in triangles for v in tri),
         max(v[i] for tri in triangles for v in tri)) for i in range(3)
    ]
    centre = ((bounds[0][0]+bounds[0][1])/2,
              (bounds[1][0]+bounds[1][1])/2, bounds[2][0])
    local = [[tuple(float(v[i])-centre[i] for i in range(3)) for v in tri]
             for tri in triangles]
    # Use an inward, coplanar patch with source-correct winding.
    first = local[0]
    midpoint = [sum(v[i] for v in first)/3 for i in range(3)]
    patch = [[(v[i]+midpoint[i])/2 for i in range(3)] for v in first]
    signature = _fingerprint(local)
    def painted(slot):
        return {"version": 2, "signature": signature,
                "regions": [{"slot": slot,
                             "patches": [{"face": 0, "polygon": patch}]}]}
    base = {"asset_id": "verified-cube", "x_mm": 0, "y_mm": 0,
            "z_mm": 0, "rotation_deg": 0, "scale_percent": 100}
    for name, edits in (
        ("baseline", {}),
        ("support", {"support_paint": painted(0)}),
        ("seam", {"seam_paint": painted(1)}),
        ("fuzzy", {"fuzzy_skin_paint": painted(0)}),
        ("combined", {"support_paint": painted(0),
                      "seam_paint": painted(1),
                      "fuzzy_skin_paint": painted(0)}),
    ):
        archive = build_prusa_native_3mf([({**base, **edits}, raw)],
                                         bed_width=250, bed_depth=210)
        (root / (name + ".3mf")).write_bytes(archive)

if __name__ == "__main__":
    main(sys.argv[1])
