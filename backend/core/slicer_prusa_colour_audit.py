"""Spatial positive-extrusion audit for native Prusa painted two-colour walls.

Research-grade geometry-specific contract, not arbitrary surface admission:
the caller must supply independently verified disjoint wall regions. Purge
tower moves outside those rectangles are not treated as painted deposition.
Stationary priming and paths crossing into a region from outside are also
excluded; a genuine deposited XY segment must lie within a measured wall.
"""
import math
import re

WORD = re.compile(r"(?:^|\s)([XYZE])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)",re.I)


def _rectangle(rect):
    if (not isinstance(rect,(tuple,list)) or len(rect)!=4 or
            any(type(v) not in (int,float) or not math.isfinite(v) for v in rect)
            or not -2000 <= rect[0] < rect[1] <= 2000
            or not -2000 <= rect[2] < rect[3] <= 2000):
        raise ValueError("Invalid native Prusa painted wall rectangle.")
    return tuple(rect)


def audit_prusa_painted_wall_tools(data, *, painted_wall, unpainted_wall,
                                   minimum_moves=20):
    if not isinstance(data,bytes) or not 0<len(data)<=90*1024*1024:
        raise ValueError("Native Prusa painted G-code must be bounded text.")
    a,b=_rectangle(painted_wall),_rectangle(unpainted_wall)
    if min(a[1],b[1])>max(a[0],b[0]) and min(a[3],b[3])>max(a[2],b[2]):
        raise ValueError("Native Prusa painted wall audit regions overlap.")
    if type(minimum_moves) is not int or not 2<=minimum_moves<=100000:
        raise ValueError("Invalid Prusa painted audit movement threshold.")
    try:
        lines=data.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise ValueError("Native Prusa painted G-code must be UTF-8.") from None
    if len(lines)>2_000_000:
        raise ValueError("Native Prusa painted G-code has excessive lines.")
    tool=None
    e=0.0
    relative=False
    relative_xy=False
    x=y=None
    role=""
    counts={0:{"painted":0,"unpainted":0},1:{"painted":0,"unpainted":0}}
    for line in lines:
        if len(line)>16384:
            raise ValueError("Native Prusa painted G-code line is too long.")
        if line.startswith(";TYPE:"):
            role=line.partition(":")[2].strip().lower()
        cmd=line.split(";",1)[0].strip()
        if not cmd:
            continue
        opcode=cmd.split(None,1)[0].upper()
        if opcode in ("T0","T1"):
            tool=int(opcode[1])
            continue
        if opcode.startswith("T") and opcode[1:].isdigit():
            raise ValueError("Unsupported native Prusa painted tool selection.")
        if opcode not in ("M82","M83","G90","G91","G92","G0","G00","G1","G01"):
            continue
        values={k.upper():float(v) for k,v in WORD.findall(cmd)}
        if any(not math.isfinite(v) or abs(v)>1e9 for v in values.values()):
            raise ValueError("Invalid native Prusa painted tool coordinates.")
        if opcode=="M82":
            relative=False
        elif opcode=="M83":
            relative=True
        elif opcode=="G90":
            relative_xy=False
        elif opcode=="G91":
            relative_xy=True
        elif opcode=="G92":
            e=values.get("E",e)
            x=values.get("X",x)
            y=values.get("Y",y)
        else:
            old_x,old_y=x,y
            if relative_xy:
                x=x+values["X"] if x is not None and "X" in values else (None if "X" in values else x)
                y=y+values["Y"] if y is not None and "Y" in values else (None if "Y" in values else y)
            else:
                x=values.get("X",x)
                y=values.get("Y",y)
            if "E" not in values:
                continue
            delta=values["E"] if relative else values["E"]-e
            e=e+values["E"] if relative else values["E"]
            if (delta<=1e-6 or opcode not in ("G1","G01") or
                    tool not in counts or x is None or y is None or
                    role.strip()!="external perimeter" or old_x is None or old_y is None or
                    abs(x-old_x)+abs(y-old_y)<=1e-7):
                continue
            for label,rect in (("painted",a),("unpainted",b)):
                if (rect[0]<=x<=rect[1] and rect[2]<=y<=rect[3] and
                        rect[0]<=old_x<=rect[1] and rect[2]<=old_y<=rect[3]):
                    counts[tool][label]+=1
    if (counts[1]["painted"]<minimum_moves or
            counts[0]["unpainted"]<minimum_moves or
            counts[1]["unpainted"]>max(2,counts[0]["unpainted"]//100)):
        raise ValueError("Native Prusa colour painting did not produce isolated T1 wall deposition.")
    return counts
