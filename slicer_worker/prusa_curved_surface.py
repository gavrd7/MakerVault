"""Source-derived 3D positive-E paint audit for genuinely nonplanar Prusa surfaces.

No 2D rectangle or whole-wall approximation. Index the trusted, source-
fingerprinted native 3MF triangles in a bounded three-dimensional BVH,
measure deposited exterior-toolpath midpoints against the nearest signed
painted/unpainted facets and exclude ambiguous boundary paths. This is an
offline qualification primitive; only proven topology/geometry combinations
may be admitted by the separate Prusa worker contract.
"""
import io
import math
import zipfile

from defusedxml import ElementTree as SafeET

from .prusa_colour_gcode_audit import WORD, NS, PAINTED_STATES
from .prusa_material_validation import MODEL, CONFIG, PAINT
from .runner import WorkerError


def _dot(a,b):
    return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]


def _sub(a,b):
    return (a[0]-b[0],a[1]-b[1],a[2]-b[2])


def _dist2(a,b):
    d=_sub(a,b)
    return _dot(d,d)


def _point_triangle_dist2(p,face):
    """Squared Euclidean distance to a finite 3-D triangle (not its plane)."""
    a,b,c=face
    ab=_sub(b,a);ac=_sub(c,a);ap=_sub(p,a)
    d1=_dot(ab,ap);d2=_dot(ac,ap)
    if d1<=0 and d2<=0:return _dist2(p,a)
    bp=_sub(p,b)
    d3=_dot(ab,bp);d4=_dot(ac,bp)
    if d3>=0 and d4<=d3:return _dist2(p,b)
    vc=d1*d4-d3*d2
    if vc<=0 and d1>=0 and d3<=0:
        v=d1/(d1-d3)
        return _dist2(p,tuple(a[i]+v*ab[i] for i in range(3)))
    cp=_sub(p,c)
    d5=_dot(ab,cp);d6=_dot(ac,cp)
    if d6>=0 and d5<=d6:return _dist2(p,c)
    vb=d5*d2-d1*d6
    if vb<=0 and d2>=0 and d6<=0:
        v=d2/(d2-d6)
        return _dist2(p,tuple(a[i]+v*ac[i] for i in range(3)))
    va=d3*d6-d5*d4
    if va<=0 and (d4-d3)>=0 and (d5-d6)>=0:
        bc=_sub(c,b)
        v=(d4-d3)/((d4-d3)+(d5-d6))
        return _dist2(p,tuple(b[i]+v*bc[i] for i in range(3)))
    denom=1/(va+vb+vc)
    v=vb*denom;w=vc*denom
    return _dist2(p,tuple(a[i]+ab[i]*v+ac[i]*w for i in range(3)))


def _bbox(entries):
    return tuple((min(entry[2][i][0] for entry in entries),
                  max(entry[2][i][1] for entry in entries))
                 for i in range(3))


def _surface_tree(painted,plain):
    """Balanced axis-wise 3-D BVH; leaf candidates keep trusted material IDs."""
    entries=[]
    for kind,faces in ((1,painted),(0,plain)):
        for triangle in faces:
            bounds=tuple((min(p[axis] for p in triangle),
                          max(p[axis] for p in triangle))
                         for axis in range(3))
            entries.append((kind,triangle,bounds))
    if not entries or len(entries)>300000:
        raise WorkerError("Prusa 3D paint exceeds bounded surface index size.")
    def build(rows):
        bounds=_bbox(rows)
        if len(rows)<=16:
            return bounds,None,None,tuple(rows)
        axis=max(range(3),key=lambda i:bounds[i][1]-bounds[i][0])
        rows.sort(key=lambda item:(item[2][axis][0]+item[2][axis][1])/2)
        mid=len(rows)//2
        return bounds,build(rows[:mid]),build(rows[mid:]),None
    return build(entries)


def _distance_bbox2(point,bounds):
    return sum((lo-point[i])**2 if point[i]<lo else
               (point[i]-hi)**2 if point[i]>hi else 0.
               for i,(lo,hi) in enumerate(bounds))


def _near_signed_faces(root,point,*,limit=1.25):
    """Return nearest painted/plain distances from source facets within 1.25mm."""
    best=[limit*limit,limit*limit]
    stack=[root]
    while stack:
        bounds,left,right,rows=stack.pop()
        if _distance_bbox2(point,bounds)>max(best):
            continue
        if rows is not None:
            for kind,triangle,box in rows:
                if _distance_bbox2(point,box)>best[kind]:
                    continue
                distance=_point_triangle_dist2(point,triangle)
                if distance<best[kind]:best[kind]=distance
        else:
            choices=sorted((left,right),
                           key=lambda node:_distance_bbox2(point,node[0]),
                           reverse=True)
            stack.extend(choices)
    return tuple(math.sqrt(value) for value in best)


def inspect_prusa_curved_surface(project,tool):
    """Require exactly one native ModelPart with genuine noncoplanar paint."""
    if (not isinstance(project,bytes) or not 0<len(project)<=32*1024*1024
            or type(tool) is not int or not 1<=tool<=7):
        raise WorkerError("Invalid native Prusa curved painted 3MF.")
    try:
        with zipfile.ZipFile(io.BytesIO(project)) as z:
            if (z.getinfo(MODEL).file_size>80*1024*1024 or
                    z.getinfo(CONFIG).file_size>65536):
                raise ValueError("Unbounded Prusa curved source.")
            model=SafeET.fromstring(z.read(MODEL))
            config=SafeET.fromstring(z.read(CONFIG))
        objects=model.findall("./"+NS+"resources/"+NS+"object")
        records=config.findall("./object")
        if len(objects)!=1 or len(records)!=1:
            raise ValueError("Unqualified mixed Prusa native paint objects.")
        volumes=records[0].findall("./volume")
        if len(volumes)!=1:
            raise ValueError("Curved painting with modifiers lacks combined proof.")
        faces=objects[0].findall("./"+NS+"mesh/"+NS+"triangles/"+NS+"triangle")
        points=[tuple(float(v.get(key)) for key in ("x","y","z"))
                for v in objects[0].findall(
                    "./"+NS+"mesh/"+NS+"vertices/"+NS+"vertex")]
        if (not 20<=len(faces)<=300000 or not 10<=len(points)<=900000 or
                volumes[0].get("firstid")!="0" or
                volumes[0].get("lastid")!=str(len(faces)-1) or
                any(not all(math.isfinite(n) and abs(n)<2000 for n in pt)
                    for pt in points)):
            raise ValueError("Native curved ModelPart contains invalid faces.")
        metadata={n.get("key"):n.get("value")
                  for n in volumes[0].findall("./metadata")}
        if metadata!={"volume_type":"ModelPart","extruder":"1"}:
            raise ValueError("Unqualified native curved painted extrusion scope.")
        expected=next(state for state,value in PAINTED_STATES.items()
                      if value==tool)
        painted=[]
        plain=[]
        normals=[]
        for face in faces:
            state=face.get(PAINT)
            if state not in (None,expected):
                raise ValueError("Native curved source contains unselected colour.")
            tri=tuple(points[int(face.get(k))] for k in ("v1","v2","v3"))
            a,b,c=tri
            ab=_sub(b,a);ac=_sub(c,a)
            cross=(ab[1]*ac[2]-ab[2]*ac[1],
                   ab[2]*ac[0]-ab[0]*ac[2],
                   ab[0]*ac[1]-ab[1]*ac[0])
            norm=math.sqrt(_dot(cross,cross))
            if norm<=1e-8:
                raise ValueError("Degenerate native curved painted face.")
            if state==expected:
                painted.append(tri)
                normals.append(tuple(value/norm for value in cross))
            else:
                plain.append(tri)
        if len(painted)<4 or len(plain)<4:
            raise ValueError("Missing independent curved paint and plain facets.")
        root_normal=normals[0]
        if all(abs(_dot(root_normal,n))>.999 for n in normals):
            raise ValueError("Planar mask is not independently qualified curved paint.")
        return {"painted_facets":len(painted),
                "unpainted_facets":len(plain),
                "spatial_index":_surface_tree(painted,plain),
                "tool":tool}
    except WorkerError:
        raise
    except (OSError,ValueError,KeyError,TypeError,IndexError,AttributeError,
            OverflowError,StopIteration,zipfile.BadZipFile):
        raise WorkerError(
            "Native Prusa curved painting has an unqualified signed 3-D source.") from None


def audit_prusa_curved_surface_gcode(data,project,*,tool,tower=None):
    """Reject colour leakage using true finite 3D source facets and G1 extrusion."""
    source=inspect_prusa_curved_surface(project,tool)
    if not isinstance(data,bytes) or not 0<len(data)<=90*1024*1024:
        raise WorkerError("Invalid Prusa curved colour G-code.")
    allowed=(0,tool)
    counts={t:{"painted":0,"unpainted":0,"ambiguous":0}
            for t in allowed}
    if tower is not None:
        if (not isinstance(tower,(tuple,list)) or len(tower)!=5 or
                any(type(n) not in (int,float) or not math.isfinite(n)
                    for n in tower)):
            raise WorkerError("Invalid native curved MMU wipe tower.")
        tx,ty=tower[:2]
        tower_box=(tx-6,tx+65,ty-12,ty+45)
        purges={t:0 for t in allowed}
    else:
        tower_box=None
        purges=None
    tool_active=None
    pos=[None,None,None]
    e=0.
    rel_e=rel_xyz=False
    role=""
    for index,raw in enumerate(io.BytesIO(data)):
        if index>=2_000_000 or len(raw)>16384:
            raise WorkerError("Prusa curved G-code exceeds bounded scan budget.")
        try:
            line=raw.decode("utf-8").strip()
        except UnicodeDecodeError:
            raise WorkerError("Invalid Prusa curved G-code encoding.") from None
        if line.startswith(";TYPE:"):
            role=line.partition(":")[2].strip().lower()
        cmd=line.split(";",1)[0].strip()
        if not cmd:continue
        op=cmd.split(None,1)[0].upper()
        if op.startswith("T") and op[1:].isdigit():
            tool_active=int(op[1:])
            if tool_active not in counts:
                raise WorkerError("Unexpected Prusa curved painted tool.")
            continue
        if op not in ("M82","M83","G90","G91","G92",
                      "G0","G00","G1","G01"):
            continue
        words={k.upper():float(v) for k,v in WORD.findall(cmd)}
        if any(not math.isfinite(v) or abs(v)>1e9 for v in words.values()):
            raise WorkerError("Nonfinite Prusa curved G-code position.")
        if op=="M82":rel_e=False
        elif op=="M83":rel_e=True
        elif op=="G90":rel_xyz=False
        elif op=="G91":rel_xyz=True
        elif op=="G92":
            e=words.get("E",e)
            for i,key in enumerate("XYZ"):
                if key in words:pos[i]=words[key]
        else:
            before=tuple(pos)
            for i,key in enumerate("XYZ"):
                if key in words:
                    pos[i]=(pos[i]+words[key] if rel_xyz and
                            pos[i] is not None else None if rel_xyz
                            else words[key])
            if "E" not in words:
                continue
            delta=words["E"] if rel_e else words["E"]-e
            e=e+words["E"] if rel_e else words["E"]
            if (purges is not None and tool_active in counts and
                    op in ("G1","G01") and delta>1e-6 and
                    all(n is not None for n in (before[0],before[1],pos[0],pos[1])) and
                    tower_box[0]<=before[0]<=tower_box[1] and
                    tower_box[2]<=before[1]<=tower_box[3] and
                    tower_box[0]<=pos[0]<=tower_box[1] and
                    tower_box[2]<=pos[1]<=tower_box[3]):
                purges[tool_active]+=1
            if (tool_active not in counts or delta<=1e-6 or
                    op not in ("G1","G01") or role!="external perimeter" or
                    any(n is None for n in before+tuple(pos))):
                continue
            if abs(pos[0]-before[0])+abs(pos[1]-before[1])<=1e-6:
                continue
            midpoint=tuple((a+b)/2 for a,b in zip(before,pos))
            plain,painted=_near_signed_faces(
                source["spatial_index"],midpoint)
            if min(plain,painted)>.85 or abs(plain-painted)<.17:
                counts[tool_active]["ambiguous"]+=1
                continue
            counts[tool_active]["painted" if painted<plain else "unpainted"]+=1
    if (counts[tool]["painted"]<20 or counts[0]["unpainted"]<35 or
            counts[tool]["unpainted"]>max(3,counts[tool]["painted"]//20) or
            counts[0]["painted"]>max(10,counts[tool]["painted"]//6)):
        raise WorkerError(
            "Native Prusa curved positive-E toolpaths contradict the "
            "source-derived painted/unpainted 3D surface.")
    if purges is not None and any(value<10 for value in purges.values()):
        raise WorkerError("Prusa curved MMU colour output lacked T0/T1 native purging.")
    return {"tool":tool,"curved_surface_moves":counts,
            "painted_facets":source["painted_facets"],
            "tower_extrusion_moves":purges,
            "wipe_tower":tower is not None,"offline_only":True}
