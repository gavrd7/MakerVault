"""Pinned PrusaSlicer 2.9.7 eight-head INDX T5/T7 split-wall research only."""
import hashlib
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from core.slicer_plate_3mf import _triangles
from core.slicer_native_support_paint import _fingerprint
from core.slicer_prusa_colour_project import build_prusa_colour_candidate
from core.slicer_prusa_filament_palette import compile_prusa_filament_palette
from core.slicer_prusa_process_settings import apply_prusa_process_overrides
from scripts.prusa_generate_mmu_paint import fixture
from scripts.prusa_native_indx_eight_tool_smoke import candidate_printer
from slicer_worker.prusa_dual_partial import (
    inspect_prusa_dual_partial, audit_prusa_dual_partial_gcode)
from slicer_worker.prusa_material_validation import validate_prusa_material_candidate
from slicer_worker.prusa_vendor_profiles import (
    flatten_prusa_vendor_preset, validate_flat_prusa_preset)
from slicer_worker.runner import run_prusa


def main(binary, vendor):
    raw=Path(vendor).read_bytes()
    sha=hashlib.sha256(raw).hexdigest()
    def preset(kind,name):
        return flatten_prusa_vendor_preset(
            raw,kind=kind,name=name,expected_sha256=sha)
    printer=candidate_printer(
        preset("printer","Original Prusa XL - 5T 0.4 nozzle"))
    filament=validate_flat_prusa_preset(
        preset("filament","Generic PLA"),kind="filament")
    native=[]
    for temp in (205,210,215,220,225,230,235,240):
        values={**filament,"temperature":str(temp),
                "first_layer_temperature":str(temp)}
        native.append("".join(f"{k} = {v}\n" for k,v in sorted(
            values.items())).encode())
    palette=compile_prusa_filament_palette(printer,native)
    settings=validate_flat_prusa_preset(
        preset("print","0.20mm NORMAL"),kind="print")
    for key in ("wipe_tower","wipe_into_infill","wipe_into_objects"):
        settings[key]="0"
    process=apply_prusa_process_overrides(
        "".join(f"{key} = {value}\n"
                for key,value in sorted(settings.items())).encode(),
        {"layer_height":.16,"wall_loops":3})
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
               {"color":"#3ec0ff","label":"front T5"},
               {"color":"#fadd4d","label":"back T7"}],
           "regions":regions}
    row={"asset_id":"native-dual-brush","x_mm":0,"y_mm":0,
         "z_mm":0,"rotation_deg":0,"scale_percent":100,
         "colour_paint":paint}
    model=build_prusa_colour_candidate(
        row,stl,printer_ini=printer,colour_tool_indices={1:5,2:7},
        bed_width=360,bed_depth=360)
    mask=inspect_prusa_dual_partial(model,(5,7))
    assert mask["axis"]==1
    tools=validate_prusa_material_candidate(
        model,printer_ini=printer,colour=True,independent_colour=True)
    assert tools["tools"]==(1,6,8)
    with TemporaryDirectory(prefix="prusa-indx-dual-partial-") as folder:
        path=Path(folder)
        for name,content in (
                ("input.3mf",model),("printer.ini",printer),
                ("filament.ini",palette),("process.ini",process)):
            (path/name).write_bytes(content)
        (path/"prusa-offline-xl-colour.marker").write_text("v1")
        run_prusa(Path(binary),path,timeout_seconds=300)
        data=(path/"output.gcode").read_bytes()
        receipt=audit_prusa_dual_partial_gcode(
            data,model,printer_ini=printer,
            tools=(5,7),tower=None)
        print("PASS: genuine native Prusa INDX eight-head T5/T7 "
              "opposite painted walls",receipt,
              "sha256",hashlib.sha256(data).hexdigest(),flush=True)


if __name__=="__main__":
    main(*sys.argv[1:])
