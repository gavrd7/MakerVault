"""Required genuine Prusa 2.9.7 offline front seam worker acceptance.

Unlike the exploratory four-face scan, this tests the specific bounded
front enforcer admitted by the normal queue and rejects its unpainted baseline.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory

from core.slicer_prusa_seam_audit import (
    validate_prusa_front_seam_candidate, audit_prusa_seam_enforcer_gcode,
)
from core.slicer_prusa_3mf import validate_prusa_project_admission
from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset
from slicer_worker.runner import run_prusa


def main(binary,vendor,directory):
    directory=Path(directory)
    source=Path(vendor).read_bytes()
    checksum=hashlib.sha256(source).hexdigest()
    with TemporaryDirectory(prefix="prusa-front-seam-") as temp:
        base=Path(temp)
        profiles={}
        for kind,native,name in (
            ("printer","printer","Original Prusa i3 MK2S"),
            ("filament","filament","Generic PLA"),
            ("process","print","0.20mm NORMAL"),
        ):
            profiles[kind+".ini"]=flatten_prusa_vendor_preset(
                source,kind=native,name=name,expected_sha256=checksum)
        painted=json.loads((directory/"seam-front.json").read_text())
        assert validate_prusa_front_seam_candidate(painted)["version"]==2
        assert validate_prusa_project_admission([painted],{},"2.9.7") is False
        outputs={}
        for title in ("baseline","seam-front"):
            work=base/title
            work.mkdir()
            shutil.copyfile(directory/(title+".3mf"),work/"input.3mf")
            for name,raw in profiles.items():
                (work/name).write_bytes(raw)
            run_prusa(Path(binary),work)
            outputs[title]=(work/"output.gcode").read_bytes()
        try:
            audit_prusa_seam_enforcer_gcode(
                outputs["baseline"],painted,bed_width=250,bed_depth=210)
        except ValueError:
            pass
        else:
            raise AssertionError("Baseline also satisfies painted native seam direction.")
        receipt=audit_prusa_seam_enforcer_gcode(
            outputs["seam-front"],painted,bed_width=250,bed_depth=210)
        assert receipt["sampled_layers"]>=5
        assert receipt["matching_layers"]>=int(.75*receipt["sampled_layers"])
        print("PASS: native worker obeys only the verified front seam enforcer;",
              receipt,"sha256",hashlib.sha256(outputs["seam-front"]).hexdigest(),
              flush=True)


if __name__=="__main__":
    main(*sys.argv[1:])
