"""Real pinned PrusaSlicer 2.9.7 MMU3 five-tool painted-wall acceptance.

Exercises actual palette, directional purge, native 3MF tower and positive-E
external perimeter deposition. Research-only: never approves printer upload.
"""
import base64
import hashlib
import uuid
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory

from core.slicer_prusa_colour_project import build_prusa_colour_candidate
from core.slicer_prusa_filament_palette import compile_prusa_filament_palette
from core.slicer_prusa_purge import compile_prusa_purge_matrix
from core.slicer_prusa_wipe_tower import add_prusa_native_wipe_tower
from scripts.prusa_generate_mmu_paint import fixture
from slicer_worker.prusa_material_validation import validate_prusa_material_candidate
from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset, validate_flat_prusa_preset
from slicer_worker.prusa_gcode_audit import WORD, audit_prusa_positive_e
from slicer_worker.prusa_colour_gcode_audit import audit_prusa_offline_colour_gcode
from slicer_worker.service import _decode_payload
from slicer_worker.runner import run_prusa


def painted_external_walls(data):
    """Count actual per-tool positive-E on target and opposite wall."""
    counts = {i: {"front": 0, "back": 0} for i in range(5)}
    role = ""
    current = None
    extrusion = 0.0
    relative = False
    x = y = None
    for line in data.decode("utf-8").splitlines():
        if line.startswith(";TYPE:"):
            role = line.partition(":")[2].strip().lower()
        cmd = line.split(";", 1)[0].strip()
        if not cmd:
            continue
        op = cmd.split(None, 1)[0].upper()
        if re.fullmatch(r"T[0-4]", op):
            current = int(op[1:])
            continue
        if op not in ("G0", "G00", "G1", "G01", "M82", "M83", "G92"):
            continue
        params = {key.upper(): float(value) for key,value in WORD.findall(cmd)}
        if op == "M82":
            relative = False
        elif op == "M83":
            relative = True
        elif op == "G92":
            extrusion = params.get("E", extrusion)
        elif op in ("G0", "G00", "G1", "G01"):
            x = params.get("X", x)
            y = params.get("Y", y)
            if "E" not in params:
                continue
            amount = params["E"] if relative else params["E"] - extrusion
            extrusion = extrusion + params["E"] if relative else params["E"]
            if (amount <= 1e-6 or current not in counts or
                    "external perimeter" not in role or x is None or y is None or
                    not 114 <= x <= 136):
                continue
            if 93 <= y <= 97:
                counts[current]["front"] += 1
            elif 113 <= y <= 117:
                counts[current]["back"] += 1
    return counts


def main(binary, vendor):
    vendor_bytes = Path(vendor).read_bytes()
    checksum = hashlib.sha256(vendor_bytes).hexdigest()
    get = lambda kind, name: flatten_prusa_vendor_preset(
        vendor_bytes, kind=kind, name=name, expected_sha256=checksum)
    printer = get("printer", "Original Prusa i3 MK3S & MK3S+ MMU3")
    filament = get("filament", "Generic PLA")
    process = get("print", "0.20mm NORMAL")
    filament_data = validate_flat_prusa_preset(filament,kind="filament")
    native_filaments = []
    for t in (205,210,215,220,225):
        preset = dict(filament_data)
        preset["temperature"] = str(t)
        preset["first_layer_temperature"] = str(t)
        native_filaments.append("".join(
            f"{k} = {v}\n" for k,v in sorted(preset.items())).encode("utf-8"))
    palette = compile_prusa_filament_palette(printer,native_filaments)
    process = compile_prusa_purge_matrix(
        printer,process,[[0 if x == y else 80 for y in range(5)] for x in range(5)])
    stl, _bytes, _states, paint = fixture(include_paint=True)
    row = {"asset_id":"five-colour-native-paint", "x_mm":0, "y_mm":0,
           "z_mm":0, "rotation_deg":0, "scale_percent":100, "colour_paint":paint}
    with TemporaryDirectory(prefix="prusa-five-paint-") as folder:
        work = Path(folder)
        for name,data in (("printer.ini",printer),("filament.ini",palette),("process.ini",process)):
            (work/name).write_bytes(data)
        for tool in range(1,5):
            project=build_prusa_colour_candidate(
                row,stl,printer_ini=printer,colour_tool_indices={1:tool},
                bed_width=250,bed_depth=210)
            project=add_prusa_native_wipe_tower(
                project,x_mm=55,y_mm=150,rotation_deg=0,bed_width=250,bed_depth=210)
            receipt=validate_prusa_material_candidate(
                project,printer_ini=printer,colour=True,tower=(55,150,0,250,210))
            assert receipt["tools"] == (1,tool+1),receipt
            encode=lambda raw:base64.b64encode(raw).decode("ascii")
            request={
                "job_id":str(uuid.uuid4()),"engine":"prusaslicer",
                "engine_version":"2.9.7","model_format":"3mf",
                "model":encode(project),"printer_profile":encode(printer),
                "filament_profile":encode(palette),"process_profile":encode(process),
                "prusa_offline_colour":{"tool":tool,"tower":[55,150,0,250,210]},
            }
            decoded=_decode_payload(request)
            assert decoded["prusa_offline_colour"]["tool"]==tool
            jobdir=work/f"native-T{tool}"
            jobdir.mkdir()
            for name,data in (("input.3mf",project),("printer.ini",printer),
                              ("filament.ini",palette),("process.ini",process)):
                (jobdir/name).write_bytes(data)
            (jobdir/"prusa-offline-colour.marker").write_text("v1")
            run_prusa(Path(binary),jobdir)
            raw=(jobdir/"output.gcode").read_bytes()
            assert audit_prusa_positive_e(raw)["positive_e_moves"]>100
            independent=audit_prusa_offline_colour_gcode(
                raw,project,printer_ini=printer,tool=tool,
                tower=(55,150,0,250,210))
            assert independent["painted_wall_moves"][tool]["front"]>20
            print("Authenticated worker research audit",independent,flush=True)
            walls=painted_external_walls(raw)
            assert walls[tool]["front"]>20,walls
            assert walls[0]["back"]>20,walls
            assert walls[tool]["back"]<=max(2,walls[0]["back"]//100),walls
            print(f"PASS: genuine Prusa MMU facet T{tool} painted front / T0 back",
                  walls,"sha256",hashlib.sha256(raw).hexdigest(),flush=True)
    print("PASS: genuine Prusa 2.9.7 native T1-T4 painted facets with isolated wipe tower",
          flush=True)


if __name__=="__main__":
    main(*sys.argv[1:])
