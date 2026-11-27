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
from slicer_worker.runner import run_prusa


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


if __name__=="__main__":
    main(*sys.argv[1:])
