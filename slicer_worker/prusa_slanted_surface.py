"""Research-only signed Prusa planar painted surface audit.

A non-axis-aligned, *planar* surface is reconstructed directly from the
native 3MF and measured against positive-E exterior toolpaths. This is a
research auditor, not ordinary worker or printer-start admission.
"""
import io
import math
import zipfile

from defusedxml import ElementTree as SafeET
from .prusa_colour_gcode_audit import NS, WORD, PAINTED_STATES
from .prusa_material_validation import MODEL, PAINT
from .runner import WorkerError


def _cross(a,b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2],
            a[0]*b[1]-a[1]*b[0])


def _dot(a,b):
    return sum(x*y for x,y in zip(a,b))


def _sub(a,b):
    return tuple(x-y for x,y in zip(a,b))


def _inside(point,tri):
    a,b,c=tri
    d=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
    if abs(d)<1e-10:
        return False
    u=((b[1]-c[1])*(point[0]-c[0])+
       (c[0]-b[0])*(point[1]-c[1]))/d
    v=((c[1]-a[1])*(point[0]-c[0])+
       (a[0]-c[0])*(point[1]-c[1]))/d
    return min(u,v,1-u-v)>.02



def _surface_tree(painted, plain):
    """Balanced 2-D BVH; query only nearby projected native facets.

    Prusa's source can have hundreds of thousands of triangles. Comparing
    every exterior G-code move to all triangles would scale quadratically.
    """
    entries=[]
    for label, triangles in (("painted", painted), ("unpainted",plain)):
        for tri in triangles:
            xs=[point[0] for point in tri]
            ys=[point[1] for point in tri]
            entries.append((label,tri,(min(xs),max(xs),min(ys),max(ys))))
    def build(rows):
        bbox=(min(row[2][0] for row in rows),
              max(row[2][1] for row in rows),
              min(row[2][2] for row in rows),
              max(row[2][3] for row in rows))
        if len(rows)<=12:
            return (bbox,None,None,tuple(rows))
        axis=0 if bbox[1]-bbox[0]>=bbox[3]-bbox[2] else 2
        rows.sort(key=lambda row:(row[2][axis]+row[2][axis+1])/2)
        mid=len(rows)//2
        return (bbox,build(rows[:mid]),build(rows[mid:]),None)
    return build(entries)


def _surface_labels(root, point):
    labels=set()
    def search(node):
        bbox,left,right,leaf=node
        if not (bbox[0]<=point[0]<=bbox[1] and
                bbox[2]<=point[1]<=bbox[3]):
            return
        if leaf is not None:
            for label,tri,bounds in leaf:
                if (bounds[0]<=point[0]<=bounds[1] and
                        bounds[2]<=point[1]<=bounds[3] and
                        _inside(point,tri)):
                    labels.add(label)
        else:
            search(left)
            search(right)
    search(root)
    return labels

def inspect_prusa_slanted_surface(project,tool):
    if type(tool) is not int or tool not in PAINTED_STATES.values():
        raise WorkerError("Invalid native sloped paint tool.")
    if not isinstance(project,bytes) or not 0<len(project)<=32*1024*1024:
        raise WorkerError("Invalid native Prusa sloped colour project.")
    try:
        from .prusa_3mf_validation import CONFIG
        with zipfile.ZipFile(io.BytesIO(project)) as z:
            model=SafeET.fromstring(z.read(MODEL))
            config=SafeET.fromstring(z.read(CONFIG))
        records=config.findall("./object")
        if len(records)!=1:
            raise ValueError("Slanted painting requires one native object.")
        volumes=records[0].findall("./volume")
        if len(volumes)!=1:
            raise ValueError(
                "Slanted painting with typed volumes lacks combined native proof.")
        metadata={node.get("key"):node.get("value")
                  for node in volumes[0].findall("./metadata")}
        if metadata!={"volume_type":"ModelPart","extruder":"1"}:
            raise ValueError("Native slanted source is not one printable ModelPart.")
        objects=model.findall("./"+NS+"resources/"+NS+"object")
        if len(objects)!=1:
            raise ValueError("Native slanted paint needs one source object.")
        points=[tuple(float(v.get(k)) for k in ("x","y","z"))
                for v in objects[0].findall(
                    "./"+NS+"mesh/"+NS+"vertices/"+NS+"vertex")]
        faces=objects[0].findall(
            "./"+NS+"mesh/"+NS+"triangles/"+NS+"triangle")
        if (not 4<=len(faces)<=500000 or
                not 4<=len(points)<=1_500_000 or
                any(not all(math.isfinite(v) and abs(v)<2000 for v in p)
                    for p in points)):
            raise ValueError("Native sloped source geometry exceeds bounds.")
        selected=next(state for state,v in PAINTED_STATES.items()
                      if v==tool)
        triangles=[]
        for face in faces:
            tri=tuple(points[int(face.get(k))]
                      for k in ("v1","v2","v3"))
            state=face.get(PAINT)
            if state not in (None,selected):
                raise ValueError("Native slanted paint contains wrong swatch.")
            triangles.append((tri,state==selected))
        coloured=[tri for tri,painted in triangles if painted]
        if not coloured:
            raise ValueError("Native sloped paint has no selected facets.")
        triangle=coloured[0]
        origin=triangle[0]
        tangent=_sub(triangle[1],triangle[0])
        tangent_length=math.sqrt(_dot(tangent,tangent))
        if tangent_length<1e-5:
            raise ValueError("Degenerate slanted facet.")
        u=tuple(x/tangent_length for x in tangent)
        normal=_cross(tangent,_sub(triangle[2],triangle[0]))
        magnitude=math.sqrt(_dot(normal,normal))
        if magnitude<1e-5:
            raise ValueError("Invalid sloped plane normal.")
        normal=tuple(v/magnitude for v in normal)
        v=_cross(normal,u)
        # Horizontal top/bottom and axis-aligned vertical faces use their
        # separately proven stricter auditor, never this research path.
        if not .1<abs(normal[2])<.95:
            raise ValueError("Research only supports slanted planar walls.")
        def projected(p):
            vector=_sub(p,origin)
            return (_dot(vector,u),_dot(vector,v))
        painted=[]
        plain=[]
        for tri,state in triangles:
            coplanar=all(abs(_dot(_sub(p,origin),normal))<=.0002
                         for p in tri)
            if state and not coplanar:
                raise ValueError("Painted facets occupy multiple planes.")
            if coplanar:
                (painted if state else plain).append(
                    tuple(projected(p) for p in tri))
        if not painted or not plain:
            raise ValueError("Native slanted mask is not a split surface.")
        return {"tool":tool,"origin":origin,"normal":normal,
                "u":u,"v":v,"painted":tuple(painted),
                "unpainted":tuple(plain)}
    except (OSError,ValueError,TypeError,AttributeError,IndexError,KeyError,
            OverflowError,StopIteration,zipfile.BadZipFile):
        raise WorkerError(
            "Prusa sloped colour mask is not a single signed planar surface.") from None


def audit_prusa_slanted_surface_gcode(data, project, *,tool):
    signed=inspect_prusa_slanted_surface(project,tool)
    if not isinstance(data,bytes) or not 0<len(data)<=90*1024*1024:
        raise WorkerError("Invalid native sloped colour G-code.")
    counts={0:{"painted":0,"unpainted":0},
            tool:{"painted":0,"unpainted":0}}
    spatial=_surface_tree(signed["painted"],signed["unpainted"])
    x=y=z=None
    e=0.
    relative_e=relative_xyz=False
    role=""
    active=None
    for index,raw in enumerate(io.BytesIO(data)):
        if index>=2_000_000 or len(raw)>16384:
            raise WorkerError("Slanted Prusa colour G-code exceeds budget.")
        try:
            line=raw.decode("utf-8").strip()
        except UnicodeDecodeError:
            raise WorkerError("Invalid slanted colour G-code encoding.") from None
        if line.startswith(";TYPE:"):
            role=line.partition(":")[2].strip().lower()
        cmd=line.split(";",1)[0].strip()
        if not cmd:
            continue
        op=cmd.split(None,1)[0].upper()
        if op.startswith("T") and op[1:].isdigit():
            active=int(op[1:])
            if active not in counts:
                raise WorkerError("Unassigned native slanted painted tool.")
            continue
        if op not in ("M82","M83","G90","G91","G92","G0","G00","G1","G01"):
            continue
        words={k.upper():float(v) for k,v in WORD.findall(cmd)}
        if any(not math.isfinite(v) or abs(v)>1e9 for v in words.values()):
            raise WorkerError("Invalid slanted G-code number.")
        if op=="M82": relative_e=False
        elif op=="M83": relative_e=True
        elif op=="G90": relative_xyz=False
        elif op=="G91": relative_xyz=True
        elif op=="G92":
            e=words.get("E",e)
            x=words.get("X",x);y=words.get("Y",y);z=words.get("Z",z)
        else:
            before=(x,y,z)
            if relative_xyz:
                x=x+words["X"] if x is not None and "X" in words else x
                y=y+words["Y"] if y is not None and "Y" in words else y
                z=z+words["Z"] if z is not None and "Z" in words else z
            else:
                x=words.get("X",x);y=words.get("Y",y);z=words.get("Z",z)
            if "E" not in words:
                continue
            delta=words["E"] if relative_e else words["E"]-e
            e=e+words["E"] if relative_e else words["E"]
            if (op not in ("G1","G01") or delta<=1e-6 or
                    active not in counts or role!="external perimeter" or
                    None in before or x is None or y is None or z is None):
                continue
            midpoint=((x+before[0])/2,(y+before[1])/2,(z+before[2])/2)
            vector=_sub(midpoint,signed["origin"])
            if abs(_dot(vector,signed["normal"]))>.95:
                continue
            xy=(_dot(vector,signed["u"]),_dot(vector,signed["v"]))
            matched=_surface_labels(spatial,xy)
            if len(matched)==1:
                counts[active][matched[0]]+=1
    if (counts[tool]["painted"]<8 or counts[0]["unpainted"]<8 or
            counts[tool]["unpainted"]>max(2,counts[tool]["painted"]//25) or
            counts[0]["painted"]>max(2,counts[tool]["painted"]//8)):
        raise WorkerError(
            "Prusa sloped native colour deposition did not match signed "
            "surface (T1 painted=%d other=%d, T0 painted=%d other=%d)." %
            (counts[tool]["painted"],counts[tool]["unpainted"],
             counts[0]["painted"],counts[0]["unpainted"]))
    return {"tool":tool,"deposition_moves":counts,"offline_only":True}
