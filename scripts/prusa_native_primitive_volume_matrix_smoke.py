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


def central_native_infill(data):
    """Sample *infill only* inside a Prusa cutter's solid central core.

    Newly created cavity perimeters can increase total extrusion. Counting
    infill paths separately detects removed interior material instead of
    misclassifying the additional cavity walls as a failed subtraction.
    """
    from slicer_worker.prusa_gcode_audit import WORD
    import math
    pos=[None,None,None]
    e=0.
    relative=False
    role=""
    result=0.
    for line in data.decode("utf-8").splitlines():
        if line.startswith(";TYPE:"):
            role=line.partition(":")[2].strip().lower()
        cmd=line.split(";",1)[0].strip()
        if not cmd:
            continue
        op=cmd.split(None,1)[0].upper()
        fields={k.upper():float(v) for k,v in WORD.findall(cmd)}
        if op=="M82":
            relative=False
        elif op=="M83":
            relative=True
        elif op=="G92":
            e=fields.get("E",e)
            pos=[fields.get(k,pos[i]) for i,k in enumerate("XYZ")]
        elif op in ("G0","G00","G1","G01"):
            next_pos=[fields.get(k,pos[i]) for i,k in enumerate("XYZ")]
            if ("E" in fields and "infill" in role
                    and None not in pos+next_pos and 3<=next_pos[2]<=17):
                delta=fields["E"] if relative else fields["E"]-e
                length=math.hypot(next_pos[0]-pos[0],next_pos[1]-pos[1])
                if delta>1e-6 and length>1e-6:
                    samples=max(1,min(2000,math.ceil(length/.25)))
                    for index in range(samples):
                        t=(index+.5)/samples
                        x=pos[0]+t*(next_pos[0]-pos[0])
                        y=pos[1]+t*(next_pos[1]-pos[1])
                        if 123<=x<=127 and 103<=y<=107:
                            result+=delta/samples
            if "E" in fields:
                e=e+fields["E"] if relative else fields["E"]
            pos=next_pos
    return result


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
            measurements[label]={"regional":REGIONAL(data),
                                  "core_infill":central_native_infill(data)}
            print("Prusa native primitive deposition",label,measurements[label])
        baseline=measurements["baseline"]["regional"]
        original_infill=measurements["baseline"]["core_infill"]
        total_baseline=sum(baseline)
        assert total_baseline>100,baseline
        confirmed=[]
        for shape in SHAPES:
            for kind in ("modifier","negative"):
                label=shape+"-"+kind
                actual=measurements[label]["regional"]
                infill=measurements[label]["core_infill"]
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
                    success=(actual[0] < baseline[0]*.85 or
                             (original_infill>.01 and infill < original_infill*.80)) and actual[1]>.1
                print("Prusa primitive",label,
                      "regional deviation",round(deviation,3),
                      "core_infill",round(infill,3),
                      "baseline_infill",round(original_infill,3),
                      "qualified",success)
                if success:
                    confirmed.append(label)
        if len(confirmed)!=len(SHAPES)*2:
            raise AssertionError("Some native primitive shapes lacked measured modifier/cavity effects: "+str(
                sorted(set(shape+"-"+kind for shape in SHAPES for kind in ("modifier","negative"))-set(confirmed))))
        print("PASS: native Prusa 2.9.7 modifier and negative volume effects in all six primitive shapes.")


if __name__=="__main__":
    main(*sys.argv[1:])
