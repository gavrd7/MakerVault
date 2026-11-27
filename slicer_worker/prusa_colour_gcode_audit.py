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
    relative_xy=False
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
        if op not in ("M82","M83","G90","G91","G92","G0","G00","G1","G01"):
            continue
        values={k.upper():float(v) for k,v in WORD.findall(cmd)}
        if any(not math.isfinite(v) or abs(v)>1e9 for v in values.values()):
            raise WorkerError("Prusa painted output contains invalid motion.")
        if op=="M82":
            relative=False
        elif op=="M83":
            relative=True
        elif op=="G90":
            relative_xy=False
        elif op=="G91":
            relative_xy=True
        elif op=="G92":
            e=values.get("E",e)
            x=values.get("X",x)
            y=values.get("Y",y)
        else:
            old_x,old_y=x,y
            if relative_xy:
                x=x+values["X"] if x is not None and "X" in values else (
                    None if "X" in values else x)
                y=y+values["Y"] if y is not None and "Y" in values else (
                    None if "Y" in values else y)
            else:
                x=values.get("X",x)
                y=values.get("Y",y)
            if "E" not in values:
                continue
            extruded=values["E"] if relative else values["E"]-e
            e=e+values["E"] if relative else values["E"]
            if (extruded<=1e-6 or op not in ("G1","G01") or
                    x is None or y is None or old_x is None or old_y is None or
                    abs(x-old_x)+abs(y-old_y)<=1e-7):
                continue
            if active not in walls:
                raise WorkerError("Prusa painted extrusion had no selected native tool.")
            if (box[0]<=x<=box[1] and box[2]<=y<=box[3] and
                    box[0]<=old_x<=box[1] and box[2]<=old_y<=box[3]):
                tower_hits[active]+=1
            if "external perimeter" not in role:
                continue
            for name,region in (("front",front),("back",back)):
                if (region[0]<=x<=region[1] and region[2]<=y<=region[3] and
                        region[0]<=old_x<=region[1] and
                        region[2]<=old_y<=region[3]):
                    walls[active][name]+=1
    if (walls[tool]["front"]<20 or walls[0]["back"]<20 or
            walls[tool]["back"]>max(2,walls[0]["back"]//100)):
        raise WorkerError("Prusa painted tool deposition did not match the selected front wall.")
    # Native wipe-tower geometry and flavour vary by profile. Insist on
    # positive-E purge from both selected tools before storing output.
    if any(n<10 for n in tower_hits.values()):
        raise WorkerError("Prusa painted G-code lacks native tool-specific tower purging.")
    return {"painted_wall_moves":walls,"tower_extrusion_moves":tower_hits}


def _two_painted_wall_regions(project, tools):
    """Require two complete disjoint native-painted opposite walls in one 3MF.

    This deliberately does NOT admit arbitrary patches, side faces or XL.
    Tool identities come from the independent 3MF validator, not browser
    swatch labels. All model-facing triangles on the two opposite walls
    must have the matching exact unsplit Prusa TriangleSelector state.
    """
    if (not isinstance(tools,(tuple,list)) or len(tools)!=2 or
            any(type(t) is not int or not 1<=t<=4 for t in tools) or
            tools[0]==tools[1]):
        raise WorkerError("Prusa multi-swatch requires two distinct native tools.")
    try:
        with zipfile.ZipFile(io.BytesIO(project)) as archive:
            root=SafeET.fromstring(archive.read(MODEL))
        objects=root.findall("./"+NS+"resources/"+NS+"object")
        if len(objects)!=1:
            raise ValueError()
        obj=objects[0]
        vertices=obj.findall("./"+NS+"mesh/"+NS+"vertices/"+NS+"vertex")
        faces=obj.findall("./"+NS+"mesh/"+NS+"triangles/"+NS+"triangle")
        points=[tuple(float(v.get(a)) for a in ("x","y","z")) for v in vertices]
        if (not 3<=len(points)<=1500000 or not 4<=len(faces)<=500000 or
                any(not all(math.isfinite(v) and abs(v)<2000 for v in p)
                    for p in points)):
            raise ValueError()
        ylo=min(p[1] for p in points)
        yhi=max(p[1] for p in points)
        if yhi-ylo<4:
            raise ValueError()
        sides={"front":(ylo,tools[0]),"back":(yhi,tools[1])}
        coverage={"front":[], "back":[]}
        for face in faces:
            verts=[points[int(face.get(k))] for k in ("v1","v2","v3")]
            state=face.get(PAINT)
            side=next((name for name,(y,_tool) in sides.items()
                       if all(abs(p[1]-y)<.0001 for p in verts)),None)
            if side is None:
                if state is not None:
                    raise ValueError()
                continue
            if state != next(key for key,value in PAINTED_STATES.items()
                             if value==sides[side][1]):
                raise ValueError()
            coverage[side].extend(verts)
        regions={}
        for side, vertices in coverage.items():
            if not vertices:
                raise ValueError()
            xs=[p[0] for p in vertices]
            zs=[p[2] for p in vertices]
            if max(xs)-min(xs)<3 or max(zs)-min(zs)<3:
                raise ValueError()
            y=sides[side][0]
            regions[side]=(min(xs)-1,max(xs)+1,y-2,y+2)
        if (regions["front"][3]>=regions["back"][2]):
            raise ValueError()
        return regions
    except (OSError, ValueError, TypeError, IndexError, KeyError,
            StopIteration, zipfile.BadZipFile, OverflowError, AttributeError):
        raise WorkerError("Prusa multi-swatch native facets are not two complete opposite walls.") from None


def audit_prusa_dual_colour_gcode(data, project, *, printer_ini, tools, tower):
    """Research-only 2-swatch MMU candidate: exact T1/T2 walls + T0 purge.

    This is NOT wired to production job admission. Success requires genuine
    moving extrusions on each assigned wall and isolated purge movements from
    all three tools, never merely a CLI exit or a selected T command.
    """
    regions=_two_painted_wall_regions(project,tools)
    receipt=validate_prusa_material_candidate(
        project, printer_ini=printer_ini, colour=True, tower=tower)
    expected=tuple(sorted((1,tools[0]+1,tools[1]+1)))
    if receipt["tools"]!=expected:
        raise WorkerError("Native Prusa two-swatch tool attribution changed.")
    if not isinstance(data,bytes) or not 0<len(data)<=90*1024*1024:
        raise WorkerError("Invalid Prusa two-swatch output.")
    if (not isinstance(tower,(tuple,list)) or len(tower)!=5 or
            any(type(v) not in (int,float) or not math.isfinite(v) for v in tower)):
        raise WorkerError("Invalid Prusa multi-swatch purge geometry.")
    tx,ty=tower[:2]
    tower_box=(tx-6,tx+65,ty-12,ty+45)
    selected={0,*tools}
    wall_counts={tool:{"front":0,"back":0} for tool in selected}
    purge={tool:0 for tool in selected}
    role=""
    active=None
    x=y=None
    e=0.
    relative_e=relative_xy=False
    for index,raw in enumerate(io.BytesIO(data)):
        if index>=2000000 or len(raw)>16384:
            raise WorkerError("Prusa two-swatch G-code exceeds audit limits.")
        try:
            line=raw.decode("utf-8").strip()
        except UnicodeDecodeError:
            raise WorkerError("Prusa two-swatch G-code must be UTF-8.") from None
        if line.startswith(";TYPE:"):
            role=line.partition(":")[2].strip().lower()
        cmd=line.split(";",1)[0].strip()
        if not cmd:
            continue
        op=cmd.split(None,1)[0].upper()
        if op.startswith("T") and op[1:].isdigit():
            active=int(op[1:])
            if active not in selected:
                raise WorkerError("Unassigned tool appeared in Prusa two-swatch output.")
            continue
        if op not in ("M82","M83","G90","G91","G92","G0","G00","G1","G01"):
            continue
        values={k.upper():float(v) for k,v in WORD.findall(cmd)}
        if any(not math.isfinite(v) or abs(v)>1e9 for v in values.values()):
            raise WorkerError("Invalid Prusa two-swatch motion.")
        if op=="M82":
            relative_e=False
        elif op=="M83":
            relative_e=True
        elif op=="G90":
            relative_xy=False
        elif op=="G91":
            relative_xy=True
        elif op=="G92":
            e=values.get("E",e)
            x=values.get("X",x)
            y=values.get("Y",y)
        else:
            previous=(x,y)
            if relative_xy:
                x=x+values["X"] if x is not None and "X" in values else (
                    None if "X" in values else x)
                y=y+values["Y"] if y is not None and "Y" in values else (
                    None if "Y" in values else y)
            else:
                x=values.get("X",x)
                y=values.get("Y",y)
            if "E" not in values:
                continue
            amount=values["E"] if relative_e else values["E"]-e
            e=e+values["E"] if relative_e else values["E"]
            if (amount<=1e-6 or op not in ("G1","G01") or
                    active not in selected or None in (x,y,*previous) or
                    abs(x-previous[0])+abs(y-previous[1])<=1e-7):
                continue
            def contained(box):
                return (box[0]<=x<=box[1] and box[2]<=y<=box[3]
                        and box[0]<=previous[0]<=box[1]
                        and box[2]<=previous[1]<=box[3])
            if contained(tower_box):
                purge[active]+=1
            if "external perimeter" in role:
                for side,box in regions.items():
                    if contained(box):
                        wall_counts[active][side]+=1
    # Native Prusa 2.9.7 legitimately retains T0 base-material external
    # perimeters near painted face corners: the real two-swatch reference
    # showed 215/221 T0 movements alongside 294 T1 front and 295 T2 back.
    # T0 is the explicit base tool and is NOT a forbidden cross-colour.
    # The independently assigned *alternate* tools must never print the
    # opposing painted wall, and each must deposit its own surface.
    if (wall_counts[tools[0]]["front"]<20 or
            wall_counts[tools[1]]["back"]<20 or
            wall_counts[tools[0]]["back"]>2 or
            wall_counts[tools[1]]["front"]>2):
        raise WorkerError("Prusa two-swatch output failed wall-local tool attribution.")
    if any(n<10 for n in purge.values()):
        raise WorkerError("Prusa two-swatch output lacks tool-specific wipe-tower purging.")
    return {"wall_moves":wall_counts,"tower_extrusion_moves":purge}
