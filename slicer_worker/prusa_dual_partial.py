"""Prusa-native signed two-colour split-face research (offline only).

The existing verified complete opposing-wall route remains unchanged. This
requires actual individual T1/T2 external perimeter extrusion inside two
different partial patches, T0 on the unpainted areas, and MMU wipe-tower
purging. No region coordinates are trusted from a browser or API metadata.
"""
import io
import math
import zipfile
from defusedxml import ElementTree as SafeET

from .prusa_colour_gcode_audit import NS, WORD, PAINTED_STATES
from .prusa_material_validation import MODEL, PAINT
from .prusa_partial_surface import _inside_triangle
from .runner import WorkerError


def inspect_prusa_dual_partial(project, tools):
    if (not isinstance(project, bytes) or not 0 < len(project) <= 32*1024*1024
            or not isinstance(tools, (tuple,list)) or len(tools)!=2
            or any(type(t) is not int or t not in PAINTED_STATES.values()
                   for t in tools) or tools[0]==tools[1]):
        raise WorkerError("Prusa dual split face tool mapping is invalid.")
    try:
        with zipfile.ZipFile(io.BytesIO(project)) as z:
            root=SafeET.fromstring(z.read(MODEL))
        objects=root.findall("./"+NS+"resources/"+NS+"object")
        if len(objects)!=1:
            raise ValueError("Expected one native printable parent.")
        vertices=objects[0].findall(
            "./"+NS+"mesh/"+NS+"vertices/"+NS+"vertex")
        facets=objects[0].findall(
            "./"+NS+"mesh/"+NS+"triangles/"+NS+"triangle")
        if not 4<=len(facets)<=500000 or not 3<=len(vertices)<=1_500_000:
            raise ValueError("Native split-face source limit exceeded.")
        points=[tuple(float(v.get(k)) for k in ("x","y","z"))
                for v in vertices]
        if any(not all(math.isfinite(n) and abs(n)<2000 for n in p)
               for p in points):
            raise ValueError("Invalid signed paint vertices.")
        faces=[]
        for f in facets:
            tri=tuple(points[int(f.get(key))] for key in ("v1","v2","v3"))
            state=f.get(PAINT)
            if state is not None and PAINTED_STATES.get(state) not in tools:
                raise ValueError("Unselected colour in partial painted plate.")
            faces.append((tri,PAINTED_STATES.get(state)))
        qualified=[]
        for axis in (1,0):
            lo=min(p[axis] for face, _ in faces for p in face)
            hi=max(p[axis] for face, _ in faces for p in face)
            if hi-lo < 4:
                continue
            buckets=[]
            for coordinate, selected in zip((lo,hi),tools):
                wall=[(tri,tool) for tri,tool in faces
                      if all(abs(p[axis]-coordinate)<1e-4 for p in tri)]
                painted=[tri for tri,tool in wall if tool==selected]
                plain=[tri for tri,tool in wall if tool is None]
                if (not painted or not plain or
                        any(t not in (None,selected) for _,t in wall)):
                    break
                tangent=1-axis
                def projected(tri):
                    return tuple((p[tangent],p[2]) for p in tri)
                if any(abs(p[axis]-coordinate)>1e-4
                       for tri in painted for p in tri):
                    break
                buckets.append({"plane":coordinate,"tool":selected,
                                "painted":tuple(map(projected,painted)),
                                "unpainted":tuple(map(projected,plain))})
            if len(buckets)!=2:
                continue
            if any(tool is not None and not (
                (tool==tools[0] and
                 all(abs(p[axis]-lo)<1e-4 for p in tri)) or
                (tool==tools[1] and
                 all(abs(p[axis]-hi)<1e-4 for p in tri)))
                   for tri,tool in faces):
                continue
            qualified.append({"axis":axis,"walls":tuple(buckets)})
        if len(qualified)!=1:
            raise ValueError("Two independent partial masks are not opposite walls.")
        return qualified[0]
    except (OSError,ValueError,TypeError,KeyError,IndexError,AttributeError,
            OverflowError,zipfile.BadZipFile,StopIteration):
        raise WorkerError("Prusa dual split faces do not match signed source facets.") from None


def audit_prusa_dual_partial_gcode(data, project, *, printer_ini, tools, tower):
    """Require moving T1/T2 deposition with no alternate-colour cross-talk."""
    from .prusa_material_validation import validate_prusa_material_candidate
    signed=inspect_prusa_dual_partial(project,tools)
    selected={0,*tools}
    receipt=validate_prusa_material_candidate(
        project,printer_ini=printer_ini,colour=True,tower=tower,
        independent_colour=tower is None)
    if receipt["tools"]!=tuple(sorted({1,*(t+1 for t in tools)})):
        raise WorkerError("Prusa partial swatch tool vector changed.")
    if not isinstance(data,bytes) or not 0<len(data)<=90*1024*1024:
        raise WorkerError("Invalid Prusa dual partial output.")
    if tower is not None:
        if (not isinstance(tower,(tuple,list)) or len(tower)!=5 or
                any(type(v) not in (int,float) or not math.isfinite(v)
                    for v in tower)):
            raise WorkerError("Invalid native MMU dual partial tower.")
        tx,ty=tower[:2]
        box=(tx-6,tx+65,ty-12,ty+45)
    else:
        box=None
    counts={t:{(side,region):0
               for side in (0,1) for region in ("painted","unpainted")}
            for t in selected}
    purges={t:0 for t in selected} if box is not None else {}
    x=y=z=None
    extrusion=0.
    relative_e=relative_xyz=False
    role=""
    tool=None
    axis=signed["axis"]
    tangent=1-axis
    for index,raw in enumerate(io.BytesIO(data)):
        if index>=2_000_000 or len(raw)>16384:
            raise WorkerError("Native Prusa dual partial output exceeds budget.")
        try:
            line=raw.decode("utf-8").strip()
        except UnicodeDecodeError:
            raise WorkerError("Prusa dual partial G-code must be UTF-8.") from None
        if line.startswith(";TYPE:"):
            role=line.partition(":")[2].strip().lower()
        cmd=line.split(";",1)[0].strip()
        if not cmd:
            continue
        op=cmd.split(None,1)[0].upper()
        if op.startswith("T") and op[1:].isdigit():
            tool=int(op[1:])
            if tool not in selected:
                raise WorkerError("Unexpected Prusa dual split deposition tool.")
            continue
        if op not in ("M82","M83","G90","G91","G92",
                      "G0","G00","G1","G01"):
            continue
        words={k.upper():float(v) for k,v in WORD.findall(cmd)}
        if any(not math.isfinite(value) or abs(value)>1e9
               for value in words.values()):
            raise WorkerError("Invalid Prusa dual partial motion.")
        if op=="M82": relative_e=False
        elif op=="M83": relative_e=True
        elif op=="G90": relative_xyz=False
        elif op=="G91": relative_xyz=True
        elif op=="G92":
            extrusion=words.get("E",extrusion)
            x=words.get("X",x);y=words.get("Y",y);z=words.get("Z",z)
        else:
            old=(x,y,z)
            if relative_xyz:
                x=x+words["X"] if x is not None and "X" in words else x
                y=y+words["Y"] if y is not None and "Y" in words else y
                z=z+words["Z"] if z is not None and "Z" in words else z
            else:
                x=words.get("X",x);y=words.get("Y",y);z=words.get("Z",z)
            if "E" not in words:
                continue
            delta=words["E"] if relative_e else words["E"]-extrusion
            extrusion=extrusion+words["E"] if relative_e else words["E"]
            if (op not in ("G1","G01") or delta<=1e-6 or
                    tool not in selected or None in old or
                    x is None or y is None or z is None):
                continue
            if (box is not None and
                    box[0]<=old[0]<=box[1] and
                    box[2]<=old[1]<=box[3] and
                    box[0]<=x<=box[1] and box[2]<=y<=box[3]):
                purges[tool]+=1
            if role!="external perimeter":
                continue
            for index_wall,wall in enumerate(signed["walls"]):
                if (abs(old[axis]-wall["plane"])>1.5 or
                        abs((x,y)[axis]-wall["plane"])>1.5 or
                        abs(old[2]-z)>.001):
                    continue
                midpoint=((old[tangent]+(x,y)[tangent])/2,z)
                inside=[region for region in ("painted","unpainted")
                        if any(_inside_triangle(midpoint,tri)
                               for tri in wall[region])]
                if len(inside)==1:
                    counts[tool][(index_wall,inside[0])]+=1
    for i,assigned in enumerate(tools):
        other=tools[1-i]
        if (counts[assigned][(i,"painted")]<8 or
                counts[0][(i,"unpainted")]<8 or
                counts[other][(i,"painted")]>2 or
                counts[assigned][(i,"unpainted")]>2 or
                counts[0][(i,"painted")]>
                max(2,counts[assigned][(i,"painted")]//8)):
            raise WorkerError(
                "Prusa dual partial faces failed isolated deposited-tool audit.")
    if box is not None and any(n<10 for n in purges.values()):
        raise WorkerError("Prusa dual partial MMU output lacks tool-specific purge.")
    return {"tool_moves":counts,"tower_extrusion_moves":purges,
            "wipe_tower":box is not None,"offline_only":True}


def qualified_prusa_dual_colour_mode(project, tools):
    """Use signed 3MF, never browser flags, to select a verified MMU audit."""
    from .prusa_colour_gcode_audit import _two_painted_wall_regions
    try:
        _two_painted_wall_regions(project, tools)
        return "complete_opposite"
    except WorkerError:
        inspect_prusa_dual_partial(project, tools)
        return "split_opposite"
