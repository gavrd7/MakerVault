"""Mandatory pinned Prusa 2.9.7 two-object support isolation acceptance.

This checks production's exact spatial audit against genuine CLI output in
both paint directions. No printer connection, imports or production changes.
"""
import hashlib
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset
from scripts.prusa_generate_support_overhang import cantilever, support_mask
from core.slicer_prusa_support_audit import audit_prusa_two_object_support


def main(binary, vendor, folder):
    raw = Path(vendor).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    raw_model = cantilever()
    with TemporaryDirectory(prefix="prusa-required-support-isolation-") as temp:
        root = Path(temp)
        native = []
        for kind, name in (("printer", "Original Prusa i3 MK2S"),
                           ("filament", "Generic PLA"),
                           ("print", "0.20mm NORMAL")):
            preset = flatten_prusa_vendor_preset(
                raw, kind=kind, name=name, expected_sha256=digest)
            if kind == "print":
                preset = b"\n".join(line for line in preset.splitlines()
                    if line.split(b"=", 1)[0].strip()
                    not in (b"support_material", b"support_material_auto")) + b"\n"
                preset += b"support_material = 1\nsupport_material_auto = 0\n"
            target = root / (kind + ".ini")
            target.write_bytes(preset)
            native.extend(["--load", str(target)])
        for side in ("left", "right"):
            painted = 0 if side == "left" else 1
            project = Path(folder) / (side + ".3mf")
            output = root / (side + ".gcode")
            subprocess.run(
                [binary, *native, "--export-gcode", "--dont-arrange",
                 "--output", str(output), str(project)],
                cwd=root, check=True, timeout=300)
            models = [(
                {"asset_id": "verified-" + key,
                 "x_mm": x, "y_mm": 0, "z_mm": 0,
                 "rotation_deg": 0, "scale_percent": 100,
                 **({"support_paint": support_mask(raw_model, 0)}
                    if painted == i else {})},
                raw_model,
            ) for i, (key, x) in enumerate((("left", -50), ("right", 50)))]
            result = audit_prusa_two_object_support(
                output.read_bytes(), models, bed_width=250, bed_depth=210)
            assert result["painted_model_index"] == painted, result
            assert result["unpainted_support_moves"] == 0, result
            print("PASS: pinned native Prusa two-object painted support isolation",
                  side, result, flush=True)

        # Production now has an independent N-object support auditor. Verify
        # the actual 2.9.7 CLI can generate a three-model plate with support
        # on one cantilever without introducing paths in either neighbour.
        from core.slicer_prusa_3mf import build_prusa_native_3mf
        from core.slicer_prusa_support_audit import audit_prusa_multi_object_support
        models = []
        for index, x in enumerate((-68, 0, 68)):
            row = {"asset_id": "three-support-" + str(index),
                   "x_mm": x, "y_mm": 0, "z_mm": 0,
                   "rotation_deg": 0, "scale_percent": 100}
            if index == 1:
                row["support_paint"] = support_mask(raw_model, 0)
            models.append((row, raw_model))
        project = build_prusa_native_3mf(
            models, bed_width=250, bed_depth=210)
        from core.slicer_prusa_3mf import validate_prusa_project_admission
        assert validate_prusa_project_admission(
            [row for row, _ in models], {}, "2.9.7") is False
        with open(root/"three-model.3mf", "wb") as target:
            target.write(project)
        output = root/"three-model.gcode"
        subprocess.run(
            [binary, *native, "--export-gcode", "--dont-arrange",
             "--output", str(output), str(root/"three-model.3mf")],
            cwd=root, check=True, timeout=300)
        checked = audit_prusa_multi_object_support(
            output.read_bytes(), models, bed_width=250, bed_depth=210)
        assert checked["painted_model_index"] == 1, checked
        assert checked["unpainted_support_moves"] == 0, checked
        print("PASS: real Prusa three-model painted-support isolation",
              checked, flush=True)

        # The same source/owner/worker spatial proof must scale beyond
        # the historical twelve-model special-case cap. Use the shared
        # MakerVault 200-instance plate budget and a genuine 15-object
        # native PrusaSlicer run with one deliberately painted cantilever.
        positions=[(x,y) for y in (-55,0,55)
                          for x in (-88,-44,0,44,88)]
        crowded=[]
        for index,(x,y) in enumerate(positions):
            obj={"asset_id":"support-scale-"+str(index),
                 "x_mm":x,"y_mm":y,"z_mm":0,
                 "rotation_deg":0,"scale_percent":100}
            if index==7:
                obj["support_paint"]=support_mask(raw_model,0)
            crowded.append((obj,raw_model))
        assert len(crowded)==15
        from core.slicer_prusa_support_audit import validate_prusa_multi_support_plate
        assert validate_prusa_multi_support_plate([obj for obj,_ in crowded])==7
        native_project=build_prusa_native_3mf(
            crowded,bed_width=250,bed_depth=210)
        (root/"fifteen-model.3mf").write_bytes(native_project)
        output=root/"fifteen-model.gcode"
        subprocess.run(
            [binary,*native,"--export-gcode","--dont-arrange",
             "--output",str(output),str(root/"fifteen-model.3mf")],
            cwd=root,check=True,timeout=300)
        fifteen=audit_prusa_multi_object_support(
            output.read_bytes(),crowded,bed_width=250,bed_depth=210)
        assert fifteen["painted_model_index"]==7,fifteen
        assert fifteen["painted_support_moves"]>=2,fifteen
        assert fifteen["unpainted_support_moves"]==0,fifteen
        print("PASS: genuine Prusa native 15-model selective support paint "
              "matches shared model budget",fifteen,flush=True)



if __name__ == "__main__":
    main(*sys.argv[1:])
