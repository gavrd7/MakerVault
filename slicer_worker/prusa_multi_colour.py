"""Signed independent native Prusa MMU colour ModelPart and G-code audits.

Separate models may own distinct material masks, but the worker must never
accept a combined file merely because each ModelPart contains paint tags.
Revalidate each object's complete signed source and compare positive-E
external walls and every native MMU purge against the combined G-code.
"""
import copy
import io
import math
import zipfile
from xml.etree import ElementTree as ET

from defusedxml import ElementTree as SafeET

from .prusa_material_validation import (
    MODEL, CONFIG, TOWER, PAINT, validate_prusa_material_candidate)
from .prusa_colour_gcode_audit import (
    NS, WORD, PAINTED_STATES, _wall_regions)
from .runner import WorkerError

PARTS=frozenset((MODEL,CONFIG,"[Content_Types].xml","_rels/.rels",TOWER))


def inspect_prusa_multi_colour(project, *, printer_ini, tower):
    """Revalidate each distinct signed object as an isolated native candidate.

    Only two nonintersecting complete vertical colour masks are currently
    qualified. Do not silently broaden this admission to multi-object
    partial or overlapping masks based on a successful 3MF import.
    """
    if not isinstance(project,bytes) or not 0<len(project)<=32*1024*1024:
        raise WorkerError("Invalid independent Prusa painted archive.")
    try:
        with zipfile.ZipFile(io.BytesIO(project)) as archive:
            infos=archive.infolist()
            if len(infos)!=len(PARTS) or {part.filename for part in infos}!=PARTS:
                raise ValueError("Unexpected Prusa multi-colour archive parts.")
            parts={name:archive.read(name) for name in PARTS}
        for name in (MODEL,CONFIG):
            if b"<!" in parts[name] or b"\0" in parts[name]:
                raise ValueError("Unsafe native Prusa multi-colour XML.")
        root=SafeET.fromstring(parts[MODEL])
        cfg=SafeET.fromstring(parts[CONFIG])
        resources=root.find(NS+"resources")
        build=root.find(NS+"build")
        objects=cfg.findall("./object")
        if (resources is None or build is None or len(resources)!=2 or
                len(build)!=2 or len(objects)!=2 or
                {obj.get("id") for obj in resources}!={"1","2"} or
                [node.get("id") for node in objects]!=["1","2"] or
                [part.get("objectid") for part in build]!=["1","2"]):
            raise ValueError("Multiple native painted ModelParts are not isolated.")
        metadata=[node.get("name") for node in root.findall(NS+"metadata")]
        if metadata.count("slic3rpe:MmPaintingVersion")!=1 or any(
                name not in ("slic3rpe:MmPaintingVersion","slic3rpe:Version3mf")
                for name in metadata):
            raise ValueError("Unqualified multi-object paint metadata.")
        receipt=[]
        for index in range(2):
            # Reconstruct a single signed candidate with no other printable
            # resources. The existing material validator checks every 3MF
            # facet, native volume, asset and palette extrusion binding.
            single=copy.deepcopy(root)
            single_resources=single.find(NS+"resources")
            single_build=single.find(NS+"build")
            for i in (1,0):
                if i!=index:
                    single_resources.remove(single_resources[i])
                    single_build.remove(single_build[i])
            single_resources[0].set("id","1")
            single_build[0].set("objectid","1")
            settings=ET.Element("config")
            volume=copy.deepcopy(objects[index])
            volume.set("id","1")
            settings.append(volume)
            candidate=io.BytesIO()
            with zipfile.ZipFile(candidate,"w",
                                 compression=zipfile.ZIP_DEFLATED,
                                 allowZip64=False) as out:
                for name,data in parts.items():
                    if name==MODEL:
                        data=ET.tostring(single,encoding="utf-8",
                                         xml_declaration=True)
                    elif name==CONFIG:
                        data=ET.tostring(settings,encoding="utf-8",
                                         xml_declaration=True)
                    out.writestr(name,data)
            one=candidate.getvalue()
            verified=validate_prusa_material_candidate(
                one,printer_ini=printer_ini,colour=True,tower=tower)
            if (verified["objects"]!=1 or len(verified["tools"])!=2 or
                    verified["tools"][0]!=1):
                raise ValueError("Unsigned native Prusa painted tool assignment.")
            tool=verified["tools"][1]-1
            front,back=_wall_regions(one,tool)
            if any(not math.isfinite(n) for box in (front,back)
                   for n in box):
                raise ValueError("Invalid native Prusa painted wall footprint.")
            receipt.append({"tool":tool,"painted":front,"unpainted":back})
        # Neither object may overlap any face region of the other, otherwise
        # extrusion toolpaths cannot be attributed to independent sources.
        for a in (receipt[0]["painted"],receipt[0]["unpainted"]):
            for b in (receipt[1]["painted"],receipt[1]["unpainted"]):
                if min(a[1],b[1])>max(a[0],b[0]) and min(a[3],b[3])>max(a[2],b[2]):
                    raise ValueError("Independent Prusa native paint regions overlap.")
        if {r["tool"] for r in receipt}!={1,2}:
            raise ValueError("Genuine multi-object MMU proof requires T1 and T2.")
        return tuple(receipt)
    except WorkerError:
        raise
    except (OSError,ValueError,TypeError,IndexError,KeyError,AttributeError,
            OverflowError,zipfile.BadZipFile,ET.ParseError):
        raise WorkerError("Unqualified independent Prusa signed colour project.") from None


def audit_prusa_multi_colour_gcode(data, project, *, printer_ini, tower):
    """Verify positive-E on each source wall, no cross-tool or plain leakage."""
    sources=inspect_prusa_multi_colour(
        project,printer_ini=printer_ini,tower=tower)
    if not isinstance(data,bytes) or not 0<len(data)<=90*1024*1024:
        raise WorkerError("Invalid Prusa independent painted G-code.")
    if (not isinstance(tower,(list,tuple)) or len(tower)!=5 or
            any(type(v) not in (int,float) or not math.isfinite(v)
                for v in tower)):
        raise WorkerError("Invalid Prusa independent painted wipe tower.")
    tx,ty=tower[:2]
    area=(tx-6,tx+65,ty-12,ty+45)
    counts=[{tool:{"painted":0,"plain":0} for tool in (0,1,2)}
            for _ in sources]
    purge={tool:0 for tool in (0,1,2)}
    x=y=None
    e=0.
    role=""
    active=None
    relative_e=relative_xy=False
    for line_number,raw in enumerate(io.BytesIO(data)):
        if line_number>=2_000_000 or len(raw)>16384:
            raise WorkerError("Prusa multi-colour G-code exceeds audit budget.")
        try:
            line=raw.decode("utf-8").strip()
        except UnicodeDecodeError:
            raise WorkerError("Prusa multi-colour G-code must be UTF-8.") from None
        if line.startswith(";TYPE:"):
            role=line.partition(":")[2].strip().lower()
        command=line.split(";",1)[0].strip()
        if not command:continue
        op=command.split(None,1)[0].upper()
        if op.startswith("T") and op[1:].isdigit():
            active=int(op[1:])
            if active not in purge:
                raise WorkerError("Unqualified native Prusa multi-colour tool.")
            continue
        if op not in ("M82","M83","G90","G91","G92",
                      "G0","G00","G1","G01"):
            continue
        words={k.upper():float(v) for k,v in WORD.findall(command)}
        if any(not math.isfinite(v) or abs(v)>1e9 for v in words.values()):
            raise WorkerError("Nonfinite native Prusa painted G-code coordinate.")
        if op=="M82":relative_e=False
        elif op=="M83":relative_e=True
        elif op=="G90":relative_xy=False
        elif op=="G91":relative_xy=True
        elif op=="G92":
            e=words.get("E",e)
            x=words.get("X",x)
            y=words.get("Y",y)
        else:
            old_x,old_y=x,y
            if relative_xy:
                x=x+words["X"] if x is not None and "X" in words else x
                y=y+words["Y"] if y is not None and "Y" in words else y
            else:
                x=words.get("X",x)
                y=words.get("Y",y)
            if "E" not in words:
                continue
            delta=words["E"] if relative_e else words["E"]-e
            e=e+words["E"] if relative_e else words["E"]
            if op not in ("G1","G01") or delta<=1e-6 or active not in purge:
                continue
            if None in (x,y,old_x,old_y):
                continue
            mid=((x+old_x)/2,(y+old_y)/2)
            if (area[0]<=x<=area[1] and area[2]<=y<=area[3] and
                    area[0]<=old_x<=area[1] and area[2]<=old_y<=area[3]):
                purge[active]+=1
            if (abs(x-old_x)+abs(y-old_y)<=1e-7 or
                    role!="external perimeter"):
                continue
            for index,source in enumerate(sources):
                for kind,region in (("painted",source["painted"]),
                                    ("plain",source["unpainted"])):
                    if (region[0]<=x<=region[1] and
                            region[2]<=y<=region[3] and
                            region[0]<=old_x<=region[1] and
                            region[2]<=old_y<=region[3]):
                        counts[index][active][kind]+=1
    for i,source in enumerate(sources):
        tool=source["tool"]
        if (counts[i][tool]["painted"]<20 or
                counts[i][0]["plain"]<20 or
                any(counts[i][other]["painted"]>2
                    for other in (0,1,2) if other!=tool) or
                any(counts[i][other]["plain"]>2
                    for other in (1,2))):
            raise WorkerError(
                "Native Prusa multi-colour G-code changed independent wall material.")
    if any(purge[t]<10 for t in (0,1,2)):
        raise WorkerError("Native Prusa multi-model colour omitted required wipe purging.")
    return {"per_model_wall_moves":counts,
            "tower_extrusion_moves":purge,
            "offline_only":True}
