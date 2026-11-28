"""Research pinned Prusa 2.9.7 MMU5 genuinely curved partial colour and purging.

Unlike XL5, every T1 brush colour change on a single-nozzle MMU needs
native positive-E purges from BOTH tools at the owner-authenticated tower.
The same signed nonplanar source has to pass genuine G-code deposition and
the strict 3D BVH nearest-facet audit before runtime admission is widened.
"""
import hashlib
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from core.slicer_prusa_colour_project import build_prusa_colour_candidate
from core.slicer_prusa_filament_palette import compile_prusa_filament_palette
from core.slicer_prusa_process_settings import apply_prusa_process_overrides
from core.slicer_prusa_purge import compile_prusa_purge_matrix
from core.slicer_prusa_wipe_tower import add_prusa_native_wipe_tower
from scripts.prusa_native_curved_colour_research import (
    cylinder_stl,mask_for,deposited_sectors)
from slicer_worker.prusa_curved_surface import (
    inspect_prusa_curved_surface,audit_prusa_curved_surface_gcode)
from slicer_worker.prusa_vendor_profiles import (
    flatten_prusa_vendor_preset,validate_flat_prusa_preset)
from slicer_worker.prusa_gcode_audit import (
    run_prusa_mmu_with_numeric_recheck,audit_prusa_positive_e)
from slicer_worker.runner import run_prusa


def main(binary,vendor):
    blob=Path(vendor).read_bytes()
    sha=hashlib.sha256(blob).hexdigest()
    def preset(kind,name):
        return flatten_prusa_vendor_preset(
            blob,kind=kind,name=name,expected_sha256=sha)
    printer=preset("printer","Original Prusa i3 MK3S & MK3S+ MMU3")
    material=validate_flat_prusa_preset(
        preset("filament","Generic PLA"),kind="filament")
    profiles=[]
    for temperature in (205,210,215,220,225):
        selected={**material,"temperature":str(temperature),
                  "first_layer_temperature":str(temperature)}
        profiles.append("".join(f"{k} = {v}\n"
                        for k,v in sorted(selected.items())).encode())
    filament=compile_prusa_filament_palette(printer,profiles)
    process=apply_prusa_process_overrides(
        preset("print","0.20mm NORMAL"),
        {"layer_height":.16,"wall_loops":3})
    process=compile_prusa_purge_matrix(
        printer,process,[[0 if i==j else 80 for j in range(5)]
                         for i in range(5)])
    mesh=cylinder_stl()
    paint=mask_for(mesh)
    project=build_prusa_colour_candidate(
        {"asset_id":"mmu-curved-brush","x_mm":0,"y_mm":0,
         "z_mm":0,"rotation_deg":0,"scale_percent":100,
         "colour_paint":paint},
        mesh,printer_ini=printer,colour_tool_indices={1:1},
        bed_width=250,bed_depth=210)
    project=add_prusa_native_wipe_tower(
        project,x_mm=55,y_mm=150,rotation_deg=0,
        bed_width=250,bed_depth=210)
    signed=inspect_prusa_curved_surface(project,1)
    assert signed["painted_facets"]>=20 and signed["unpainted_facets"]>=100
    tower=(55,150,0,250,210)
    with TemporaryDirectory(prefix="prusa-mmu-curved-") as directory:
        work=Path(directory)
        for name,data in (("input.3mf",project),("printer.ini",printer),
                          ("filament.ini",filament),("process.ini",process)):
            (work/name).write_bytes(data)
        (work/"prusa-offline-colour.marker").write_text("v1")
        _,gcode=run_prusa_mmu_with_numeric_recheck(
            run_prusa,Path(binary),work,timeout_seconds=300,
            max_bytes=64*1024*1024)
        audit_prusa_positive_e(gcode)
        geometric=deposited_sectors(gcode,center=(125.,105.))
        proof=audit_prusa_curved_surface_gcode(
            gcode,project,tool=1,tower=tower)
        print("PASS: native MMU5 curved partial colour and signed T0/T1 "
              "surface and purge attribution",geometric,proof,
              hashlib.sha256(gcode).hexdigest(),flush=True)


if __name__=="__main__":
    main(*sys.argv[1:])
