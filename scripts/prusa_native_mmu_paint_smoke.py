"""Semantic Prusa 2.9.7 MMU3 native colour painting G-code acceptance.

The pinned real 5-slot MMU printer must use T1 on the painted wall while
retaining T0 on the opposite unpainted wall. Tool changes alone do not qualify.
"""
import hashlib
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory

from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset
from slicer_worker.prusa_gcode_audit import WORD,audit_prusa_positive_e


def counts(data):
    role=""
    tool=None
    e=0.
    relative=False
    x=y=None
    walls={0:{"front":0,"back":0},1:{"front":0,"back":0}}
    for line in data.decode("utf-8").splitlines():
        if line.startswith(";TYPE:"):
            role=line.partition(":")[2].strip().lower()
        cmd=line.split(";",1)[0].strip()
        if not cmd:
            continue
        op=cmd.split(None,1)[0].upper()
        if op in ("T0","T1"):
            tool=int(op[1:])
        words={key.upper():float(value) for key,value in WORD.findall(cmd)}
        if op=="M82":
            relative=False
        elif op=="M83":
            relative=True
        elif op=="G92":
            e=words.get("E",e)
        elif op in ("G0","G00","G1","G01"):
            x=words.get("X",x)
            y=words.get("Y",y)
            if "E" in words:
                delta=words["E"] if relative else words["E"]-e
                e=e+words["E"] if relative else words["E"]
                if (delta>1e-6 and tool in walls and "external perimeter" in role
                        and x is not None and y is not None and 114<=x<=136):
                    if 93<=y<=97:
                        walls[tool]["front"]+=1
                    elif 113<=y<=117:
                        walls[tool]["back"]+=1
    return walls


def main(binary,vendor,baseline,painted):
    source=Path(vendor).read_bytes()
    sha=hashlib.sha256(source).hexdigest()
    with TemporaryDirectory(prefix="prusa-mmu-facet-") as temp:
        root=Path(temp)
        args=[]
        for kind,name in (("printer","Original Prusa i3 MK3S & MK3S+ MMU3"),
                          ("filament","Generic PLA"),("print","0.20mm NORMAL")):
            file=root/(kind+".ini")
            file.write_bytes(flatten_prusa_vendor_preset(
                source,kind=kind,name=name,expected_sha256=sha))
            args.extend(["--load",str(file)])
        results={}
        for label,project in (("baseline",baseline),("painted",painted)):
            output=root/(label+".gcode")
            subprocess.run([binary,*args,"--export-gcode","--dont-arrange",
                            "--output",str(output),project],
                           cwd=root,check=True,timeout=300)
            raw=output.read_bytes()
            assert audit_prusa_positive_e(raw)["positive_e_moves"]>100
            mapping=counts(raw)
            switches={n:len(re.findall(rb"(?m)^T"+str(n).encode()+rb"(?:[ ;\r\n]|$)",raw))
                      for n in (0,1)}
            results[label]=mapping
            print("Prusa MMU source-painted toolpath",label,
                  "toolhead selections",switches,"external walls",mapping)
        mapped=results["painted"]
        assert mapped[1]["front"]>20 and mapped[0]["back"]>20, mapped
        assert mapped[1]["back"]<5, mapped
        assert results["baseline"][1]["front"]<5, results["baseline"]
        print("PASS: Prusa 2.9.7 native MMU painted wall extruded with T1 while unpainted opposite wall retained T0.")
        print("NOTE: printer hardware, purge distances, flushing volumes and independent XL topology still unverified.")


if __name__=="__main__":
    main(*sys.argv[1:])
