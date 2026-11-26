"""Real pinned Prusa 2.9.7 offline MMU worker request + native toolpath smoke.

Explicit fixture-only HTTP payload decoder + worker runner, not a production
job dispatcher and never printer submission.
"""
import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import uuid

from core.slicer_prusa_filament_palette import compile_prusa_filament_palette
from core.slicer_prusa_purge import compile_prusa_purge_matrix
from core.slicer_prusa_wipe_tower import add_prusa_native_wipe_tower
from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset
from slicer_worker.service import _decode_payload
from slicer_worker.runner import WorkerError, run_prusa
from slicer_worker.prusa_material_gcode_audit import audit_prusa_material_model_gcode


def main(binary, vendor, projects):
    raw = Path(vendor).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    printer = flatten_prusa_vendor_preset(
        raw,kind="printer",name="Original Prusa i3 MK3S & MK3S+ MMU3",
        expected_sha256=digest)
    filament = flatten_prusa_vendor_preset(
        raw,kind="filament",name="Generic PLA",expected_sha256=digest)
    process = flatten_prusa_vendor_preset(
        raw,kind="print",name="0.20mm NORMAL",expected_sha256=digest)
    parsed = dict(line.split("=",1) for line in [] )  # no profile mutation
    from slicer_worker.prusa_vendor_profiles import validate_flat_prusa_preset
    original = validate_flat_prusa_preset(filament,kind="filament")
    filaments = []
    for temperature in (205,220,205,205,205):
        values=dict(original)
        values["temperature"]=str(temperature)
        values["first_layer_temperature"]=str(temperature)
        filaments.append("".join(f"{key} = {value}\n" for key,value in sorted(values.items())).encode())
    palette=compile_prusa_filament_palette(printer,filaments)
    purge=compile_prusa_purge_matrix(
        printer,process,[[0 if i==j else 120 for j in range(5)] for i in range(5)])
    tower=[55,150,0,250,210]
    project=add_prusa_native_wipe_tower(
        (Path(projects)/"trusted.3mf").read_bytes(),
        x_mm=tower[0],y_mm=tower[1],rotation_deg=tower[2],
        bed_width=tower[3],bed_depth=tower[4])
    def encode(value):
        return base64.b64encode(value).decode("ascii")
    request={
        "job_id":str(uuid.uuid4()),"engine":"prusaslicer",
        "engine_version":"2.9.7","model_format":"3mf",
        "model":encode(project),"printer_profile":encode(printer),
        "filament_profile":encode(palette),"process_profile":encode(purge),
        "prusa_offline_mmu":{"tools":[1,2],"tower":tower},
    }
    decoded=_decode_payload(request)
    assert decoded["prusa_offline_mmu"]["tools"]==[1,2]
    for field in ("prusa_offline_mmu","process_profile"):
        altered=dict(request)
        if field=="prusa_offline_mmu":
            altered.pop(field)
        else:
            altered[field]=encode(purge.replace(b"wipe_tower = 1",b"wipe_tower = 0"))
        try:
            _decode_payload(altered)
        except WorkerError:
            pass
        else:
            raise AssertionError("Unsafe MMU request was accepted: "+field)
    with tempfile.TemporaryDirectory(prefix="prusa-offline-mmu-") as scratch:
        root=Path(scratch)
        for name,data in (("input.3mf",project),("printer.ini",printer),
                          ("filament.ini",palette),("process.ini",purge)):
            (root/name).write_bytes(data)
        (root/"prusa-offline-mmu.marker").write_text("v1")
        run_prusa(Path(binary),root)
        gcode=(root/"output.gcode").read_bytes()
        result=audit_prusa_material_model_gcode(
            gcode,project,printer_ini=printer,tools=[1,2],tower=tower)
        assert result["incorrect_extrusion_moves"]==[0,0]
        assert min(result["correct_extrusion_moves"])>100
        print("PASS: pinned Prusa authenticated offline MMU payload, native CLI and post-slice audit",
              result,"G-code SHA256",hashlib.sha256(gcode).hexdigest(),flush=True)


if __name__=="__main__":
    main(*sys.argv[1:])
