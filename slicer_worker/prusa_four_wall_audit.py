"""Native Prusa 2.9.7 four-exterior-wall colour source and positive-E audit.

This is deliberately narrower than the shared arbitrary-polygon painter.
Full rectangular vertical walls, four distinct independent toolheads and
the original MakerVault 3MF mesh are proven before accepting deposited
toolpaths. No colour or geometry may be silently ignored.
"""
import io
import math
import re
import zipfile
from defusedxml import ElementTree as SafeET

from .prusa_material_validation import validate_prusa_material_candidate, MODEL, PAINT
from .prusa_colour_gcode_audit import PAINTED_STATES, WORD
from .runner import WorkerError

NS="{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
SIDES=("x_min","x_max","y_min","y_max")


def four_painted_wall_regions(project):
    try:
        with zipfile.ZipFile(io.BytesIO(project)) as archive:
            mesh=SafeET.fromstring(archive.read(MODEL))
            cfg=SafeET.fromstring(archive.read("Metadata/Slic3r_PE_model.config"))
        objects=mesh.findall("./"+NS+"resources/"+NS+"object")
        if len(objects)!=1:
            raise ValueError()
        volumes=cfg.findall("./object/volume")
        if len(volumes)!=1 or volumes[0].get("firstid")!="0":
            raise ValueError()
        vertices=objects[0].findall("./"+NS+"mesh/"+NS+"vertices/"+NS+"vertex")
        triangles=objects[0].findall("./"+NS+"mesh/"+NS+"triangles/"+NS+"triangle")
        if not 4<=len(triangles)<=500000 or not 3<=len(vertices)<=1500000:
            raise ValueError()
        points=[tuple(float(v.get(k)) for k in ("x","y","z")) for v in vertices]
        if any(not all(math.isfinite(k) and abs(k)<2000 for k in p) for p in points):
            raise ValueError()
        low=[min(p[k] for p in points) for k in range(3)]
        high=[max(p[k] for p in points) for k in range(3)]
        if any(high[k]-low[k]<=4 for k in range(3)):
            raise ValueError()
        wall_faces={side:[] for side in SIDES}
        wall_states={side:set() for side in SIDES}
        for face in triangles:
            v=[points[int(face.get(k))] for k in ("v1","v2","v3")]
            sides=[side for side,axis,coord in
                   (("x_min",0,low[0]),("x_max",0,high[0]),
                    ("y_min",1,low[1]),("y_max",1,high[1]))
                   if all(abs(p[axis]-coord)<.0001 for p in v)]
            state=face.get(PAINT)
            if len(sides)!=1:
                if state is not None:
                    raise ValueError()
                continue
            side=sides[0]
            wall_faces[side].extend(v)
            wall_states[side].add(state)
        selected={}
        for side in SIDES:
            verts=wall_faces[side]
            states=wall_states[side]
            if len(states)!=1 or len(verts)<3:
                raise ValueError()
            state=next(iter(states))
            if state not in PAINTED_STATES:
                raise ValueError()
            selected[side]=PAINTED_STATES[state]
            axis=0 if side.startswith("x") else 1
            tangent=1-axis
            if max(p[tangent] for p in verts)-min(p[tangent] for p in verts)<3:
                raise ValueError()
            if max(p[2] for p in verts)-min(p[2] for p in verts)<3:
                raise ValueError()
        if len(set(selected.values()))!=4:
            raise ValueError()
        return {"tools":selected,"min":low,"max":high}
    except (OSError,ValueError,TypeError,IndexError,KeyError,OverflowError,
            AttributeError,StopIteration,zipfile.BadZipFile):
        raise WorkerError("Prusa four-colour painting requires four complete distinct vertical walls.") from None


def audit_prusa_four_wall_gcode(data,project,*,printer_ini,tools):
    if (not isinstance(tools,(list,tuple)) or len(tools)!=4 or
            any(type(t) is not int or not 1<=t<=7 for t in tools) or
            len(set(tools))!=4):
        raise WorkerError("Prusa four-wall painting needs four distinct native painted heads.")
    # The pinned independent XL5 is verified here. Official INDX G12
    # firmware cleaner must receive its own physical-script qualification.
    from .prusa_material_validation import _qualified_topology
    count,changer=_qualified_topology(printer_ini)
    if changer or count!=5:
        raise WorkerError("Four-wall native deposition is currently qualified for independent XL5.")
    source=four_painted_wall_regions(project)
    selected=tuple(source["tools"][side] for side in SIDES)
    if selected!=tuple(tools):
        raise WorkerError("Four-wall tool order does not match the signed native mesh.")
    validated=validate_prusa_material_candidate(
        project,printer_ini=printer_ini,colour=True,independent_colour=True)
    if (validated["tools"]!=tuple(sorted((1,*(tool+1 for tool in tools)))) or
            validated["wipe_tower"]):
        raise WorkerError("Native painted head identities changed.")
    if not isinstance(data,bytes) or not 0<len(data)<=90*1024*1024:
        raise WorkerError("Invalid four-wall G-code.")
    if len(data.splitlines())>2_000_000:
        raise WorkerError("Four-wall toolpath exceeds bounded audit limit.")
    counts={tool:{side:0 for side in SIDES} for tool in (0,*tools)}
    role=""
    active=None
    x=y=None
    e=0.
    relative_e=relative_xy=False
    bounds=source
    for raw in io.BytesIO(data):
        if len(raw)>16384:
            raise WorkerError("Four-wall motion line exceeds limit.")
        try:
            line=raw.decode("utf-8").strip()
        except UnicodeDecodeError:
            raise WorkerError("Four-wall G-code must be UTF-8.") from None
        if line.startswith(";TYPE:"):
            role=line.partition(":")[2].strip().lower()
        cmd=line.split(";",1)[0].strip()
        if not cmd:
            continue
        op=cmd.split(None,1)[0].upper()
        if op.startswith("T") and op[1:].isdigit():
            active=int(op[1:])
            if active not in counts:
                raise WorkerError("Prusa four-wall output selected an unassigned tool.")
            continue
        if op not in ("M82","M83","G90","G91","G92","G0","G00","G1","G01"):
            continue
        words={k.upper():float(v) for k,v in WORD.findall(cmd)}
        if any(not math.isfinite(v) or abs(v)>1e9 for v in words.values()):
            raise WorkerError("Four-wall output contains nonfinite coordinates.")
        if op=="M82":
            relative_e=False
        elif op=="M83":
            relative_e=True
        elif op=="G90":
            relative_xy=False
        elif op=="G91":
            relative_xy=True
        elif op=="G92":
            x=words.get("X",x)
            y=words.get("Y",y)
            e=words.get("E",e)
        else:
            previous=(x,y)
            if relative_xy:
                x=x+words["X"] if x is not None and "X" in words else x
                y=y+words["Y"] if y is not None and "Y" in words else y
            else:
                x=words.get("X",x)
                y=words.get("Y",y)
            if "E" not in words:
                continue
            amount=words["E"] if relative_e else words["E"]-e
            e=e+words["E"] if relative_e else words["E"]
            if (op not in ("G1","G01") or amount<=1e-6 or
                    None in (active,x,y,*previous) or
                    "external perimeter" not in role):
                continue
            for side,axis,positive in (
                    ("x_min",0,False),("x_max",0,True),
                    ("y_min",1,False),("y_max",1,True)):
                old=previous[axis]
                current=(x,y)[axis]
                old_t=previous[1-axis]
                current_t=(x,y)[1-axis]
                coord=bounds["max"][axis] if positive else bounds["min"][axis]
                if (abs(old-coord)<=3.5 and abs(current-coord)<=3.5 and
                        abs(current-old)<=.8 and abs(current_t-old_t)>.5 and
                        bounds["min"][1-axis]-1.5<=old_t<=bounds["max"][1-axis]+1.5 and
                        bounds["min"][1-axis]-1.5<=current_t<=bounds["max"][1-axis]+1.5):
                    counts[active][side]+=1
    for side,tool in source["tools"].items():
        if counts[tool][side]<20:
            raise WorkerError("Four-wall Prusa paint did not deposit on its selected native face.")
        if any(counts[other][side]>2 for other in tools if other!=tool):
            raise WorkerError("Prusa native tool deposited on another painted exterior wall.")
    return {"wall_moves":counts,"wipe_tower":False,"tools":selected}
