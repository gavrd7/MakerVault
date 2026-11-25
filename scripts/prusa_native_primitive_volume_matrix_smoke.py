"""Genuine native Prusa 2.9.7 six-primitive modifier/negative deposition matrix."""
import hashlib
from pathlib import Path
import runpy
import subprocess
import sys
from tempfile import TemporaryDirectory

from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset
from slicer_worker.prusa_gcode_audit import audit_prusa_positive_e

REGIONAL=runpy.run_path("/tmp/prusa_region_math.py")["regional_extrusion"]
SHAPES=("box","cone","cylinder","disc","sphere","torus")


def main(binary,vendor,folder):
    raw=Path(vendor).read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    projects=Path(folder)
    with TemporaryDirectory(prefix="prusa-primitive-matrix-") as temp:
        root=Path(temp)
        args=[]
        for kind,name in (("printer","Original Prusa i3 MK2S"),
                          ("filament","Generic PLA"),
                          ("print","0.20mm NORMAL")):
            ini=root/(kind+".ini")
            ini.write_bytes(flatten_prusa_vendor_preset(
                raw,kind=kind,name=name,expected_sha256=digest))
            args.extend(["--load",str(ini)])
        measurements={}
        for label in ("baseline",*(shape+"-"+kind for shape in SHAPES
                                    for kind in ("modifier","negative"))):
            out=root/(label+".gcode")
            subprocess.run([binary,*args,"--export-gcode","--dont-arrange",
                            "--output",str(out),str(projects/(label+".3mf"))],
                           check=True,timeout=300,cwd=root,
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            data=out.read_bytes()
            assert audit_prusa_positive_e(data)["positive_e_moves"]>100
            measurements[label]=REGIONAL(data)
            print("Prusa native primitive deposition",label,measurements[label])
        baseline=measurements["baseline"]
        total_baseline=sum(baseline)
        assert total_baseline>100,baseline
        confirmed=[]
        for shape in SHAPES:
            for kind in ("modifier","negative"):
                label=shape+"-"+kind
                actual=measurements[label]
                total=sum(actual)
                deviation=total-total_baseline
                if kind=="modifier":
                    # Parameter modifiers must demonstrably increase local
                    # deposition, not merely change a metadata/footer hash.
                    success=deviation>1.0 and actual[1]>.1
                else:
                    # Subtraction creates new inner cavity walls, so its total
                    # E can INCREASE. Require less deposition at the original
                    # occupied centre while retaining surrounding material.
                    success=actual[0] < baseline[0]*.85 and actual[1]>.1
                print("Prusa primitive",label,
                      "regional deviation",round(deviation,3),
                      "qualified",success)
                if success:
                    confirmed.append(label)
        if len(confirmed)!=len(SHAPES)*2:
            raise AssertionError("Some native primitive shapes lacked measured modifier/cavity effects: "+str(
                sorted(set(shape+"-"+kind for shape in SHAPES for kind in ("modifier","negative"))-set(confirmed))))
        print("PASS: native Prusa 2.9.7 modifier and negative volume effects in all six primitive shapes.")


if __name__=="__main__":
    main(*sys.argv[1:])
