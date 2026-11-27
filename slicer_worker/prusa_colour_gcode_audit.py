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
PAINTED_STATES={"8":1,"0C":2,"1C":3,"2C":4,
                "3C":5,"4C":6,"5C":7}


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
        # The native encoder already preserves facet positions. Derive
        # the painted vertical wall from those positions, not a fixed
        # front-facing fixture. Retain the opposite-wall deposition proof.
        for axis in (0, 1):
            tangent=1-axis
            lo=min(p[axis] for p in points)
            hi=max(p[axis] for p in points)
            if hi-lo<=4:
                continue
            for plane, opposite in ((lo,hi),(hi,lo)):
                if not all(abs(p[axis]-plane)<=.0001 for p in painted):
                    continue
                ts=[p[tangent] for p in painted]
                zs=[p[2] for p in painted]
                if max(ts)-min(ts)<3 or max(zs)-min(zs)<3:
                    continue
                def region(value):
                    along=(min(ts)-1,max(ts)+1)
                    across=(value-2,value+2)
                    return (*across,*along) if axis==0 else (*along,*across)
                return region(plane),region(opposite)
        raise ValueError()
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
            if extruded<=1e-6 or op not in ("G1","G01") or x is None or y is None:
                continue
            if active not in walls:
                raise WorkerError("Prusa painted extrusion had no selected native tool.")
            # Stationary positive-E is *valid purging* at a trusted tower XY,
            # but is never painted model deposition. Genuine Prusa MMU3
            # outputs include E-only changes at their wipe tower. Moving
            # extrusion requires both endpoints inside the tower.
            stationary=(old_x is not None and old_y is not None and
                        abs(x-old_x)+abs(y-old_y)<=1e-7)
            if (box[0]<=x<=box[1] and box[2]<=y<=box[3] and
                    ((old_x is not None and old_y is not None and
                      box[0]<=old_x<=box[1] and box[2]<=old_y<=box[3])
                     or stationary)):
                tower_hits[active]+=1
            if (old_x is None or old_y is None or stationary or
                    "external perimeter" not in role):
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
    """Qualify complete opposing native painted walls on either XY axis.

    The two selected tools must cover every triangle of opposite outer
    vertical walls, with no painted triangles anywhere else. Regions are
    derived from authenticated 3MF vertices, never the browser's swatch order.
    Returned "front"/"back" are the negative/positive axis walls.
    """
    if (not isinstance(tools,(tuple,list)) or len(tools)!=2 or
            any(type(t) is not int or not 1<=t<=7 for t in tools) or
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
        face_data=[]
        for face in faces:
            verts=[points[int(face.get(k))] for k in ("v1","v2","v3")]
            face_data.append((verts,face.get(PAINT)))
        states={key:next(name for name,value in PAINTED_STATES.items()
                         if value==tool)
                for key,tool in zip(("front","back"),tools)}
        qualified=[]
        for axis in (1,0):
            lo=min(p[axis] for p in points)
            hi=max(p[axis] for p in points)
            if hi-lo<=4:
                continue
            coverage={"front":[],"back":[]}
            valid=True
            for verts,state in face_data:
                side=("front" if all(abs(p[axis]-lo)<.0001 for p in verts)
                      else "back" if all(abs(p[axis]-hi)<.0001 for p in verts)
                      else None)
                if side is None:
                    if state is not None:
                        valid=False
                        break
                    continue
                if state != states[side]:
                    valid=False
                    break
                coverage[side].extend(verts)
            if not valid or not all(coverage.values()):
                continue
            tangent=1-axis
            regions={}
            for side,verts in coverage.items():
                ts=[p[tangent] for p in verts]
                zs=[p[2] for p in verts]
                if max(ts)-min(ts)<3 or max(zs)-min(zs)<3:
                    valid=False
                    break
                across=lo if side=="front" else hi
                span=(min(ts)-1,max(ts)+1)
                plane=(across-2,across+2)
                regions[side]=(*plane,*span) if axis==0 else (*span,*plane)
            if not valid:
                continue
            if (regions["front"][1]>=regions["back"][0] if axis==0
                    else regions["front"][3]>=regions["back"][2]):
                continue
            qualified.append(regions)
        if len(qualified)!=1:
            raise ValueError()
        return qualified[0]
    except (OSError, ValueError, TypeError, IndexError, KeyError,
            StopIteration, zipfile.BadZipFile, OverflowError, AttributeError):
        raise WorkerError("Prusa multi-swatch native facets are not two complete opposite walls.") from None


def audit_prusa_dual_colour_gcode(data, project, *, printer_ini, tools, tower=None):
    """Research-only 2-swatch MMU candidate: exact T1/T2 walls + T0 purge.

    This is NOT wired to production job admission. Success requires genuine
    moving extrusions on each assigned wall and isolated purge movements from
    all three tools, never merely a CLI exit or a selected T command.
    """
    regions=_two_painted_wall_regions(project,tools)
    receipt=validate_prusa_material_candidate(
        project, printer_ini=printer_ini, colour=True, tower=tower,
        independent_colour=tower is None)
    expected=tuple(sorted((1,tools[0]+1,tools[1]+1)))
    if receipt["tools"]!=expected:
        raise WorkerError("Native Prusa two-swatch tool attribution changed.")
    if not isinstance(data,bytes) or not 0<len(data)<=90*1024*1024:
        raise WorkerError("Invalid Prusa two-swatch output.")
    if tower is not None and (not isinstance(tower,(tuple,list)) or len(tower)!=5 or
            any(type(v) not in (int,float) or not math.isfinite(v) for v in tower)):
        raise WorkerError("Invalid Prusa multi-swatch purge geometry.")
    tower_box=((tower[0]-6,tower[0]+65,tower[1]-12,tower[1]+45)
               if tower is not None else None)
    selected={0,*tools}
    wall_counts={tool:{"front":0,"back":0} for tool in selected}
    purge={tool:0 for tool in selected} if tower is not None else {}
    role=""
    active=None
    x=y=None
    e=0.
    relative_e=relative_xy=False
    from .prusa_material_gcode_audit import _trusted_indx_cleaner_profile
    trusted_cleaner=_trusted_indx_cleaner_profile(printer_ini,list(tools),tower)
    cleaner=flush=False
    flush_moves=flush_blocks=0
    for index,raw in enumerate(io.BytesIO(data)):
        if index>=2000000 or len(raw)>16384:
            raise WorkerError("Prusa two-swatch G-code exceeds audit limits.")
        try:
            line=raw.decode("utf-8").strip()
        except UnicodeDecodeError:
            raise WorkerError("Prusa two-swatch G-code must be UTF-8.") from None
        if line.startswith(";TYPE:"):
            role=line.partition(":")[2].strip().lower()
        if line in (";FLUSH_START",";FLUSH_END"):
            if not trusted_cleaner or not cleaner:
                raise WorkerError("Unqualified Prusa native cleaner marker.")
            if line==";FLUSH_START":
                if flush or not relative_xy or active is None:
                    raise WorkerError("Invalid native INDX cleaner sequence.")
                flush=True
                flush_moves=0
            else:
                if not flush or not 3<=flush_moves<=8:
                    raise WorkerError("Incomplete native INDX cleaner sequence.")
                flush=False
                flush_blocks+=1
            continue
        cmd=line.split(";",1)[0].strip()
        if not cmd:
            continue
        op=cmd.split(None,1)[0].upper()
        if op=="G12" and trusted_cleaner:
            if re.search(r"(?:^|\s)S90(?:\s|$)",cmd):
                if cleaner or flush:
                    raise WorkerError("Native INDX cleaner was already active.")
                cleaner=True
            elif re.search(r"(?:^|\s)S91(?:\s|$)",cmd):
                if not cleaner or flush:
                    raise WorkerError("Native INDX cleaner did not close.")
                cleaner=False
            continue
        if op.startswith("T") and op[1:].isdigit():
            if flush:
                raise WorkerError("Native INDX tool changed inside cleaner motion.")
            active=int(op[1:])
            if active not in selected:
                raise WorkerError("Unassigned tool appeared in Prusa two-swatch output.")
            continue
        if op not in ("M82","M83","G90","G91","G92","G0","G00","G1","G01"):
            continue
        values={k.upper():float(v) for k,v in WORD.findall(cmd)}
        if any(not math.isfinite(v) or abs(v)>1e9 for v in values.values()):
            raise WorkerError("Invalid Prusa two-swatch motion.")
        if flush and op in ("G90","G92","M82"):
            raise WorkerError("INDX native cleaner changed coordinate mode.")
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
                if flush and (op not in ("G1","G01") or not relative_xy or
                              "Z" in values or abs(values.get("X",0))+
                              abs(values.get("Y",0))>2):
                    raise WorkerError("Unexpected native INDX cleaner travel.")
                continue
            amount=values["E"] if relative_e else values["E"]-e
            e=e+values["E"] if relative_e else values["E"]
            if flush:
                distance=abs(values.get("X",0))+abs(values.get("Y",0))
                if (op not in ("G1","G01") or not relative_e or not relative_xy
                        or "Z" in values or not 0<=amount<=80
                        or not 0<distance<=2):
                    raise WorkerError("Unqualified native INDX cleaner extrusion.")
                flush_moves+=1
                if flush_moves>8:
                    raise WorkerError("Native INDX cleaner exceeds bounded strokes.")
                continue
            if (amount<=1e-6 or op not in ("G1","G01") or
                    active not in selected or x is None or y is None):
                continue
            stationary=(None not in previous and
                        abs(x-previous[0])+abs(y-previous[1])<=1e-7)
            def contained(box):
                return (None not in previous and
                        box[0]<=x<=box[1] and box[2]<=y<=box[3]
                        and box[0]<=previous[0]<=box[1]
                        and box[2]<=previous[1]<=box[3])
            if tower_box is not None and contained(tower_box):
                purge[active]+=1
            if (None in previous or stationary):
                continue
            if "external perimeter" in role:
                for side,box in regions.items():
                    if contained(box):
                        wall_counts[active][side]+=1
    if trusted_cleaner and (cleaner or flush or flush_blocks<1):
        raise WorkerError("Official INDX cleaner sequence was incomplete.")
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
    if tower is not None and any(n<10 for n in purge.values()):
        raise WorkerError("Prusa two-swatch output lacks tool-specific wipe-tower purging.")
    return {"wall_moves":wall_counts,"tower_extrusion_moves":purge,
            "wipe_tower":tower is not None}


def audit_prusa_xl_colour_gcode(data, project, *, printer_ini, tool):
    """Prove real model-local native XL Tn front-wall and T0 rear deposition.

    No tower or shared nozzle: an independent head may not inherit MMU purge
    admission. Native painted 3MF, machine identity and exact opposite wall
    geometry are checked before interpreting any emitted G-code movements.
    """
    receipt=validate_prusa_material_candidate(
        project,printer_ini=printer_ini,colour=True,independent_colour=True)
    if receipt["tools"]!=(1,tool+1) or receipt["wipe_tower"]:
        raise WorkerError("Native XL painted tool identity changed.")
    front, back = _wall_regions(project, tool)
    if not isinstance(data,bytes) or not 0<len(data)<=90*1024*1024:
        raise WorkerError("Invalid native Prusa XL colour output.")
    counts={0:{"front":0,"back":0},tool:{"front":0,"back":0}}
    role=""
    active=None
    x=y=None
    e=0.
    relative_e=relative_xy=False
    try:
        lines=data.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise WorkerError("Prusa XL colour output must be UTF-8.") from None
    if len(lines)>2000000:
        raise WorkerError("Prusa XL colour toolpaths exceed auditing limits.")
    for line in lines:
        if len(line)>16384:
            raise WorkerError("Prusa XL colour G-code line exceeds audit limit.")
        if line.startswith(";TYPE:"):
            role=line.partition(":")[2].strip().lower()
        cmd=line.split(";",1)[0].strip()
        if not cmd:
            continue
        op=cmd.split(None,1)[0].upper()
        if op.startswith("T") and op[1:].isdigit():
            active=int(op[1:])
            if active not in counts:
                raise WorkerError("Unassigned native XL painted tool was selected.")
            continue
        if op not in ("M82","M83","G90","G91","G92","G0","G00","G1","G01"):
            continue
        values={k.upper():float(v) for k,v in WORD.findall(cmd)}
        if any(not math.isfinite(v) or abs(v)>1e9 for v in values.values()):
            raise WorkerError("Invalid native Prusa XL colour coordinates.")
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
            if (op not in ("G1","G01") or amount<=1e-6 or
                    None in (x,y,*previous) or
                    abs(x-previous[0])+abs(y-previous[1])<=1e-7):
                continue
            if active not in counts:
                raise WorkerError("Native XL material was deposited before selecting a tool.")
            if role!="external perimeter":
                continue
            for side,box in (("front",front),("back",back)):
                if (box[0]<=x<=box[1] and box[2]<=y<=box[3] and
                        box[0]<=previous[0]<=box[1] and
                        box[2]<=previous[1]<=box[3]):
                    counts[active][side]+=1
    if (counts[tool]["front"]<20 or counts[0]["back"]<20 or
            counts[tool]["back"]>max(2,counts[0]["back"]//100)):
        raise WorkerError("Native Prusa XL painted wall tool attribution failed.")
    return {"painted_wall_moves":counts,"wipe_tower":False}
