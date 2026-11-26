"""Independent offline Prusa MMU painted-wall positive-E and tower audit.

The proven native route is one upright model, a single selected alternate tool,
and a Y-min front wall. Arbitrary face patterns, angled models and a full colour
painting palette require separate actual-G-code qualification.
"""
import io
import math
import re
import zipfile

from defusedxml import ElementTree as SafeET
from .prusa_material_validation import (
    validate_prusa_material_candidate, MODEL, PAINT,
)
from .runner import WorkerError

NS="{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
WORD=re.compile(r"(?:^|\s)([XYZE])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)",re.I)
PAINTED_STATES={"8":1,"0C":2,"1C":3,"2C":4}


def _wall_regions(project, tool):
    try:
        with zipfile.ZipFile(io.BytesIO(project)) as source:
            root=SafeET.fromstring(source.read(MODEL))
        object_rows=root.findall("./"+NS+"resources/"+NS+"object")
        if len(object_rows)!=1:
            raise ValueError()
        obj=object_rows[0]
        vertices=obj.findall("./"+NS+"mesh/"+NS+"vertices/"+NS+"vertex")
        triangles=obj.findall("./"+NS+"mesh/"+NS+"triangles/"+NS+"triangle")
        points=[(float(v.get("x")),float(v.get("y")),float(v.get("z")))
                for v in vertices]
        if (not 3<=len(points)<=1500000 or
                any(not all(math.isfinite(x) and abs(x)<2000 for x in row)
                    for row in points)):
            raise ValueError()
        minimum_y=min(p[1] for p in points)
        maximum_y=max(p[1] for p in points)
        if maximum_y-minimum_y < 4:
            raise ValueError()
        painted=[]
        for triangle in triangles:
            state=triangle.get(PAINT)
            if state is None:
                continue
            if PAINTED_STATES.get(state)!=tool:
                raise ValueError()
            for key in ("v1","v2","v3"):
                index=int(triangle.get(key))
                painted.append(points[index])
        if not painted:
            raise ValueError()
        front_y=painted[0][1]
        if (abs(front_y-minimum_y)>.25 or
                any(abs(p[1]-front_y)>.25 for p in painted)):
            raise ValueError()
        xs=[p[0] for p in painted]
        zs=[p[2] for p in painted]
        if max(xs)-min(xs)<3 or max(zs)-min(zs)<3:
            raise ValueError()
        return ((min(xs)-1,max(xs)+1,front_y-2,front_y+2),
                (min(xs)-1,max(xs)+1,maximum_y-2,maximum_y+2))
    except (OSError,ValueError,TypeError,IndexError,KeyError,zipfile.BadZipFile,
            OverflowError,AttributeError):
        raise WorkerError("Prusa native colour has an unqualified painted surface.") from None


def audit_prusa_offline_colour_gcode(data, project, *, printer_ini, tool, tower):
    if type(tool) is not int or not 1<=tool<=4:
        raise WorkerError("Prusa painted tool must be T1-T4.")
    receipt=validate_prusa_material_candidate(
        project,printer_ini=printer_ini,colour=True,tower=tower)
    if receipt["tools"]!=(1,tool+1):
        raise WorkerError("Prusa painted project tool does not match selected native material.")
    front,back=_wall_regions(project,tool)
    if not isinstance(data,bytes) or not 0<len(data)<=90*1024*1024:
        raise WorkerError("Invalid Prusa painted output.")
    try:
        lines=data.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise WorkerError("Native Prusa colour output must be UTF-8.") from None
    if len(lines)>2_000_000:
        raise WorkerError("Native Prusa colour G-code exceeds its line limit.")
    role=""
    active=None
    e=0.0
    relative=False
    x=y=None
    walls={0:{"front":0,"back":0},tool:{"front":0,"back":0}}
    tower_hits={0:0,tool:0}
    tx,ty=tower[:2]
    box=(tx-6,tx+65,ty-12,ty+45)
    for line in lines:
        if len(line)>16384:
            raise WorkerError("Native Prusa colour G-code line is too long.")
        if line.startswith(";TYPE:"):
            role=line.partition(":")[2].strip().lower()
        cmd=line.split(";",1)[0].strip()
        if not cmd:
            continue
        op=cmd.split(None,1)[0].upper()
        if op.startswith("T") and op[1:].isdigit():
            active=int(op[1:])
            if active not in walls:
                raise WorkerError("Prusa painted output selected an unexpected tool.")
            continue
        if op not in ("M82","M83","G92","G0","G00","G1","G01"):
            continue
        values={k.upper():float(v) for k,v in WORD.findall(cmd)}
        if any(not math.isfinite(v) or abs(v)>1e9 for v in values.values()):
            raise WorkerError("Prusa painted output contains invalid motion.")
        if op=="M82":
            relative=False
        elif op=="M83":
            relative=True
        elif op=="G92":
            e=values.get("E",e)
        else:
            x=values.get("X",x)
            y=values.get("Y",y)
            if "E" not in values:
                continue
            extruded=values["E"] if relative else values["E"]-e
            e=e+values["E"] if relative else values["E"]
            if extruded<=1e-6 or op not in ("G1","G01") or x is None or y is None:
                continue
            if active not in walls:
                raise WorkerError("Prusa painted extrusion had no selected native tool.")
            if box[0]<=x<=box[1] and box[2]<=y<=box[3]:
                tower_hits[active]+=1
            if "external perimeter" not in role:
                continue
            for name,region in (("front",front),("back",back)):
                if region[0]<=x<=region[1] and region[2]<=y<=region[3]:
                    walls[active][name]+=1
    if (walls[tool]["front"]<20 or walls[0]["back"]<20 or
            walls[tool]["back"]>max(2,walls[0]["back"]//100)):
        raise WorkerError("Prusa painted tool deposition did not match the selected front wall.")
    # Native wipe-tower geometry and flavour vary by profile. Insist on
    # positive-E purge from both selected tools before storing output.
    if any(n<10 for n in tower_hits.values()):
        raise WorkerError("Prusa painted G-code lacks native tool-specific tower purging.")
    return {"painted_wall_moves":walls,"tower_extrusion_moves":tower_hits}
