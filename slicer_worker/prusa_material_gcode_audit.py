"""Prusa native multi-object toolpath audit for *offline* qualification only.

Uses real 3MF model vertices for tool-local positive E deposition rather than
T commands or the G-code header alone. Purge tower/physical transfer validation
is a separate gate. No production caller is enabled here.
"""
import io
import math
import re
import zipfile
from xml.etree import ElementTree as ET

from .prusa_material_validation import validate_prusa_material_candidate
from .runner import WorkerError

NS="{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
WORD=re.compile(r"(?:^|\s)([XYZE])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)",re.I)


def _bounds(project, expected):
    with zipfile.ZipFile(io.BytesIO(project)) as z:
        content=z.read("3D/3dmodel.model")
    root=ET.fromstring(content)
    objects=root.findall("./"+NS+"resources/"+NS+"object")
    if len(objects)!=expected:
        raise WorkerError("Prusa material model footprint mismatch.")
    result=[]
    for obj in objects:
        vertices=obj.findall("./"+NS+"mesh/"+NS+"vertices/"+NS+"vertex")
        if not vertices:
            raise WorkerError("Prusa material object has no mesh.")
        coords=[(float(v.get("x")),float(v.get("y"))) for v in vertices]
        if any(not math.isfinite(value) for pt in coords for value in pt):
            raise WorkerError("Prusa material footprint contains invalid coordinates.")
        xs=[v[0] for v in coords]
        ys=[v[1] for v in coords]
        box=(min(xs),max(xs),min(ys),max(ys))
        if box[1]-box[0]<1 or box[3]-box[2]<1:
            raise WorkerError("Prusa material region has degenerate footprint.")
        for old in result:
            if min(box[1],old[1])+.4>max(box[0],old[0]) and (
                    min(box[3],old[3])+.4>max(box[2],old[2])):
                raise WorkerError("Prusa material model regions overlap.")
        result.append(box)
    return result


def audit_prusa_material_model_gcode(data, project, *, printer_ini, tools):
    validate_prusa_material_candidate(project,printer_ini=printer_ini,tools=tools)
    bounds=_bounds(project,len(tools))
    if not isinstance(data,bytes) or not 0<len(data)<=90*1024*1024:
        raise WorkerError("Invalid native Prusa multi-material G-code.")
    try:
        lines=data.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise WorkerError("Native Prusa multi-material output must be text.") from None
    if len(lines)>2_000_000:
        raise WorkerError("Prusa material G-code line limit exceeded.")
    correct=[0]*len(bounds)
    incorrect=[0]*len(bounds)
    active=None
    e=0.
    relative=False
    x=y=None
    used=set()
    for line in lines:
        if len(line)>16384:
            raise WorkerError("Prusa material G-code line too long.")
        cmd=line.split(";",1)[0].strip()
        if not cmd:
            continue
        op=cmd.split(None,1)[0].upper()
        if op.startswith("T") and op[1:].isdigit():
            active=int(op[1:])
            if active not in {tool-1 for tool in tools}:
                raise WorkerError("Unexpected native Prusa material tool.")
            used.add(active)
            continue
        if op not in ("M82","M83","G92","G0","G00","G1","G01"):
            continue
        params={k.upper():float(v) for k,v in WORD.findall(cmd)}
        if any(not math.isfinite(v) or abs(v)>1e9 for v in params.values()):
            raise WorkerError("Prusa material toolpath contains invalid coordinates.")
        if op=="M82":
            relative=False
        elif op=="M83":
            relative=True
        elif op=="G92":
            e=params.get("E",e)
        else:
            x=params.get("X",x)
            y=params.get("Y",y)
            if "E" not in params:
                continue
            amount=params["E"] if relative else params["E"]-e
            e=e+params["E"] if relative else params["E"]
            if amount<=1e-6 or op not in ("G1","G01") or x is None or y is None:
                continue
            for index,box in enumerate(bounds):
                if box[0]-.15<=x<=box[1]+.15 and box[2]-.15<=y<=box[3]+.15:
                    if active==tools[index]-1:
                        correct[index]+=1
                    else:
                        incorrect[index]+=1
    if (used!={tool-1 for tool in tools} or any(
            good<20 or bad>max(2,int(good*.01))
            for good,bad in zip(correct,incorrect))):
        raise WorkerError("Native Prusa material toolpaths do not match the assigned model tools.")
    return {"correct_extrusion_moves":correct,
            "incorrect_extrusion_moves":incorrect,
            "selected_tools":tuple(sorted(used))}
