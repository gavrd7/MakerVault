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
from slicer_worker.prusa_gcode_audit import WORD, audit_prusa_positive_e, run_prusa_mmu_with_numeric_recheck
from slicer_worker.prusa_colour_gcode_audit import audit_prusa_offline_colour_gcode
from slicer_worker.service import _decode_payload
from slicer_worker.runner import run_prusa, WorkerError


def painted_external_walls(data, *, center_x=125, center_y=105):
    """Count actual per-tool positive-E on target and opposite wall."""
    counts = {i: {"front": 0, "back": 0} for i in range(5)}
    role = ""
    current = None
    extrusion = 0.0
    relative = False
    relative_xy = False
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
        if op not in ("G0", "G00", "G1", "G01", "M82", "M83", "G90", "G91", "G92"):
            continue
        params = {key.upper(): float(value) for key,value in WORD.findall(cmd)}
        if op == "M82":
            relative = False
        elif op == "M83":
            relative = True
        elif op == "G90":
            relative_xy = False
        elif op == "G91":
            relative_xy = True
        elif op == "G92":
            extrusion = params.get("E", extrusion)
            x = params.get("X", x)
            y = params.get("Y", y)
        elif op in ("G0", "G00", "G1", "G01"):
            previous_x, previous_y = x, y
            if relative_xy:
                x = x+params["X"] if x is not None and "X" in params else x
                y = y+params["Y"] if y is not None and "Y" in params else y
            else:
                x = params.get("X", x)
                y = params.get("Y", y)
            if "E" not in params:
                continue
            amount = params["E"] if relative else params["E"] - extrusion
            extrusion = extrusion + params["E"] if relative else params["E"]
            if (amount <= 1e-6 or op not in ("G1", "G01") or
                    current not in counts or "external perimeter" not in role or
                    previous_x is None or previous_y is None or
                    x is None or y is None or
                    abs(x-previous_x)+abs(y-previous_y)<=1e-7 or
                    not center_x-11 <= x <= center_x+11 or
                    not center_x-11 <= previous_x <= center_x+11):
                continue
            if (center_y-12 <= y <= center_y-8 and
                    center_y-12 <= previous_y <= center_y-8):
                counts[current]["front"] += 1
            elif (center_y+8 <= y <= center_y+12 and
                      center_y+8 <= previous_y <= center_y+12):
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
    from core.slicer_prusa_process_settings import apply_prusa_process_overrides
    process = apply_prusa_process_overrides(process, {"layer_height": .16, "wall_loops": 3})
    assert b"layer_height = 0.16\n" in process and b"perimeters = 3\n" in process
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
            try:
                _receipt,raw=run_prusa_mmu_with_numeric_recheck(
                    run_prusa,Path(binary),jobdir,timeout_seconds=300,
                    max_bytes=64*1024*1024)
                assert audit_prusa_positive_e(raw)["positive_e_moves"]>100
            except WorkerError:
                output=jobdir/"output.gcode"
                raw=output.read_bytes() if output.exists() else b""
                # Synthetic, non-user 2.9.7 fixture: record only bounded
                # offending numeric coordinate metadata, never G-code or
                # private preset contents, to distinguish genuine native
                # overflow from a spatial-audit parser false positive.
                from slicer_worker.prusa_gcode_audit import WORD
                import math
                outliers=[]
                for number,line in enumerate(raw.splitlines()):
                    cmd=line.split(b";",1)[0].strip()
                    if not cmd: continue
                    opcode=cmd.split(None,1)[0].upper()
                    if opcode not in (b"G0",b"G00",b"G1",b"G01"): continue
                    for key,word in WORD.findall(cmd.decode("utf-8","replace")):
                        try: value=float(word)
                        except ValueError: continue
                        if not math.isfinite(value) or abs(value)>1e9:
                            outliers.append((number,key,len(word),
                                             "nonfinite" if not math.isfinite(value)
                                             else "out-of-range",
                                             "scientific" if "e" in word.lower()
                                             else "decimal",
                                             int(math.log10(abs(value))) if
                                             math.isfinite(value) and value else None))
                        if len(outliers)>=8: break
                    if len(outliers)>=8: break
                print("Prusa synthetic MMU colour numeric rejection",
                      "native tool",tool,"outlier categories",outliers,
                      flush=True)
                raise
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
        # Research a genuine THREE-tool painted object, not just one
        # alternate painted swatch. Two complete opposing vertical faces
        # map to different MMU tools; positive-E on the wrong wall is a
        # failure even if all three T commands appear in the G-code.
        from core.slicer_plate_3mf import _triangles
        from core.slicer_native_support_paint import _fingerprint
        triangles = list(_triangles(stl))
        lower = [min(p[a] for face in triangles for p in face) for a in range(3)]
        upper = [max(p[a] for face in triangles for p in face) for a in range(3)]
        origin = ((lower[0]+upper[0])/2, (lower[1]+upper[1])/2, lower[2])
        local = [[tuple(v[a]-origin[a] for a in range(3)) for v in face]
                 for face in triangles]
        by_side = {}
        for slot, ordinate in ((1, -10), (2, 10)):
            patches = [
                {"face": index,
                 "polygon": [list(v) for v in face]}
                for index, face in enumerate(local)
                if all(abs(v[1]-ordinate)<.00001 for v in face)]
            assert len(patches)==2, ("Missing painted wall", slot)
            by_side[slot] = patches
        multi = {**paint, "signature": _fingerprint(local),
                 "palette": [
                     {"color":"#ff8000","label":"base T0"},
                     {"color":"#3ec0ff","label":"front T1"},
                     {"color":"#fadd4d","label":"back T2"}],
                 "regions":[{"slot":slot,"patches":by_side[slot]}
                            for slot in (1,2)]}
        multi_project = build_prusa_colour_candidate(
            {**row, "colour_paint":multi}, stl,
            printer_ini=printer, colour_tool_indices={1:1, 2:2},
            bed_width=250, bed_depth=210)
        multi_project = add_prusa_native_wipe_tower(
            multi_project, x_mm=55, y_mm=150, rotation_deg=0,
            bed_width=250, bed_depth=210)
        receipt = validate_prusa_material_candidate(
            multi_project, printer_ini=printer, colour=True,
            tower=(55,150,0,250,210))
        assert receipt["tools"]==(1,2,3), receipt
        target = work/"native-two-painted-walls"
        target.mkdir()
        for name, data in (
                ("input.3mf",multi_project),("printer.ini",printer),
                ("filament.ini",palette),("process.ini",process)):
            (target/name).write_bytes(data)
        (target/"prusa-offline-colour.marker").write_text("v1")
        _receipt,gcode = run_prusa_mmu_with_numeric_recheck(
            run_prusa,Path(binary),target,timeout_seconds=300,
            max_bytes=64*1024*1024)
        counts = painted_external_walls(gcode)
        assert counts[1]["front"]>20 and counts[2]["back"]>20, counts
        assert counts[1]["back"]<=2 and counts[2]["front"]<=2, counts
        # Prusa's T0 base material still deposits edge/corner perimeters
        # around both painted walls; genuine native 2.9.7 counts T0
        # front=215/back=221. Only cross-use of the *alternate* T1/T2
        # tools is forbidden, not legitimate T0 foundation extrusion.
        assert counts[0]["front"]>0 and counts[0]["back"]>0, counts
        from slicer_worker.prusa_colour_gcode_audit import audit_prusa_dual_colour_gcode
        try:
            proof = audit_prusa_dual_colour_gcode(
                gcode, multi_project, printer_ini=printer, tools=(1,2),
                tower=(55,150,0,250,210))
        except WorkerError:
            # Diagnostic is bounded numeric metadata for a synthetic
            # fixture only; neither user G-code nor printer scripts are
            # ever exposed in logs.
            import math
            invalid=[]
            for lineno,line in enumerate(gcode.splitlines()):
                cmd=line.split(b";",1)[0].strip()
                if not cmd: continue
                opcode=cmd.split(None,1)[0].upper()
                if opcode not in (b"G0",b"G00",b"G1",b"G01",
                                  b"G90",b"G91",b"G92"): continue
                for axis,number in WORD.findall(cmd.decode("utf-8","replace")):
                    value=float(number)
                    if not math.isfinite(value) or abs(value)>1e9:
                        invalid.append((lineno,opcode.decode(),axis,
                                        len(number),
                                        "nonfinite" if not math.isfinite(value)
                                        else "out-of-range",
                                        "scientific" if "e" in number.lower()
                                        else "decimal",
                                        int(math.log10(abs(value))) if
                                        math.isfinite(value) and value else None))
                        if len(invalid)>=8: break
                if len(invalid)>=8: break
            print("Prusa synthetic dual-swatch numeric audit rejection",
                  invalid,flush=True)
            raise
        assert proof["wall_moves"][1]["front"]>20, proof
        assert proof["wall_moves"][2]["back"]>20, proof
        print("PASS: independently audited native three-tool painted MMU",
              proof, flush=True)
        print("PASS: research genuine Prusa MMU T1-front/T2-back multi-swatch",
              counts, "sha256",hashlib.sha256(gcode).hexdigest(),flush=True)
    print("PASS: genuine Prusa 2.9.7 native T1-T4 painted facets with isolated wipe tower",
          flush=True)


if __name__=="__main__":
    main(*sys.argv[1:])
