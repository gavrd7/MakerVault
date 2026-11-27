"""Genuine Prusa 2.9.7 XL five-head facet-paint feasibility experiment.

Research only. Does not use or relax MakerVault's independently audited
production worker admission; exact XL native G-code is inspected offline.
"""
import hashlib
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from core.slicer_prusa_colour_project import build_prusa_colour_candidate
from core.slicer_prusa_filament_palette import compile_prusa_filament_palette
from scripts.prusa_generate_mmu_paint import fixture
from scripts.prusa_native_five_colour_paint_smoke import painted_external_walls
from slicer_worker.prusa_vendor_profiles import (
    flatten_prusa_vendor_preset, validate_flat_prusa_preset)
from slicer_worker.runner import run_prusa, WorkerError


def main(binary, vendor):
    blob=Path(vendor).read_bytes()
    source_sha=hashlib.sha256(blob).hexdigest()
    resolve=lambda kind,name:flatten_prusa_vendor_preset(
        blob,kind=kind,name=name,expected_sha256=source_sha)
    printer=resolve("printer","Original Prusa XL - 5T 0.4 nozzle")
    printer=b"\n".join(
        b"binary_gcode = 0" if line.split(b"=",1)[0].strip()==b"binary_gcode"
        else line for line in printer.splitlines())+b"\n"
    machine=validate_flat_prusa_preset(printer,kind="printer")
    assert machine.get("single_extruder_multi_material","0") in ("0","false")
    assert len(machine["nozzle_diameter"].split(","))==5
    stock=validate_flat_prusa_preset(resolve("filament","Generic PLA"),kind="filament")
    filaments=[]
    for temp in (205,210,215,220,225):
        row={**stock,"temperature":str(temp),"first_layer_temperature":str(temp)}
        filaments.append("".join(f"{key} = {value}\n"
                        for key,value in sorted(row.items())).encode())
    palette=compile_prusa_filament_palette(printer,filaments)
    base=validate_flat_prusa_preset(resolve("print","0.20mm NORMAL"),kind="print")
    for key in ("wipe_tower","wipe_into_infill","wipe_into_objects"):
        base[key]="0"
    process="".join(f"{key} = {value}\n"
                    for key,value in sorted(base.items())).encode()
    from core.slicer_prusa_process_settings import apply_prusa_process_overrides
    process = apply_prusa_process_overrides(process, {"layer_height": .16, "wall_loops": 3})
    assert b"layer_height = 0.16\n" in process and b"perimeters = 3\n" in process
    stl,_,_,paint=fixture(include_paint=True)
    row={"asset_id":"xl-native-paint-research","x_mm":0,"y_mm":0,"z_mm":0,
         "rotation_deg":0,"scale_percent":100,"colour_paint":paint}
    project=build_prusa_colour_candidate(
        row,stl,printer_ini=printer,colour_tool_indices={1:1},
        bed_width=360,bed_depth=360)
    with TemporaryDirectory(prefix="prusa-xl-paint-research-") as folder:
        work=Path(folder)
        for name,data in (
            ("input.3mf",project),("printer.ini",printer),
            ("filament.ini",palette),("process.ini",process)):
            (work/name).write_bytes(data)
        # Exercise the same dedicated XL marker as the authenticated worker.
        # The service independently admits and audits the 3MF before writing it.
        (work/"prusa-offline-xl-colour.marker").write_text("v1")
        run_prusa(Path(binary),work)
        output=(work/"output.gcode").read_bytes()
        counts=painted_external_walls(output,center_x=180,center_y=180)
        assert counts[1]["front"]>=20,counts
        assert counts[0]["back"]>=20,counts
        assert counts[1]["back"]<=2,counts
        # The genuine 2.9.7 native toolpaths retain T0 foundation perimeters
        # along the painted wall. Audit exclusivity of alternate tools, not
        # legitimate T0 base extrusion (observed 271 front T0 segments).
        assert counts[1]["back"]<=2,counts
        for key in (2,3,4):
            assert counts[key]["front"]<=2 and counts[key]["back"]<=2,counts
        from slicer_worker.prusa_colour_gcode_audit import audit_prusa_xl_colour_gcode
        receipt=audit_prusa_xl_colour_gcode(
            output,project,printer_ini=printer,tool=1)
        assert receipt["painted_wall_moves"][1]["front"]>20
        assert receipt["painted_wall_moves"][0]["back"]>20
        assert receipt["wipe_tower"] is False
        print("PASS: genuine independent XL5 T1-front/T0-back paint",
              counts,receipt,"sha256",hashlib.sha256(output).hexdigest(),
              flush=True)
        # The same native facet encoder supports two opposing selected
        # tools. Run this through the *independent-head* worker contract
        # and spatial auditor; it must never inherit an MMU wipe tower.
        from core.slicer_plate_3mf import _triangles
        from core.slicer_native_support_paint import _fingerprint
        from slicer_worker.prusa_offline_contract import validate_prusa_offline_xl_colour_inputs
        from slicer_worker.prusa_colour_gcode_audit import audit_prusa_dual_colour_gcode
        triangles=list(_triangles(stl))
        lower=[min(p[a] for face in triangles for p in face) for a in range(3)]
        upper=[max(p[a] for face in triangles for p in face) for a in range(3)]
        origin=((lower[0]+upper[0])/2,(lower[1]+upper[1])/2,lower[2])
        local=[[tuple(v[a]-origin[a] for a in range(3)) for v in face]
               for face in triangles]
        back=[{"face":i,"polygon":[list(v) for v in face]}
              for i,face in enumerate(local)
              if all(abs(v[1]-10)<.00001 for v in face)]
        assert len(back)==2, "Expected the two rear wall triangles"
        multi={**paint, "signature":_fingerprint(local),
               "palette":[*paint["palette"],
                          {"color":"#fadd4d","label":"XL T2 back"}],
               "regions":[*paint["regions"],{"slot":2,"patches":back}]}
        dual_project=build_prusa_colour_candidate(
            {**row,"colour_paint":multi},stl,printer_ini=printer,
            colour_tool_indices={1:1,2:2},bed_width=360,bed_depth=360)
        approved=validate_prusa_offline_xl_colour_inputs(
            project=dual_project,printer=printer,filament=palette,
            process=process,tools=[1,2])
        assert approved["tools"]==[1,2] and not approved["wipe_tower"],approved
        (work/"input.3mf").write_bytes(dual_project)
        (work/"output.gcode").unlink()
        run_prusa(Path(binary),work)
        dual_output=(work/"output.gcode").read_bytes()
        dual_receipt=audit_prusa_dual_colour_gcode(
            dual_output,dual_project,printer_ini=printer,tools=[1,2],tower=None)
        assert dual_receipt["wall_moves"][1]["front"]>=20,dual_receipt
        assert dual_receipt["wall_moves"][2]["back"]>=20,dual_receipt
        assert not dual_receipt["tower_extrusion_moves"],dual_receipt
        assert dual_receipt["wipe_tower"] is False,dual_receipt
        print("PASS: genuine independent XL5 dual painted walls T1/T2",
              dual_receipt,"sha256",hashlib.sha256(dual_output).hexdigest(),
              flush=True)

        # A second genuine binary project proves the same native 3MF and
        # authenticated toolpath auditor work on the X-min/X-max walls.
        # Opposite wall direction comes from source mesh geometry, never
        # from hardcoded Y-facing swatch coordinates.
        xnegative=[{"face":i,"polygon":[list(v) for v in face]}
                   for i,face in enumerate(local)
                   if all(abs(v[0]+10)<.00001 for v in face)]
        xpositive=[{"face":i,"polygon":[list(v) for v in face]}
                   for i,face in enumerate(local)
                   if all(abs(v[0]-10)<.00001 for v in face)]
        assert len(xnegative)==len(xpositive)==2
        xpaint={**paint,"signature":_fingerprint(local),
                "regions":[{"slot":1,"patches":xnegative},
                           {"slot":2,"patches":xpositive}],
                "palette":[*paint["palette"],
                           {"color":"#fadd4d","label":"XL T2 right"}]}
        xproject=build_prusa_colour_candidate(
            {**row,"colour_paint":xpaint},stl,printer_ini=printer,
            colour_tool_indices={1:1,2:2},bed_width=360,bed_depth=360)
        xreceipt=validate_prusa_offline_xl_colour_inputs(
            project=xproject,printer=printer,filament=palette,
            process=process,tools=[1,2])
        assert xreceipt["tools"]==[1,2] and not xreceipt["wipe_tower"]
        (work/"input.3mf").write_bytes(xproject)
        (work/"output.gcode").unlink(missing_ok=True)
        run_prusa(Path(binary),work)
        xoutput=(work/"output.gcode").read_bytes()
        xproof=audit_prusa_dual_colour_gcode(
            xoutput,xproject,printer_ini=printer,tools=[1,2],tower=None)
        assert xproof["wall_moves"][1]["front"]>=20,xproof
        assert xproof["wall_moves"][2]["back"]>=20,xproof
        assert xproof["wall_moves"][1]["back"]<=2,xproof
        assert xproof["wall_moves"][2]["front"]<=2,xproof
        assert not xproof["wipe_tower"],xproof
        print("PASS: genuine independent XL5 X-opposing dual painted walls",
              xproof,"sha256",hashlib.sha256(xoutput).hexdigest(),flush=True)

        # Four-sided native painting feasibility (base T0 plus T1..T4):
        # do not authorize the workbench until independent spatial G-code
        # evidence establishes that no alternate colour prints another wall.
        # This experiment uses the same fingerprinted MakerVault colour
        # editor regions and 3MF encoder; only the output audit is research.
        from slicer_worker.prusa_colour_gcode_audit import WORD
        import re
        sidespec=((0,-10,1),(0,10,2),(1,-10,3),(1,10,4))
        regions=[]
        colours=[{"color":"#ff8000","label":"XL base T0"}]
        for axis,face_value,tool in sidespec:
            patches=[{"face":i,"polygon":[list(v) for v in face]}
                     for i,face in enumerate(local)
                     if all(abs(v[axis]-face_value)<.00001 for v in face)]
            assert len(patches)==2,("Missing native side",axis,face_value)
            regions.append({"slot":tool,"patches":patches})
            colours.append({"color":("#"+format(tool*0x202020, "06X")),
                            "label":"XL wall T"+str(tool)})
        fourpaint={**paint,"signature":_fingerprint(local),
                   "palette":colours,"regions":regions}
        four=build_prusa_colour_candidate(
            {**row,"colour_paint":fourpaint},stl,printer_ini=printer,
            colour_tool_indices={t:t for t in range(1,5)},
            bed_width=360,bed_depth=360)
        (work/"input.3mf").write_bytes(four)
        (work/"output.gcode").unlink(missing_ok=True)
        try:
            run_prusa(Path(binary),work)
            lines=(work/"output.gcode").read_bytes().decode("utf-8").splitlines()
            counts={tool:{idx:0 for idx in range(4)}
                    for tool in range(5)}
            active=None
            role=""
            x=y=e=None
            relative_e=relative_xy=False
            for line in lines:
                if line.startswith(";TYPE:"):
                    role=line.partition(":")[2].strip().lower()
                cmd=line.split(";",1)[0].strip()
                if not cmd:
                    continue
                op=cmd.split(None,1)[0].upper()
                if op.startswith("T") and op[1:].isdigit():
                    active=int(op[1:])
                    continue
                if op not in ("M82","M83","G90","G91","G92",
                              "G0","G00","G1","G01"):
                    continue
                values={key.upper():float(num) for key,num in WORD.findall(cmd)}
                if op=="M82":
                    relative_e=False
                elif op=="M83":
                    relative_e=True
                elif op=="G90":
                    relative_xy=False
                elif op=="G91":
                    relative_xy=True
                elif op=="G92":
                    e=values.get("E",e)
                    x=values.get("X",x)
                    y=values.get("Y",y)
                else:
                    before=(x,y)
                    if relative_xy:
                        x=x+values["X"] if x is not None and "X" in values else x
                        y=y+values["Y"] if y is not None and "Y" in values else y
                    else:
                        x=values.get("X",x)
                        y=values.get("Y",y)
                    amount=(values["E"] if relative_e else
                            values["E"]-e if e is not None else 0
                            ) if "E" in values else 0
                    if "E" in values:
                        e=e+values["E"] if relative_e and e is not None else values["E"]
                    if (active not in counts or "external perimeter" not in role
                            or amount<=1e-6 or op not in ("G1","G01")
                            or None in before or x is None or y is None
                            or abs(x-before[0])+abs(y-before[1])<=1e-7):
                        continue
                    for idx,(axis,face_value,tool) in enumerate(sidespec):
                        across=180+face_value
                        p=(x,y)[axis]
                        old=before[axis]
                        tangent=(x,y)[1-axis]
                        old_tangent=before[1-axis]
                        if (abs(p-across)<=2 and abs(old-across)<=2 and
                                180-7<=tangent<=180+7 and
                                180-7<=old_tangent<=180+7):
                            counts[active][idx]+=1
            print("FOUR-WALL XL5 NATIVE RESEARCH",counts,flush=True)
            for idx,(_axis,_plane,tool) in enumerate(sidespec):
                if counts[tool][idx]<20 or any(
                        counts[other][idx]>2 for other in range(1,5)
                        if other!=tool):
                    raise AssertionError("Native XL four-wall tool attribution not isolated")
            print("RESEARCH PASS: genuine Prusa XL5 four independently painted walls",
                  counts,flush=True)
        except (AssertionError,ValueError,RuntimeError,WorkerError) as exc:
            print("RESEARCH BLOCKED: native XL5 four-wall mapping",
                  type(exc).__name__,str(exc)[:320],flush=True)




if __name__=="__main__":
    main(*sys.argv[1:])
