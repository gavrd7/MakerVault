"""Native Prusa 2.9.7 signed horizontal top-surface colour verification.

Only one genuine XL5 top-plane partial mask is currently qualified. This
inspects actual 3MF source triangles and moving deposited G-code; no browser
coordinates, screenshot colours or temporary tool selectors are trusted.
"""
import io
import math
import re
import zipfile

from defusedxml import ElementTree as SafeET

from .prusa_colour_gcode_audit import NS, PAINTED_STATES
from .prusa_material_validation import MODEL, PAINT
from .runner import WorkerError

_WORD = re.compile(
    r"(?:^|\s)([XYZE])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)",
    re.I)


def _area2(triangle):
    a, b, c = triangle
    return abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))


def _interior(xy, triangle, margin=.05):
    a, b, c = triangle
    denominator = ((b[1]-c[1])*(a[0]-c[0]) +
                   (c[0]-b[0])*(a[1]-c[1]))
    if abs(denominator) < 1e-10:
        return False
    u = ((b[1]-c[1])*(xy[0]-c[0]) +
         (c[0]-b[0])*(xy[1]-c[1])) / denominator
    v = ((c[1]-a[1])*(xy[0]-c[0]) +
         (a[0]-c[0])*(xy[1]-c[1])) / denominator
    return min(u, v, 1-u-v) > margin


def inspect_prusa_partial_top(project, tool):
    """Read a *partially* painted highest horizontal ModelPart face.

    A fully painted top, walls/slopes, mixed tools, paint on modifiers or
    unsupported coordinates must fail. The output is only a source-geometry
    description, never printer-dispatch authorisation.
    """
    if type(tool) is not int or tool not in PAINTED_STATES.values():
        raise WorkerError("Invalid Prusa top-surface paint tool.")
    if not isinstance(project, bytes) or not 0 < len(project) <= 32*1024*1024:
        raise WorkerError("Invalid Prusa top-surface project.")
    try:
        with zipfile.ZipFile(io.BytesIO(project)) as z:
            root = SafeET.fromstring(z.read(MODEL))
            cfg = SafeET.fromstring(z.read(
                "Metadata/Slic3r_PE_model.config"))
        objects = root.findall("./"+NS+"resources/"+NS+"object")
        records = cfg.findall("./object")
        if len(objects)!=1 or len(records)!=1:
            raise ValueError("Expected a single native paint source.")
        vertices = objects[0].findall(
            "./"+NS+"mesh/"+NS+"vertices/"+NS+"vertex")
        triangles = objects[0].findall(
            "./"+NS+"mesh/"+NS+"triangles/"+NS+"triangle")
        volumes = records[0].findall("./volume")
        if (not 3<=len(vertices)<=1_500_000 or
                not 4<=len(triangles)<=500_000 or not volumes or
                volumes[0].get("firstid")!="0" or
                not any(node.get("key")=="volume_type" and
                        node.get("value")=="ModelPart" for node in
                        volumes[0].findall("./metadata"))):
            raise ValueError("Missing qualified printable volume.")
        end = int(volumes[0].get("lastid", "-1"))
        if not 3<=end<len(triangles):
            raise ValueError("Invalid top ModelPart range.")
        if any(PAINT in face.attrib for face in triangles[end+1:]):
            raise ValueError("Nonprinting volume contains paint.")
        points = [tuple(float(v.get(axis)) for axis in ("x","y","z"))
                  for v in vertices]
        if any(not all(math.isfinite(value) and abs(value)<2000
                       for value in point) for point in points):
            raise ValueError("Invalid source vertices.")
        data=[]
        expected = next(name for name, t in PAINTED_STATES.items()
                        if t==tool)
        for face in triangles[:end+1]:
            verts=tuple(points[int(face.get(axis))]
                        for axis in ("v1","v2","v3"))
            state=face.get(PAINT)
            if state not in (None, expected):
                raise ValueError("Unexpected painted tool state.")
            data.append((verts,state))
        z_max=max(point[2] for face, _ in data for point in face)
        painted=[]
        plain=[]
        for face,state in data:
            top=all(abs(point[2]-z_max)<=0.0001 for point in face)
            if state==expected and not top:
                raise ValueError("Paint extends beyond the top horizontal plane.")
            if top:
                polygon=tuple((point[0],point[1]) for point in face)
                if _area2(polygon)<=1e-5:
                    raise ValueError("Degenerate top paint polygon.")
                (painted if state==expected else plain).append(polygon)
        if not painted or not plain:
            raise ValueError("Full or empty top paint cannot certify a split.")
        total_painted=sum(_area2(tri) for tri in painted)/2
        total_plain=sum(_area2(tri) for tri in plain)/2
        if total_painted<=.01 or total_plain<=.01:
            raise ValueError("Insufficient split mask surface area.")
        return {"tool":tool,"z_top":z_max,
                "painted":tuple(painted),"unpainted":tuple(plain),
                "painted_area_mm2":round(total_painted,5),
                "unpainted_area_mm2":round(total_plain,5)}
    except (OSError,ValueError,TypeError,IndexError,KeyError,StopIteration,
            OverflowError,AttributeError,zipfile.BadZipFile):
        raise WorkerError(
            "Prusa native colour has an unqualified horizontal top surface.") from None


def audit_prusa_partial_top_gcode(data, project, *, tool, tower=None):
    """Audit native top-skin painting and, for MMU, source-bound tool purges."""
    source=inspect_prusa_partial_top(project,tool)
    if not isinstance(data, bytes) or not 0<len(data)<=90*1024*1024:
        raise WorkerError("Invalid Prusa partial top G-code.")
    selected={0,tool}
    counts={t:{"painted":0,"unpainted":0} for t in selected}
    if tower is not None:
        if (not isinstance(tower,(tuple,list)) or len(tower)!=5 or
                any(type(n) not in (int,float) or not math.isfinite(n)
                    for n in tower)):
            raise WorkerError("Invalid Prusa MMU top-surface tower geometry.")
        tx,ty=tower[:2]
        tower_box=(tx-6,tx+65,ty-12,ty+45)
        purge={t:0 for t in selected}
    else:
        tower_box=None
        purge=None
    role=""
    active=None
    position=[None,None,None]
    e=0.
    relative_e=relative_xyz=False
    for index,line_bytes in enumerate(io.BytesIO(data)):
        if index>=2_000_000 or len(line_bytes)>16384:
            raise WorkerError("Prusa horizontal G-code exceeds audit budget.")
        try:
            line=line_bytes.decode("utf-8").strip()
        except UnicodeDecodeError:
            raise WorkerError("Invalid Prusa horizontal G-code encoding.") from None
        if line.startswith(";TYPE:"):
            role=line.partition(":")[2].strip().lower()
        cmd=line.split(";",1)[0].strip()
        if not cmd:
            continue
        op=cmd.split(None,1)[0].upper()
        if op.startswith("T") and op[1:].isdigit():
            active=int(op[1:])
            if active not in selected:
                raise WorkerError("Unexpected Prusa horizontal paint tool.")
            continue
        if op not in ("M82","M83","G90","G91","G92",
                      "G0","G00","G1","G01"):
            continue
        words={k.upper():float(v) for k,v in _WORD.findall(cmd)}
        if any(not math.isfinite(v) or abs(v)>1e9 for v in words.values()):
            raise WorkerError("Invalid Prusa horizontal coordinates.")
        if op=="M82": relative_e=False
        elif op=="M83": relative_e=True
        elif op=="G90": relative_xyz=False
        elif op=="G91": relative_xyz=True
        elif op=="G92":
            e=words.get("E",e)
            for i,k in enumerate("XYZ"):
                if k in words: position[i]=words[k]
        else:
            before=tuple(position)
            for i,k in enumerate("XYZ"):
                if k in words:
                    position[i]=(position[i]+words[k] if relative_xyz and
                                 position[i] is not None else
                                 None if relative_xyz else words[k])
            if "E" not in words:
                continue
            delta=words["E"] if relative_e else words["E"]-e
            e=e+words["E"] if relative_e else words["E"]
            if (tower_box is not None and active in selected and
                    op in ("G1","G01") and delta>1e-6 and
                    all(point is not None for point in
                        (before[0],before[1],position[0],position[1])) and
                    tower_box[0]<=before[0]<=tower_box[1] and
                    tower_box[2]<=before[1]<=tower_box[3] and
                    tower_box[0]<=position[0]<=tower_box[1] and
                    tower_box[2]<=position[1]<=tower_box[3]):
                # A native MMU may purge by stationary E moves at the
                # authenticated tower XY, not only moving wipe paths.
                purge[active]+=1
            if (op not in ("G1","G01") or delta<=1e-6 or
                    active not in selected or
                    not ("solid infill" in role or role=="external perimeter")
                    or any(x is None for x in before+tuple(position))):
                continue
            if (abs(position[2]-source["z_top"])>.7 or
                    abs(before[2]-source["z_top"])>.7 or
                    abs(position[0]-before[0])+abs(position[1]-before[1])<=1e-5):
                continue
            midpoint=((position[0]+before[0])/2,
                      (position[1]+before[1])/2)
            painted=any(_interior(midpoint,tri)
                        for tri in source["painted"])
            plain=any(_interior(midpoint,tri)
                      for tri in source["unpainted"])
            if painted == plain:
                continue
            counts[active]["painted" if painted else "unpainted"]+=1
    if (counts[tool]["painted"]<8 or counts[0]["unpainted"]<20 or
            counts[0]["painted"]>max(2,counts[tool]["painted"]//8) or
            counts[tool]["unpainted"]>max(5,counts[tool]["painted"]//4)):
        raise WorkerError(
            "Prusa partial top deposition mismatched signed facets "
            "(selected painted=%d, selected other=%d, base painted=%d, "
            "base other=%d)." % (
                counts[tool]["painted"], counts[tool]["unpainted"],
                counts[0]["painted"], counts[0]["unpainted"]))
    if purge is not None and any(n<10 for n in purge.values()):
        raise WorkerError(
            "Prusa MMU partial top G-code lacks independently verified T0/T1 wipe purging.")
    return {"tool":tool,"top_deposition_moves":counts,
            "tower_extrusion_moves":purge,
            "offline_only":True,"wipe_tower":tower is not None}
