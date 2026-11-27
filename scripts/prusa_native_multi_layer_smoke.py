"""Genuine Prusa 2.9.7 per-object layer schedule vs untouched neighbour."""
import hashlib
import math
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory

from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset
from slicer_worker.prusa_gcode_audit import WORD, audit_prusa_positive_e


def intervals(data):
    z = None
    e = 0.
    relative = False
    xs = None
    ys = None
    zones = {"left": set(), "right": set()}
    for line in data.decode("utf-8").splitlines():
        if line.startswith(";Z:"):
            try:
                z = float(line.split(":",1)[1].strip())
            except ValueError:
                pass
        cmd = line.split(";",1)[0].strip()
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
        elif op in ("G0","G00","G1","G01"):
            xs=fields.get("X",xs)
            ys=fields.get("Y",ys)
            if "E" in fields:
                change=fields["E"] if relative else fields["E"]-e
                e=e+fields["E"] if relative else fields["E"]
                if (change>1e-6 and z is not None and
                    xs is not None and ys is not None and 100<=ys<=110):
                    if 80<=xs<=100:
                        zones["left"].add(round(z,4))
                    elif 150<=xs<=170:
                        zones["right"].add(round(z,4))
    samples={}
    for key,zs in zones.items():
        ordered=sorted(zs)
        samples[key]=[round(b-a,4) for a,b in zip(ordered,ordered[1:])
                      if a>=5 and b<=15]
    return samples


def main(binary,vendor,baseline,modified):
    source=Path(vendor).read_bytes()
    digest=hashlib.sha256(source).hexdigest()
    with TemporaryDirectory(prefix="prusa-multi-layer-") as temp:
        root=Path(temp)
        flags=[]
        for kind,name in (("printer","Original Prusa i3 MK2S"),
                          ("filament","Generic PLA"),("print","0.20mm NORMAL")):
            f=root/(kind+".ini")
            f.write_bytes(flatten_prusa_vendor_preset(
                source,kind=kind,name=name,expected_sha256=digest))
            flags.extend(["--load",str(f)])
        reports={}
        for label,project in (("baseline",baseline),("modified",modified)):
            output=root/(label+".gcode")
            subprocess.run([binary,*flags,"--export-gcode","--dont-arrange",
                            "--output",str(output),project],
                           cwd=root,check=True,timeout=300)
            raw=output.read_bytes()
            assert audit_prusa_positive_e(raw)["positive_e_moves"]>40
            reports[label]=intervals(raw)
            print("Prusa independent object layer schedule",label,
                  {key:{"count":len(value),"values":sorted(set(value))[:12]}
                   for key,value in reports[label].items()})
        left=reports["modified"]["left"]
        right=reports["modified"]["right"]
        assert len(left)>24 and sum(abs(v-.12)<.016 for v in left)>.7*len(left),left
        assert len(right)>24 and sum(abs(v-.2)<.018 for v in right)>.7*len(right),right
        print("PASS: Prusa 2.9.7 honoured left object .12mm band without altering right object's .20mm layers.")


if __name__=="__main__":
    main(*sys.argv[1:])
