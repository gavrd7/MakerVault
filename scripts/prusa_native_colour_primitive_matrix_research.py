"""Native Prusa 2.9.7 six-shape modifier/cavity compatibility with MMU colour.

Tests existing MakerVault primitive shapes against an actual T1-painted
ModelPart. No parser-only or changed-hash evidence: require T1 front exterior
deposition, actual modifier region extrusion and zero cavity interior E.
Do not broaden production acceptance until each shape passes this CLI audit.
"""
import hashlib
import sys
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from core.slicer_prusa_colour_project import build_prusa_colour_candidate
from core.slicer_prusa_filament_palette import compile_prusa_filament_palette
from core.slicer_prusa_process_settings import apply_prusa_process_overrides
from core.slicer_prusa_purge import compile_prusa_purge_matrix
from core.slicer_prusa_wipe_tower import add_prusa_native_wipe_tower
from core.slicer_modifier_volumes import PRIMITIVE_SHAPES
from scripts.prusa_generate_mmu_paint import fixture
from scripts.prusa_native_five_colour_paint_smoke import painted_external_walls
from slicer_worker.modifier_gcode_audit import (
    modifier_bounds,audit_modifier_positive_e)
from slicer_worker.prusa_gcode_audit import (
    run_prusa_mmu_with_numeric_recheck,audit_prusa_positive_e)
from slicer_worker.prusa_vendor_profiles import (
    flatten_prusa_vendor_preset,validate_flat_prusa_preset)
from slicer_worker.runner import run_prusa


def main(binary,vendor):
    raw=Path(vendor).read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    def preset(kind,name):
        return flatten_prusa_vendor_preset(
            raw,kind=kind,name=name,expected_sha256=digest)
    printer=preset("printer","Original Prusa i3 MK3S & MK3S+ MMU3")
    material=validate_flat_prusa_preset(
        preset("filament","Generic PLA"),kind="filament")
    filaments=[]
    for temperature in (205,210,215,220,225):
        values={**material,"temperature":str(temperature),
                "first_layer_temperature":str(temperature)}
        filaments.append("".join(f"{k} = {v}\n"
                        for k,v in sorted(values.items())).encode())
    palette=compile_prusa_filament_palette(printer,filaments)
    process=compile_prusa_purge_matrix(
        printer,apply_prusa_process_overrides(
            preset("print","0.20mm NORMAL"),
            {"layer_height":.16,"wall_loops":3}),
        [[0 if i==j else 80 for j in range(5)]
         for i in range(5)])
    stl,_,_,paint=fixture(include_paint=True)
    base={"asset_id":"painted-primitive-matrix","x_mm":0,"y_mm":0,
          "z_mm":0,"rotation_deg":0,"scale_percent":100,
          "colour_paint":paint}
    shapes=tuple(sorted(PRIMITIVE_SHAPES))
    with TemporaryDirectory(prefix="prusa-colour-primitive-") as directory:
        root=Path(directory)
        verified=[]
        for shape in shapes:
            for kind in ("modifier","negative"):
                native={
                    "id":str(uuid.uuid5(uuid.NAMESPACE_DNS,
                                       "painted-"+shape+"-"+kind)),
                    "shape":shape,"kind":kind,
                    "width_mm":12,"depth_mm":12,"height_mm":20,
                    "x_mm":0,"y_mm":0,"z_mm":10,
                    "settings":{"sparse_infill_density":85}
                               if kind=="modifier" else {},
                }
                project=build_prusa_colour_candidate(
                    {**base,"modifier_volumes":[native]},stl,
                    printer_ini=printer,colour_tool_indices={1:1},
                    bed_width=250,bed_depth=210,research_compound=True)
                project=add_prusa_native_wipe_tower(
                    project,x_mm=55,y_mm=150,rotation_deg=0,
                    bed_width=250,bed_depth=210)
                folder=root/(shape+"-"+kind)
                folder.mkdir()
                for name,blob in (
                        ("input.3mf",project),("printer.ini",printer),
                        ("filament.ini",palette),("process.ini",process)):
                    (folder/name).write_bytes(blob)
                (folder/"prusa-offline-colour.marker").write_text("v1")
                _,gcode=run_prusa_mmu_with_numeric_recheck(
                    run_prusa,Path(binary),folder,
                    timeout_seconds=300,max_bytes=64*1024*1024)
                assert audit_prusa_positive_e(gcode)["positive_e_moves"]>100
                walls=painted_external_walls(gcode)
                assert walls[1]["front"]>=20 and walls[1]["back"]<=2,(
                    shape,kind,"colour dropped",walls)
                bounds,kinds,meshes=modifier_bounds(
                    project,"prusaslicer",include_meshes=True)
                assert len(bounds)==len(kinds)==len(meshes)==1
                proof=audit_modifier_positive_e(
                    gcode,project,"prusaslicer")
                assert proof["modifier_count"]==1 and (
                    proof["negative_volume_count"]==(1 if kind=="negative" else 0))
                if kind=="negative":
                    assert proof["modifier_region_paths"]==[0]
                else:
                    assert proof["modifier_region_paths"][0]>0
                verified.append(shape+"-"+kind)
                print("Native Prusa painted primitive region",
                      shape,kind,proof,flush=True)
        assert len(verified)==len(shapes)*2
        print("PASS: genuine Prusa 2.9.7 T1 colour plus all six native "
              "modifiers and cavities with actual geometric deposition",
              verified,flush=True)


if __name__=="__main__":
    main(*sys.argv[1:])
