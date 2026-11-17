"""Engine-neutral prioritisation for a bounded whole-print G-code overview.

Only affects visual preview; complete G-code and single-layer inspection retain
every native extrusion move. Priority follows visual shell significance.
"""

def overview_priority(feature):
    name = str(feature or "").lower().strip()
    if any(value in name for value in ("outer wall", "external perimeter", "external wall", "outer perimeter")):
        return 0
    if any(value in name for value in ("top surface", "top solid", "top skin", "top fill", "bridge", "overhang")):
        return 1
    if "support" in name and any(value in name for value in ("interface", "roof", "contact", "floor")):
        return 2
    if "support" in name:
        return 3
    if any(value in name for value in ("inner wall", "internal perimeter", "wall", "perimeter")):
        return 4
    if any(value in name for value in ("brim", "skirt", "prime tower", "wipe tower")):
        return 5
    if any(value in name for value in ("solid infill", "bottom solid", "bottom surface")):
        return 6
    if any(value in name for value in ("infill", "fill", "sparse")):
        return 7
    return 8
