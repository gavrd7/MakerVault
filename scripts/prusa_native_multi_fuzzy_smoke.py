"""Real native Prusa 2.9.7 per-model fuzzy-wall extrusion isolation."""
import hashlib
import math
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from slicer_worker.prusa_gcode_audit import WORD,audit_prusa_positive_e
from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset


def audited_short_external_walls(data):
    role=""
    xyz=[None,None,None]
    e=0.
    relative=False
    count={"left":0,"right":0}
    for line in data.decode("utf-8").splitlines():
        if line.startswith(";TYPE:"):
            role=line.partition(":")[2].strip().lower()
        cmd=line.split(";",1)[0].strip()
        if not cmd:
            continue
        op=cmd.split(None,1)[0].upper()
        words={k.upper():float(v) for k,v in WORD.findall(cmd)}
        if op=="M82":
            relative=False
        elif op=="M83":
            relative=True
        elif op=="G92":
            e=words.get("E",e)
        elif op in ("G0","G00","G1","G01"):
            new=[words.get(k,xyz[i]) for i,k in enumerate("XYZ")]
            if ("E" in words and "external perimeter" in role
                    and None not in new and None not in xyz):
                delta=words["E"] if relative else words["E"]-e
                length=math.hypot(new[0]-xyz[0],new[1]-xyz[1])
                midpoint=((new[0]+xyz[0])/2,(new[1]+xyz[1])/2)
                if (delta>1e-6 and .01<length<1.25
                        and 2<=new[2]<=18 and 94<=midpoint[1]<=97):
                    if 80<=midpoint[0]<=100:
                        count["left"]+=1
                    elif 150<=midpoint[0]<=170:
                        count["right"]+=1
            xyz=new
            if "E" in words:
                e=e+words["E"] if relative else words["E"]
    return count


def main(binary,vendor,directory):
    raw=Path(vendor).read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    root=Path(directory)
    with TemporaryDirectory(prefix="prusa-multi-fuzzy-") as temp:
        scratch=Path(temp)
        flags=[]
        for kind,name in (("printer","Original Prusa i3 MK2S"),
                          ("filament","Generic PLA"),("print","0.20mm NORMAL")):
            ini=scratch/(kind+".ini")
            ini.write_bytes(flatten_prusa_vendor_preset(raw,kind=kind,name=name,
                                                   expected_sha256=digest))
            flags.extend(["--load",str(ini)])
        counts={}
        for label in ("baseline","left","right"):
            dest=scratch/(label+".gcode")
            subprocess.run([binary,*flags,"--export-gcode","--dont-arrange",
                            "--output",str(dest),str(root/(label+".3mf"))],
                           cwd=scratch,check=True,timeout=300)
            gcode=dest.read_bytes()
            assert audit_prusa_positive_e(gcode)["positive_e_moves"]>100
            counts[label]=audited_short_external_walls(gcode)
            print("Native two-object Prusa fuzzy wall",label,counts[label])
        assert counts["baseline"]["left"]<5 and counts["baseline"]["right"]<5,counts
        assert counts["left"]["left"]>100 and counts["left"]["right"]<5,counts
        assert counts["right"]["right"]>100 and counts["right"]["left"]<5,counts
        print("PASS: Prusa 2.9.7 selectively fuzzed only the painted model, leaving the other smooth.")


if __name__=="__main__":
    main(*sys.argv[1:])
