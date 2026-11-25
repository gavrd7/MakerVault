"""Prusa 2.9.7 two-object selective fuzzy skin extrusion acceptance.

A syntactically valid 3MF facet flag does not prove native surface texture.
Check real short positive-E external-wall movements independently in the
painted object's XY footprint and in the unchanged neighbouring object.
"""
import math
import re

from .slicer_prusa_spatial_layers import _bounds

_WORD=re.compile(r"(?:^|\s)([XYZE])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)",re.I)


def audit_prusa_two_object_fuzzy(data, models, *, bed_width, bed_depth):
    if (not isinstance(data,bytes) or not 0<len(data)<=90*1024*1024 or
            not isinstance(models,list) or len(models)!=2):
        raise ValueError("Prusa selective fuzzy acceptance requires two source models.")
    painted=[i for i,(item,_raw) in enumerate(models) if isinstance(item,dict)
             and (item.get("fuzzy_skin_paint") or {}).get("regions")]
    if len(painted)!=1:
        raise ValueError("Prusa selective fuzzy acceptance needs exactly one painted object.")
    if any((item.get("support_paint") or {}).get("regions") or
           (item.get("seam_paint") or {}).get("regions") or
           item.get("modifier_volumes") or
           (item.get("variable_layer_profile") or {}).get("bands")
           for item,_raw in models):
        raise ValueError("Prusa two-object fuzzy with other native features is unqualified.")
    limits=[_bounds(source,bed_width,bed_depth) for source in models]
    a,b=limits
    if min(a[1],b[1])>max(a[0],b[0])+.01 and min(a[3],b[3])>max(a[2],b[2])+.01:
        raise ValueError("Overlapping model footprints cannot prove regional fuzzy skin.")
    try:
        lines=data.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise ValueError("Prusa fuzzy audit requires text G-code.") from None
    pos={"X":None,"Y":None,"Z":None}
    e=0.
    relative=False
    role=""
    counts=[0,0]
    for idx,line in enumerate(lines):
        if idx>=2_000_000 or len(line)>16384:
            raise ValueError("Prusa fuzzy toolpath audit exceeds input limits.")
        stripped=line.strip()
        if stripped.startswith(";TYPE:"):
            role=stripped.partition(":")[2].strip().lower()
        cmd=stripped.split(";",1)[0].strip()
        if not cmd:
            continue
        op=cmd.split(None,1)[0].upper()
        if op not in ("M82","M83","G92","G0","G00","G1","G01"):
            continue
        words={k.upper():float(v) for k,v in _WORD.findall(cmd)}
        if any(not math.isfinite(value) or abs(value)>1e9 for value in words.values()):
            raise ValueError("Native Prusa fuzzy G-code coordinate is invalid.")
        if op=="M82":
            relative=False
        elif op=="M83":
            relative=True
        elif op=="G92":
            e=words.get("E",e)
        else:
            start=pos.copy()
            pos.update({k:value for k,value in words.items() if k in pos})
            if "E" not in words:
                continue
            delta=words["E"] if relative else words["E"]-e
            e=e+words["E"] if relative else words["E"]
            if (delta<=1e-6 or "external perimeter" not in role or
                    any(start[k] is None or pos[k] is None for k in ("X","Y","Z"))):
                continue
            length=math.hypot(pos["X"]-start["X"],pos["Y"]-start["Y"])
            if not .01<=length<=1.25:
                continue
            middle=((start["X"]+pos["X"])/2,(start["Y"]+pos["Y"])/2)
            for i,(xmin,xmax,ymin,ymax,zmin,zmax) in enumerate(limits):
                if (xmin-.1<=middle[0]<=xmax+.1 and
                        ymin-.1<=middle[1]<=ymax+.1 and
                        max(2.,zmin+.5)<=pos["Z"]<=min(zmax-1.,zmin+20)):
                    counts[i]+=1
    changed=counts[painted[0]]
    untouched=counts[1-painted[0]]
    if changed<80 or untouched>max(5,math.floor(changed*.05)):
        raise ValueError("Prusa native fuzzy wall effect was not isolated to the painted object.")
    return {"painted_model_index":painted[0],"painted_short_external_moves":changed,
            "unpainted_short_external_moves":untouched}
