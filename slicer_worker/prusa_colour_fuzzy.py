"""Strict signed native Prusa 2.9.7 MMU colour + selective fuzzy verifier.

Qualification: one printable model, one complete T1-painted vertical wall
and exactly one complete *opposite* native fuzzy-painted wall. Every slice
must prove T1 isolation/purge independently and actual additional moving,
short T0 exterior deposition in the fuzzy region. Never infer success from
3MF import or from a source attribute alone.
"""
import io
import math
import zipfile

from defusedxml import ElementTree as SafeET

from .prusa_colour_gcode_audit import NS, WORD, PAINTED_STATES, _wall_regions
from .prusa_material_validation import MODEL, PAINT
from .prusa_3mf_validation import CONFIG
from .runner import WorkerError

FUZZ="{http://schemas.slic3r.org/3mf/2017/06}fuzzy_skin"
FUZZ_HEADER="slic3rpe:FuzzySkinPaintingVersion"


def qualified_prusa_colour_fuzzy(project):
    """Identify only the genuine pinned MMU T1-front/opposite-fuzzy layout."""
    if not isinstance(project,bytes) or not 0<len(project)<=32*1024*1024:
        raise WorkerError("Invalid Prusa native painted fuzzy project.")
    try:
        with zipfile.ZipFile(io.BytesIO(project)) as archive:
            root=SafeET.fromstring(archive.read(MODEL))
            cfg=SafeET.fromstring(archive.read(CONFIG))
        resources=root.findall("./"+NS+"resources/"+NS+"object")
        objects=cfg.findall("./object")
        if len(resources)!=1 or len(objects)!=1:
            raise ValueError("Expected one printable Prusa painted ModelPart.")
        faces=resources[0].findall(
            "./"+NS+"mesh/"+NS+"triangles/"+NS+"triangle")
        vertices=resources[0].findall(
            "./"+NS+"mesh/"+NS+"vertices/"+NS+"vertex")
        records=objects[0].findall("./volume")
        version=[meta for meta in root.findall("./"+NS+"metadata")
                 if meta.get("name")==FUZZ_HEADER]
        fuzzy_count=sum(FUZZ in face.attrib for face in faces)
        if not version and not fuzzy_count:
            # An ordinary signed colour+modifier/cavity project remains
            # valid; only a *requested* fuzzy channel imposes one-volume
            # constraints. Do not reject unrelated qualified operations.
            return False
        if len(records)!=1:
            raise ValueError("Native mixed colour+fuzzy with volumes is unqualified.")
        if (len(version)!=1 or version[0].text!="2" or
                version[0].attrib!={"name":FUZZ_HEADER} or
                not fuzzy_count or len(faces)<4 or
                records[0].get("firstid")!="0" or
                records[0].get("lastid")!=str(len(faces)-1)):
            raise ValueError("Malformed native Prusa fuzzy/colour topology.")
        other_headers={"slic3rpe:FdmSupportsPaintingVersion",
                       "slic3rpe:SeamPaintingVersion"}
        if any(meta.get("name") in other_headers
               for meta in root.findall("./"+NS+"metadata")):
            raise ValueError("Unqualified simultaneous semantic-paint channel.")
        points=[tuple(float(v.get(k)) for k in ("x","y","z"))
                for v in vertices]
        if (not 4<=len(points)<=1_500_000 or
                any(not all(math.isfinite(n) and abs(n)<2000 for n in p)
                    for p in points)):
            raise ValueError("Invalid native Prusa source geometry.")
        marked=[]
        decoded=[]
        for face in faces:
            tri=tuple(points[int(face.get(k))] for k in ("v1","v2","v3"))
            if face.get(PAINT) is not None:
                if PAINTED_STATES.get(face.get(PAINT))!=1:
                    raise ValueError("Only Prusa MMU T1 native colour is qualified.")
                marked.extend(tri)
            if face.get(FUZZ) not in (None,"4"):
                raise ValueError("Only native painted fuzzy state 4 is qualified.")
            decoded.append((tri,face.get(FUZZ)))
        if not marked:
            raise ValueError("Native colour was not applied.")
        _wall_regions(project,1)
        plane=[]
        for axis in (0,1):
            lo=min(p[axis] for p in points)
            hi=max(p[axis] for p in points)
            if hi-lo<4:
                continue
            for front,opposite in ((lo,hi),(hi,lo)):
                if all(abs(p[axis]-front)<.0001 for p in marked):
                    plane.append((axis,opposite))
        if len(plane)!=1:
            raise ValueError("Prusa fuzzy mask lacks a unique opposite colour wall.")
        axis,back=plane[0]
        expected=0
        for tri,state in decoded:
            on_back=all(abs(p[axis]-back)<.0001 for p in tri)
            if on_back:
                expected+=1
                if state!="4":
                    raise ValueError("Prusa opposite fuzzy wall is not fully painted.")
            elif state is not None:
                raise ValueError("Prusa selective fuzzy leaked onto unrelated facets.")
        if expected<2 or expected!=fuzzy_count:
            raise ValueError("Missing native Prusa back-wall fuzzy facets.")
        return True
    except WorkerError:
        raise
    except (OSError,ValueError,TypeError,KeyError,IndexError,AttributeError,
            OverflowError,zipfile.BadZipFile,StopIteration):
        raise WorkerError("Unqualified signed Prusa colour/fuzzy composition.") from None


def audit_prusa_colour_fuzzy_gcode(data,project):
    """Verify the independently painted T0 back-face texture on actual G-code."""
    if not qualified_prusa_colour_fuzzy(project):
        raise WorkerError("Prusa G-code has no qualified selective fuzzy region.")
    if not isinstance(data,bytes) or not 0<len(data)<=90*1024*1024:
        raise WorkerError("Invalid Prusa colour/fuzzy G-code.")
    front,back=_wall_regions(project,1)
    x=y=z=None
    e=0.
    relative_e=relative_xyz=False
    role=""
    tool=None
    back_hits=front_hits=0
    for index,raw in enumerate(io.BytesIO(data)):
        if index>=2_000_000 or len(raw)>16384:
            raise WorkerError("Prusa fuzzy/colour G-code exceeds native audit limits.")
        try:
            line=raw.decode("utf-8").strip()
        except UnicodeDecodeError:
            raise WorkerError("Native fuzzy G-code is not UTF-8.") from None
        if line.startswith(";TYPE:"):
            role=line.partition(":")[2].strip().lower()
        cmd=line.split(";",1)[0].strip()
        if not cmd:
            continue
        op=cmd.split(None,1)[0].upper()
        if op.startswith("T") and op[1:].isdigit():
            tool=int(op[1:])
            if tool not in (0,1):
                raise WorkerError("Unselected native fuzzy/colour tool.")
            continue
        if op not in ("M82","M83","G90","G91","G92",
                      "G0","G00","G1","G01"):
            continue
        words={k.upper():float(v) for k,v in WORD.findall(cmd)}
        if any(not math.isfinite(v) or abs(v)>1e9 for v in words.values()):
            raise WorkerError("Nonfinite Prusa fuzzy/colour coordinate.")
        if op=="M82": relative_e=False
        elif op=="M83": relative_e=True
        elif op=="G90": relative_xyz=False
        elif op=="G91": relative_xyz=True
        elif op=="G92":
            e=words.get("E",e)
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
            delta=words["E"] if relative_e else words["E"]-e
            e=e+words["E"] if relative_e else words["E"]
            if (op not in ("G1","G01") or delta<=1e-6 or
                    role!="external perimeter" or
                    None in old or x is None or y is None or z is None):
                continue
            length=math.hypot(x-old[0],y-old[1])
            if not .01<=length<=1.25:
                continue
            mx,my=(x+old[0])/2,(y+old[1])/2
            if not 3<=z<=2000:
                continue
            if back[0]<=mx<=back[1] and back[2]<=my<=back[3]:
                if tool!=0:
                    raise WorkerError("Prusa alternate colour deposited on fuzzy back face.")
                back_hits+=1
            elif front[0]<=mx<=front[1] and front[2]<=my<=front[3]:
                front_hits+=1
    # The same genuine 2.9.7 control had back=0, front=376. The
    # simultaneous colour+fuzzy fixture gave back=3091, front=376.
    # Demand a substantial *relative* back texture effect on every job;
    # never assert completion on a mere painted facet or G-code hash.
    if back_hits<120 or back_hits<3*max(1,front_hits):
        raise WorkerError(
            "Prusa painted native fuzzy facet did not create isolated "
            "short deposited back-wall perimeter paths.")
    return {"fuzzy_back_short_moves":back_hits,
            "other_front_short_moves":front_hits,
            "offline_only":True}
