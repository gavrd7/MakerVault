"""Native-only evidence for per-object Prusa walls under different tools.

This is a controlled acceptance-fixture comparison, NOT a general-purpose
auditor of arbitrary model shapes. Both test cubes have the same geometry,
layer height, material and location-independent native presets. The sole
intentional difference is object-level perimeters/infill metadata.
"""
import math

from slicer_worker.prusa_material_gcode_audit import WORD, _bounds


def count_native_object_deposition(gcode, project, tools):
    boxes = _bounds(project, len(tools))
    if not isinstance(gcode, bytes) or len(gcode) > 90 * 1024 * 1024:
        raise ValueError("Invalid native Prusa object-settings G-code.")
    try:
        source = gcode.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("Prusa native G-code must be text.") from None
    active = None
    role = ""
    e = 0.
    x = y = None
    xyz_absolute = True
    e_absolute = True
    internal = [0]*len(boxes)
    sparse_infill = [0]*len(boxes)
    for line_number, text in enumerate(source.splitlines(),1):
        if line_number > 2_000_000 or len(text)>16384:
            raise ValueError("Native toolpath exceeds object-settings audit limits.")
        if text.startswith(";TYPE:"):
            role = text.partition(":")[2].strip().lower()
        instruction=text.split(";",1)[0].strip()
        if not instruction:
            continue
        op=instruction.split(None,1)[0].upper()
        if op.startswith("T") and op[1:].isdigit():
            active=int(op[1:])
            continue
        if op not in ("M82","M83","G90","G91","G92","G0","G00","G1","G01"):
            continue
        values={key.upper():float(value) for key,value in WORD.findall(instruction)}
        if any(not math.isfinite(v) or abs(v)>1e9 for v in values.values()):
            raise ValueError("Native toolpath has unbounded coordinates.")
        if op=="M82":
            e_absolute=True
        elif op=="M83":
            e_absolute=False
        elif op=="G90":
            xyz_absolute=True
        elif op=="G91":
            xyz_absolute=False
        elif op=="G92":
            e=values.get("E",e)
            x=values.get("X",x)
            y=values.get("Y",y)
        else:
            nx=(values["X"] if xyz_absolute or x is None else x+values["X"]) if "X" in values else x
            ny=(values["Y"] if xyz_absolute or y is None else y+values["Y"]) if "Y" in values else y
            amount=values.get("E",0) if not e_absolute else values.get("E",e)-e
            if "E" in values:
                e = values["E"]+e if not e_absolute else values["E"]
            x,y=nx,ny
            if (op not in ("G1","G01") or amount<=1e-6 or
                    x is None or y is None or active is None or
                    not ("perimeter" in role or "infill" in role)):
                continue
            for index,(xmin,xmax,ymin,ymax) in enumerate(boxes):
                if (active==tools[index]-1 and xmin-.15<=x<=xmax+.15
                        and ymin-.15<=y<=ymax+.15):
                    if "perimeter" in role and "external" not in role:
                        internal[index]+=1
                    if "infill" in role and not any(
                            excluded in role for excluded in ("solid","top","bottom","bridge")):
                        sparse_infill[index]+=1
    return {"internal":internal, "sparse_infill":sparse_infill}


def count_internal_perimeters(gcode, project, tools):
    return count_native_object_deposition(gcode,project,tools)["internal"]


def require_distinct_object_wall_counts(gcode, project, tools):
    counts=count_internal_perimeters(gcode,project,tools)
    # Fixture-only: model 0 has one wall; identical model 1 has five.
    # If the native CLI drops the object overrides, they inherit the
    # global three-wall setting and have comparable inner-perimeter paths.
    if not counts[1]>=20 or not counts[1]>max(4,counts[0]*1.8):
        raise AssertionError(
            "Native Prusa object-local perimeter overrides lack spatial proof: "
            + repr(counts[:2]))
    return {"internal_perimeter_moves":counts}


def require_distinct_object_infill(gcode, project, tools):
    counts=count_native_object_deposition(gcode,project,tools)["sparse_infill"]
    # Independent identical model pair 2/3 uses 10% vs 55% sparse infill,
    # same wall count and identical geometry. Fail if real G-code does not
    # show materially more model-local sparse-infill deposition for model 3.
    if not counts[3]>=20 or not counts[3]>max(4,counts[2]*1.5):
        raise AssertionError(
            "Native Prusa object-local sparse infill lacks spatial proof: "
            + repr(counts[2:4]))
    return {"sparse_infill_moves":counts}
