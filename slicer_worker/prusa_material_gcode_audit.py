"""Prusa native multi-object toolpath audit for *offline* qualification only.

Uses real 3MF model vertices for moving XY positive-E deposition rather than
T commands, E-only toolchange recovery or the G-code header alone. Purge tower/physical transfer validation
is a separate gate. No production caller is enabled here.
"""
import io
import hashlib
import math
import re
import zipfile
from xml.etree import ElementTree as ET
from defusedxml import ElementTree as SafeET

from .prusa_material_validation import validate_prusa_material_candidate
from .runner import WorkerError

NS="{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
WORD=re.compile(r"(?:^|\s)([XYZE])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)",re.I)


def _bounds(project, expected):
    with zipfile.ZipFile(io.BytesIO(project)) as z:
        content=z.read("3D/3dmodel.model")
    root=SafeET.fromstring(content)
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


# SHA-256 of the *single reviewed upstream INDX 2.5.16* 8T
# toolchange_gcode, with the one qualified 2.9.7 placeholder translation.
# Do not trust G-code comments from arbitrary imported printer profiles.
_OFFICIAL_INDX_8T_TOOLCHANGE_SHA256 = (
    "0ecc93d74fd10a304a2b11a051c7b670a70cfe3ab5ee366a911c799af9f7d18e"
)


def _trusted_indx_cleaner_profile(printer_ini, tools, tower):
    """The exact pinned INDX 8T script, never an operator-supplied annotation."""
    if tower is not None or len(tools) != 8 or set(tools) != set(range(1, 9)):
        return False
    from .prusa_vendor_profiles import validate_flat_prusa_preset, PrusaPresetError
    try:
        settings = validate_flat_prusa_preset(printer_ini, kind="printer")
    except PrusaPresetError:
        return False
    script = settings.get("toolchange_gcode", "")
    return (settings.get("single_extruder_multi_material", "0") in ("0", "false")
            and len(settings.get("nozzle_diameter", "").split(",")) == 8
            and hashlib.sha256(script.encode("utf-8")).hexdigest()
            == _OFFICIAL_INDX_8T_TOOLCHANGE_SHA256)


def audit_prusa_material_model_gcode(data, project, *, printer_ini, tools, tower=None):
    validate_prusa_material_candidate(project,printer_ini=printer_ini,tools=tools,tower=tower)
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
    tower_hits={}
    if tower is not None:
        if tower[2] != 0:
            raise WorkerError("Rotated Prusa wipe towers require separate spatial qualification.")
        tx,ty=tower[:2]
        tower_box=(tx-6,tx+65,ty-12,ty+45)
        for box in bounds:
            if (min(box[1],tower_box[1])>max(box[0],tower_box[0]) and
                    min(box[3],tower_box[3])>max(box[2],tower_box[2])):
                raise WorkerError("Prusa material model overlaps the wipe tower audit region.")
        tower_hits={tool-1:0 for tool in tools}
    active=None
    e=0.
    relative=False
    relative_xy=False
    x=y=None
    used=set()
    trusted_cleaner = _trusted_indx_cleaner_profile(printer_ini, tools, tower)
    cleaner = flush = False
    flush_moves = flush_blocks = 0
    for line in lines:
        if len(line)>16384:
            raise WorkerError("Prusa material G-code line too long.")
        stripped=line.strip()
        # The pinned INDX 8T toolchange physically diverts extrusion into
        # its firmware cleaner (G12 S90/S91). Its five relative-XY purge
        # strokes otherwise appear to be located at the previous model XY.
        # Marker comments alone never authorize exclusion; they must occur
        # within this *exact pinned* firmware cleaner sequence.
        if stripped in (";FLUSH_START", ";FLUSH_END"):
            if not trusted_cleaner or not cleaner:
                raise WorkerError("Unqualified Prusa native cleaner markers.")
            if stripped == ";FLUSH_START":
                if flush or not relative_xy or active is None:
                    raise WorkerError("Invalid INDX cleaner sequence.")
                flush = True
                flush_moves = 0
            else:
                if not flush or not 3 <= flush_moves <= 8:
                    raise WorkerError("INDX native purge geometry is incomplete.")
                flush = False
                flush_blocks += 1
            continue
        cmd=line.split(";",1)[0].strip()
        if not cmd:
            continue
        op=cmd.split(None,1)[0].upper()
        if op == "G12" and trusted_cleaner:
            if re.search(r"(?:^|\s)S90(?:\s|$)", cmd):
                if cleaner or flush:
                    raise WorkerError("INDX native cleaner is already active.")
                cleaner = True
            elif re.search(r"(?:^|\s)S91(?:\s|$)", cmd):
                if not cleaner or flush:
                    raise WorkerError("INDX native cleaner was not closed.")
                cleaner = False
            continue
        if op.startswith("T") and op[1:].isdigit():
            if flush:
                raise WorkerError("INDX tool changed inside the purge geometry.")
            active=int(op[1:])
            if active not in {tool-1 for tool in tools}:
                raise WorkerError("Unexpected native Prusa material tool.")
            used.add(active)
            continue
        if op not in ("M82","M83","G90","G91","G92","G0","G00","G1","G01"):
            continue
        params={k.upper():float(v) for k,v in WORD.findall(cmd)}
        if any(not math.isfinite(v) or abs(v)>1e9 for v in params.values()):
            raise WorkerError("Prusa material toolpath contains invalid coordinates.")
        if flush and op in ("G90","G92","M82"):
            raise WorkerError("INDX purge altered native coordinate mode.")
        if op=="M82":
            relative=False
        elif op=="M83":
            relative=True
        elif op=="G90":
            relative_xy=False
        elif op=="G91":
            relative_xy=True
        elif op=="G92":
            e=params.get("E",e)
            x=params.get("X",x)
            y=params.get("Y",y)
        else:
            previous_x,previous_y=x,y
            if relative_xy:
                x=x+params["X"] if x is not None and "X" in params else (
                    None if "X" in params else x)
                y=y+params["Y"] if y is not None and "Y" in params else (
                    None if "Y" in params else y)
            else:
                x=params.get("X",x)
                y=params.get("Y",y)
            if "E" not in params:
                if (flush and (op not in ("G1","G01") or not relative_xy
                        or previous_x is None or previous_y is None or
                        x is None or y is None or "Z" in params or
                        abs(x-previous_x)+abs(y-previous_y)>2)):
                    raise WorkerError("Unexpected INDX purge travel.")
                continue
            amount=params["E"] if relative else params["E"]-e
            e=e+params["E"] if relative else params["E"]
            if flush:
                # The official INDX cleaner emits short, local movements
                # in G91/M83; exclude ONLY these, not arbitrary deposited
                # extrusion outside the explicitly fenced cleaner window.
                if (op not in ("G1","G01") or not relative or not relative_xy or
                        previous_x is None or previous_y is None or
                        x is None or y is None or
                        not 0 <= amount <= 80 or
                        not 0 < abs(x-previous_x)+abs(y-previous_y) <= 2):
                    raise WorkerError("Unexpected native INDX purge movement.")
                flush_moves += 1
                if flush_moves > 8:
                    raise WorkerError("INDX native purge has too many strokes.")
                continue
            if amount<=1e-6 or op not in ("G1","G01") or x is None or y is None:
                continue
            if tower is not None and active in tower_hits:
                # A native MMU wipe tower may purge filament at stationary
                # XY, which *is* physical extrusion into its dedicated
                # tower. Do not confuse legitimate tower purging with model
                # deposition under the next selected tool.
                if (tower_box[0]<=x<=tower_box[1] and
                        tower_box[2]<=y<=tower_box[3]):
                    tower_hits[active]+=1
            if (previous_x is None or previous_y is None
                    or abs(x-previous_x)+abs(y-previous_y)<=1e-7):
                # Stationary model/tool-change recovery is not a deposited
                # model segment; model attribution requires moving XY.
                continue
            for index,box in enumerate(bounds):
                if (box[0]-.15<=x<=box[1]+.15 and
                        box[2]-.15<=y<=box[3]+.15 and
                        box[0]-.15<=previous_x<=box[1]+.15 and
                        box[2]-.15<=previous_y<=box[3]+.15):
                    if active==tools[index]-1:
                        correct[index]+=1
                    else:
                        incorrect[index]+=1
    if trusted_cleaner and (flush or cleaner or flush_blocks < 1):
        raise WorkerError("Official INDX cleaner sequence did not complete.")
    if (used!={tool-1 for tool in tools} or any(
            good<20 or bad>(0 if trusted_cleaner else max(2,int(good*.01)))
            for good,bad in zip(correct,incorrect))):
        raise WorkerError("Native Prusa material toolpaths do not match the assigned model tools.")
    if tower is not None and any(count<20 for count in tower_hits.values()):
        raise WorkerError("Prusa material output lacks verified wipe tower extrusion.")
    return {"correct_extrusion_moves":correct,
            "incorrect_extrusion_moves":incorrect,
            "selected_tools":tuple(sorted(used)),
            "tower_extrusion_moves":tower_hits,
            "qualified_cleaner_flushes":flush_blocks}
