"""Real PrusaSlicer 2.9.7 multiple-model painted seam G-code proof."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory

from core.slicer_prusa_seam_audit import audit_prusa_multi_object_seam_gcode
from core.slicer_prusa_process_settings import qualify_prusa_seam_process
from scripts.prusa_real_binary_smoke import cube_stl
from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset
from slicer_worker.runner import run_prusa


def main(binary,vendor,directory):
    root=Path(directory)
    raw=Path(vendor).read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    profiles={}
    for kind,upstream,name in (
            ("printer","printer","Original Prusa i3 MK2S"),
            ("filament","filament","Generic PLA"),
            ("process","print","0.20mm NORMAL")):
        data=flatten_prusa_vendor_preset(
            raw,kind=upstream,name=name,expected_sha256=digest)
        profiles[kind+".ini"]=(
            qualify_prusa_seam_process(data,"random")
            if kind=="process" else data)
    mesh=cube_stl()
    with TemporaryDirectory(prefix="prusa-multi-seam-") as temp:
        work=Path(temp)
        data={}
        rows={}
        for label in ("baseline","one","two"):
            place=work/label
            place.mkdir()
            shutil.copyfile(root/(label+".3mf"),place/"input.3mf")
            for name,content in profiles.items():
                (place/name).write_bytes(content)
            run_prusa(Path(binary),place)
            data[label]=(place/"output.gcode").read_bytes()
            rows[label]=[(item,mesh) for item in
                         json.loads((root/(label+".json")).read_text())]
        # The same 15-model physical geometry without seam metadata
        # must NOT accidentally satisfy the painted face audit.
        try:
            audit_prusa_multi_object_seam_gcode(
                data["baseline"],rows["one"],
                bed_width=250,bed_depth=210)
        except ValueError:
            pass
        else:
            raise AssertionError("Unpainted fifteen-object seam baseline passed")
        once=audit_prusa_multi_object_seam_gcode(
            data["one"],rows["one"],bed_width=250,bed_depth=210)
        twice=audit_prusa_multi_object_seam_gcode(
            data["two"],rows["two"],bed_width=250,bed_depth=210)
        assert once["painted_model_indices"]==[7],once
        assert twice["painted_model_indices"]==[7,8],twice
        assert once["sampled_layers"][7]>=5,once
        assert all(twice["sampled_layers"][i]>=5 for i in (7,8)),twice
        print("PASS: genuine native Prusa fifteen-model per-object seams "
              "with separately painted front and back models",
              {"one":once,"two":twice},flush=True)


if __name__=="__main__":
    main(*sys.argv[1:])
