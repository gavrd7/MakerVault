"""Audit independent Prusa 2.9.7 object layer schedules from XY-region G-code.

Native Prusa emits one interleaved G-code file for multiple objects. Auditing
only global ;Z increments can falsely approve per-object variable layer edits.
Require actual positive extrusion at each model's own native Z coordinates.
"""
import math
import re
import struct

from .slicer_prusa_plate import build_prusa_placed_stl
from .slicer_variable_layers import validate_variable_layer_profile

_WORD = re.compile(r"(?:^|\s)([XYZE])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)", re.I)
_Z = re.compile(r"^;\s*Z:\s*(\d+(?:\.\d+)?)\s*$", re.I)
_OMIT = frozenset(("variable_layer_profile","process_overrides","modifier_volumes",
                   "support_paint","seam_paint","fuzzy_skin_paint","colour_paint"))


def _bounds(source, bed_width, bed_depth):
    item, raw = source
    geometric = {k: v for k,v in item.items() if k not in _OMIT}
    baked = build_prusa_placed_stl([(geometric,raw)],
                                    bed_width=bed_width,bed_depth=bed_depth)
    count = struct.unpack_from("<I", baked, 80)[0]
    if not count:
        raise ValueError("Prusa object mesh has no triangles.")
    xs,ys,zs = [],[],[]
    for tri in struct.iter_unpack("<12fH", baked[84:]):
        for pos in (3,6,9):
            xs.append(tri[pos])
            ys.append(tri[pos+1])
            zs.append(tri[pos+2])
    return (min(xs),max(xs),min(ys),max(ys),min(zs),max(zs))


def audit_prusa_multi_object_layer_ranges(gcode, sources, *, bed_width,
                                          bed_depth, base_layer_mm):
    """Return verified bands after independently inspecting each object.

    The profile's ordinary layer height is also checked on objects with no
    variable band, so an edit on one model cannot silently alter its neighbour.
    """
    if (not isinstance(gcode, bytes) or not 0 < len(gcode) <= 90*1024*1024 or
            not isinstance(sources, list) or not 2 <= len(sources) <= 12 or
            type(base_layer_mm) not in (int,float) or not math.isfinite(base_layer_mm)
            or not .05 <= base_layer_mm <= .5):
        raise ValueError("Invalid native Prusa multi-object layer audit.")
    footprints = [_bounds(row,bed_width,bed_depth) for row in sources]
    for i, a in enumerate(footprints):
        for b in footprints[i+1:]:
            if min(a[1],b[1]) > max(a[0],b[0])+.01 and (
                    min(a[3],b[3]) > max(a[2],b[2])+.01):
                raise ValueError("Overlapping object XY bounds cannot be independently audited.")
    try:
        lines = gcode.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise ValueError("Native Prusa output is not UTF-8.") from None
    zones = [set() for _ in sources]
    z=x=y=None
    e=0.
    relative=False
    for i,line in enumerate(lines):
        if i>=2_000_000 or len(line)>16384:
            raise ValueError("Native Prusa layer audit exceeds bounds.")
        match=_Z.fullmatch(line.strip())
        if match:
            z=float(match.group(1))
        command=line.split(";",1)[0].strip()
        if not command:
            continue
        op=command.split(None,1)[0].upper()
        if op not in ("M82","M83","G92","G0","G00","G1","G01"):
            continue
        words={k.upper():float(v) for k,v in _WORD.findall(command)}
        if any(not math.isfinite(v) or abs(v)>20000 for k,v in words.items()
               if k in ("X","Y","Z")):
            raise ValueError("Native Prusa coordinates are invalid.")
        if op=="M82":
            relative=False
        elif op=="M83":
            relative=True
        elif op=="G92":
            e=words.get("E",e)
        else:
            x=words.get("X",x)
            y=words.get("Y",y)
            z=words.get("Z",z)
            if "E" not in words:
                continue
            delta=words["E"] if relative else words["E"]-e
            e=e+words["E"] if relative else words["E"]
            if delta<=1e-6 or x is None or y is None or z is None:
                continue
            for n,(xmin,xmax,ymin,ymax,_zmin,_zmax) in enumerate(footprints):
                if xmin-.15<=x<=xmax+.15 and ymin-.15<=y<=ymax+.15:
                    zones[n].add(round(z,4))
    outcome=[]
    for n,((item,_raw),bounds,zs) in enumerate(zip(sources,footprints,zones)):
        ordered=sorted(zs)
        if len(ordered)<15:
            raise ValueError("Prusa native output lacks per-object extrusion layers.")
        profile=item.get("variable_layer_profile")
        bands=validate_variable_layer_profile(profile)["bands"] if (
            isinstance(profile,dict) and profile.get("bands")) else []
        if not bands:
            lo=max(2.,bounds[4]+.2)
            hi=min(bounds[5]-2.,bounds[4]+18.)
            bands=[{"from_mm":lo,"to_mm":hi,"layer_mm":base_layer_mm}]
        for band in bands:
            lo,hi,wanted=band["from_mm"],band["to_mm"],band["layer_mm"]
            steps=[b-a for a,b in zip(ordered,ordered[1:])
                   if a>=lo+wanted and b<=hi-wanted]
            tolerance=max(.018,wanted*.12)
            matched=sum(abs(step-wanted)<=tolerance for step in steps)
            if len(steps)<4 or matched<math.ceil(len(steps)*.65):
                raise ValueError("Prusa G-code does not preserve this object's layer schedule.")
            outcome.append({"object":n+1,"target_layer_mm":wanted,
                            "verified_steps":matched,"sampled_steps":len(steps)})
    return outcome
