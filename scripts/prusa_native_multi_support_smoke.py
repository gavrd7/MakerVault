"""Native Prusa 2.9.7 two-model support-paint regional toolpath audit."""
import hashlib
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset
from slicer_worker.prusa_gcode_audit import WORD, audit_prusa_positive_e


def count_native_support(data):
    role=""
    tool_e=0.
    relative=False
    x=y=None
    regions={"left":0,"right":0,"outside":0}
    for line in data.decode("utf-8").splitlines():
        if line.startswith(";TYPE:"):
            role=line.partition(":")[2].strip().lower()
        instruction=line.split(";",1)[0].strip()
        if not instruction:
            continue
        opcode=instruction.split(None,1)[0].upper()
        fields={k.upper():float(v) for k,v in WORD.findall(instruction)}
        if opcode=="M82":
            relative=False
        elif opcode=="M83":
            relative=True
        elif opcode=="G92":
            tool_e=fields.get("E",tool_e)
        elif opcode in ("G0","G00","G1","G01"):
            x=fields.get("X",x)
            y=fields.get("Y",y)
            if "E" in fields:
                delta=fields["E"] if relative else fields["E"]-tool_e
                tool_e=tool_e+fields["E"] if relative else fields["E"]
                if (delta>1e-6 and "support material" in role
                        and x is not None and y is not None):
                    region=("left" if 56<=x<=94 and 93<=y<=117 else
                            "right" if 156<=x<=194 and 93<=y<=117 else "outside")
                    regions[region]+=1
    return regions


def main(binary,vendor,directory):
    raw=Path(vendor).read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    root=Path(directory)
    with TemporaryDirectory(prefix="prusa-multi-support-") as tmp:
        scratch=Path(tmp)
        flags=[]
        for kind,name in (("printer","Original Prusa i3 MK2S"),
                          ("filament","Generic PLA"),
                          ("print","0.20mm NORMAL")):
            content=flatten_prusa_vendor_preset(
                raw,kind=kind,name=name,expected_sha256=digest)
            if kind=="print":
                # Local CLI fixture: manual painted support enforcers on,
                # auto supports off. Never modify owner-created profiles.
                content = b"\n".join(line for line in content.splitlines()
                    if line.split(b"=",1)[0].strip() not in
                    (b"support_material",b"support_material_auto")) + b"\n"
                content += b"support_material = 1\nsupport_material_auto = 0\n"
            path=scratch/(kind+".ini")
            path.write_bytes(content)
            flags.extend(["--load",str(path)])
        counts={}
        for name in ("baseline","left","right"):
            out=scratch/(name+".gcode")
            subprocess.run([binary,*flags,"--export-gcode","--dont-arrange",
                            "--output",str(out),str(root/(name+".3mf"))],
                           cwd=scratch,check=True,timeout=300)
            data=out.read_bytes()
            assert audit_prusa_positive_e(data)["positive_e_moves"]>100
            counts[name]=count_native_support(data)
            print("Native Prusa dual-object support region",name,counts[name])
        assert counts["baseline"]["left"]<5 and counts["baseline"]["right"]<5,counts
        assert counts["left"]["left"]>50 and counts["left"]["right"]<5,counts
        assert counts["right"]["right"]>50 and counts["right"]["left"]<5,counts
        print("PASS: genuine Prusa 2.9.7 support enforcers independently affect only their selected model.")


if __name__=="__main__":
    main(*sys.argv[1:])
