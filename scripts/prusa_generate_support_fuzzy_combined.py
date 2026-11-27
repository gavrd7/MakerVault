"""Generate same-geometry Prusa support/fuzzy native qualification projects."""
from pathlib import Path
import sys

from core.slicer_prusa_3mf import build_prusa_native_3mf
from core.slicer_native_support_paint import _fingerprint
from core.slicer_plate_3mf import _triangles
from scripts.prusa_generate_support_overhang import cantilever, support_mask


def main(folder):
    output = Path(folder)
    output.mkdir(parents=True, exist_ok=True)
    raw = cantilever()
    triangles = list(_triangles(raw))
    lows = [min(p[a] for tri in triangles for p in tri) for a in range(3)]
    highs = [max(p[a] for tri in triangles for p in tri) for a in range(3)]
    pivot = ((lows[0] + highs[0])/2, (lows[1] + highs[1])/2, lows[2])
    local = [[tuple(float(point[a]) - pivot[a] for a in range(3))
              for point in tri] for tri in triangles]
    front = [index for index, tri in enumerate(triangles)
             if all(abs(p[1] - lows[1]) < 1e-5 for p in tri)
             and max(p[2] for p in tri) - min(p[2] for p in tri) > 3]
    if len(front) < 2:
        raise ValueError("No independent front cantilever wall for selective fuzzy skin.")
    fuzzy = {"version": 2, "signature": _fingerprint(local),
             "regions": [{"slot": 0, "patches": [
                 {"face": index,
                  "polygon": [list(point) for point in local[index]]}
                 for index in front]}]}
    support = support_mask(raw)
    overlap = {patch["face"] for region in support["regions"]
               for patch in region["patches"]} & set(front)
    if overlap:
        raise ValueError("Support and fuzzy paint test facets overlap.")
    base = {"asset_id": "prusa-combined-support-fuzzy", "x_mm": 0,
            "y_mm": 0, "z_mm": 0, "rotation_deg": 0, "scale_percent": 100}
    for label, edits in (
        ("baseline", {}),
        ("support", {"support_paint": support}),
        ("fuzzy", {"fuzzy_skin_paint": fuzzy}),
        ("combined", {"support_paint": support, "fuzzy_skin_paint": fuzzy}),
    ):
        project = build_prusa_native_3mf(
            [({**base, **edits}, raw)], bed_width=250, bed_depth=210)
        (output / (label + ".3mf")).write_bytes(project)


if __name__ == "__main__":
    main(sys.argv[1])
