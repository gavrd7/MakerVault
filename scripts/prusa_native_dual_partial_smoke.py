"""Pinned PrusaSlicer 2.9.7 MMU two-swatch split-wall research only."""
import hashlib
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from core.slicer_plate_3mf import _triangles
from core.slicer_native_support_paint import _fingerprint
from core.slicer_prusa_colour_project import build_prusa_colour_candidate
from core.slicer_prusa_filament_palette import compile_prusa_filament_palette
from core.slicer_prusa_process_settings import apply_prusa_process_overrides
from core.slicer_prusa_purge import compile_prusa_purge_matrix
from core.slicer_prusa_wipe_tower import add_prusa_native_wipe_tower
from scripts.prusa_generate_mmu_paint import fixture
from slicer_worker.prusa_dual_partial import (
    inspect_prusa_dual_partial, audit_prusa_dual_partial_gcode)
from slicer_worker.prusa_material_validation import validate_prusa_material_candidate
from slicer_worker.prusa_gcode_audit import run_prusa_mmu_with_numeric_recheck
from slicer_worker.prusa_vendor_profiles import (
    flatten_prusa_vendor_preset, validate_flat_prusa_preset)
from slicer_worker.runner import run_prusa


def main(binary, vendor):
    raw=Path(vendor).read_bytes()
    sha=hashlib.sha256(raw).hexdigest()
    def preset(kind,name):
        return flatten_prusa_vendor_preset(
            raw,kind=kind,name=name,expected_sha256=sha)
    printer=preset("printer","Original Prusa i3 MK3S & MK3S+ MMU3")
    filament=validate_flat_prusa_preset(
        preset("filament","Generic PLA"),kind="filament")
    native=[]
    for temp in (205,210,215,220,225):
        values={**filament,"temperature":str(temp),
                "first_layer_temperature":str(temp)}
        native.append("".join(f"{k} = {v}\n" for k,v in sorted(
            values.items())).encode())
    palette=compile_prusa_filament_palette(printer,native)
    process=apply_prusa_process_overrides(
        preset("print","0.20mm NORMAL"),
        {"layer_height":.16,"wall_loops":3})
    process=compile_prusa_purge_matrix(
        printer,process,[[0 if i==j else 80 for j in range(5)]
                         for i in range(5)])
    stl,_,_,base=fixture(include_paint=True)
    original=list(_triangles(stl))
    minimum=[min(p[i] for f in original for p in f) for i in range(3)]
    maximum=[max(p[i] for f in original for p in f) for i in range(3)]
    centre=((minimum[0]+maximum[0])/2,
            (minimum[1]+maximum[1])/2,minimum[2])
    faces=[[tuple(p[i]-centre[i] for i in range(3)) for p in tri]
           for tri in original]
    regions=[]
    for index,(slot,coord) in enumerate(((1,-10),(2,10))):
        face_number=next(n for n,face in enumerate(faces)
                         if all(abs(p[1]-coord)<1e-5 for p in face))
        a,b,c=faces[face_number]
        region={"slot":slot,"patches":[{
            "face":face_number,
            "polygon":[list(a),
                       [(a[i]+b[i])/2 for i in range(3)],
                       [(a[i]+c[i])/2 for i in range(3)]]}]}
        regions.append(region)
    paint={**base,"signature":_fingerprint(faces),
           "palette":[
               {"color":"#808080","label":"T0 base"},
               {"color":"#3ec0ff","label":"front T1"},
               {"color":"#fadd4d","label":"back T2"}],
           "regions":regions}
    row={"asset_id":"native-dual-brush","x_mm":0,"y_mm":0,
         "z_mm":0,"rotation_deg":0,"scale_percent":100,
         "colour_paint":paint}
    model=build_prusa_colour_candidate(
        row,stl,printer_ini=printer,colour_tool_indices={1:1,2:2},
        bed_width=250,bed_depth=210)
    model=add_prusa_native_wipe_tower(
        model,x_mm=55,y_mm=150,rotation_deg=0,
        bed_width=250,bed_depth=210)
    mask=inspect_prusa_dual_partial(model,(1,2))
    assert mask["axis"]==1
    tools=validate_prusa_material_candidate(
        model,printer_ini=printer,colour=True,tower=(55,150,0,250,210))
    assert tools["tools"]==(1,2,3)
    from slicer_worker.prusa_offline_contract import validate_prusa_offline_colour_inputs
    signed = validate_prusa_offline_colour_inputs(
        project=model, printer=printer, filament=palette, process=process,
        tools=[1,2], tower=[55,150,0,250,210])
    assert signed["dual_partial"] and not signed["compound_volume"], signed
    with TemporaryDirectory(prefix="prusa-dual-partial-") as folder:
        path=Path(folder)
        for name,content in (
                ("input.3mf",model),("printer.ini",printer),
                ("filament.ini",palette),("process.ini",process)):
            (path/name).write_bytes(content)
        (path/"prusa-offline-colour.marker").write_text("v1")
        _,data=run_prusa_mmu_with_numeric_recheck(
            run_prusa,Path(binary),path,timeout_seconds=300,
            max_bytes=64*1024*1024)
        receipt=audit_prusa_dual_partial_gcode(
            data,model,printer_ini=printer,
            tools=(1,2),tower=(55,150,0,250,210))
        print("PASS: genuine native Prusa MMU two independently split "
              "opposite painted walls",receipt,
              "sha256",hashlib.sha256(data).hexdigest(),flush=True)


if __name__=="__main__":
    main(*sys.argv[1:])
