"""Native Prusa 2.9.7 multi-tool deposition audit, independent of G-code headers.

Source STLs and tool identities must already be owner-resolved. A successful
Prusa MMU/XL CLI exit, T0/T1 tokens or prime tower alone does not prove that
each real printable object is extruded by its assigned native material.
Stationary priming and cross-object travel with E do not qualify as deposition.
This audit is read-only and does not authorise hardware printing.
"""
import math
import re

from .slicer_prusa_spatial_layers import _bounds

_WORD = re.compile(r"(?:^|\s)([XYZE])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)", re.I)
_T = re.compile(r"^T([0-7])(?:\s|$)", re.I)


def audit_prusa_native_object_tools(data, models, assignments, *,
                                    bed_width, bed_depth):
    """Qualify model-local positive extrusion against exact expected tools.

    This checks *per-model* identity for two to 200 independent models.
    Painted single-object colours need a different per-facet spatial auditor.
    """
    if (not isinstance(data, bytes) or not 0 < len(data) <= 90*1024*1024 or
            not isinstance(models, list) or not 2 <= len(models) <= 200 or
            not isinstance(assignments, (list, tuple)) or len(assignments) != len(models)
            or any(type(t) is not int or not 0 <= t <= 7 for t in assignments)
            or len(set(assignments)) < 2):
        raise ValueError("Invalid native Prusa multi-tool audit contract.")
    bounds = [_bounds(row, bed_width, bed_depth) for row in models]
    for i,a in enumerate(bounds):
        for b in bounds[i+1:]:
            if min(a[1],b[1]) > max(a[0],b[0])+.01 and (
                    min(a[3],b[3]) > max(a[2],b[2])+.01):
                raise ValueError("Overlapping Prusa model tool regions are ambiguous.")
    try:
        source = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("Native Prusa tool audit requires text G-code.") from None
    tool=None
    relative=False
    relative_xy=False
    e=0.
    x=y=None
    good=[0]*len(models)
    wrong=[0]*len(models)
    toolchanges=set()
    for idx,line in enumerate(source.splitlines()):
        if idx>=2_000_000 or len(line)>16384:
            raise ValueError("Prusa native toolpath audit line limit exceeded.")
        command=line.split(";",1)[0].strip()
        if not command:
            continue
        opcode=command.split(None,1)[0].upper()
        changed=_T.fullmatch(command)
        if changed:
            tool=int(changed.group(1))
            toolchanges.add(tool)
            continue
        if opcode.startswith("T") and opcode[1:].isdigit():
            raise ValueError("Prusa native G-code selected an unexpected tool.")
        if opcode not in ("M82","M83","G90","G91","G92","G0","G00","G1","G01"):
            continue
        words={key.upper():float(v) for key,v in _WORD.findall(command)}
        if any(not math.isfinite(v) or abs(v)>1e9 for v in words.values()):
            raise ValueError("Prusa native G-code contains invalid coordinates.")
        if opcode=="M82":
            relative=False
        elif opcode=="M83":
            relative=True
        elif opcode=="G90":
            relative_xy=False
        elif opcode=="G91":
            relative_xy=True
        elif opcode=="G92":
            e=words.get("E",e)
            x=words.get("X",x)
            y=words.get("Y",y)
        else:
            old_x,old_y=x,y
            if relative_xy:
                x=x+words["X"] if x is not None and "X" in words else (None if "X" in words else x)
                y=y+words["Y"] if y is not None and "Y" in words else (None if "Y" in words else y)
            else:
                x=words.get("X",x)
                y=words.get("Y",y)
            if "E" not in words:
                continue
            delta=words["E"] if relative else words["E"]-e
            e=e+words["E"] if relative else words["E"]
            if (delta<=1e-6 or opcode not in ("G1","G01") or
                    x is None or y is None or old_x is None or old_y is None or
                    abs(x-old_x)+abs(y-old_y)<=1e-7):
                continue
            for i,(xmin,xmax,ymin,ymax,_zmin,_zmax) in enumerate(bounds):
                if (xmin-.12 <= x <= xmax+.12 and ymin-.12 <= y <= ymax+.12
                        and xmin-.12 <= old_x <= xmax+.12
                        and ymin-.12 <= old_y <= ymax+.12):
                    if tool==assignments[i]:
                        good[i]+=1
                    else:
                        wrong[i]+=1
    for i,t in enumerate(assignments):
        if (t not in toolchanges or good[i]<20 or
                wrong[i] > max(2,math.floor(good[i]*.01))):
            raise ValueError("Native Prusa G-code did not prove the assigned model tools.")
    return {"objects":len(models),"distinct_tools":len(toolchanges),
            "correct_deposition_moves":good,"incorrect_deposition_moves":wrong}
