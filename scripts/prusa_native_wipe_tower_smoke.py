"""Actual native Prusa 2.9.7 wipe-tower relocation and purge XY audit."""
import hashlib
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset
from slicer_worker.prusa_gcode_audit import WORD, audit_prusa_positive_e


def tower_extrusion_xy(data):
    tool=None
    relative=False
    e=0.
    x=y=None
    sampled=[]
    tools={}
    for line in data.decode("utf-8").splitlines():
        command=line.split(";",1)[0].strip()
        if not command:
            continue
        opcode=command.split(None,1)[0].upper()
        if opcode in ("T0","T1"):
            tool=int(opcode[1:])
            continue
        fields={k.upper():float(v) for k,v in WORD.findall(command)}
        if opcode=="M82":
            relative=False
        elif opcode=="M83":
            relative=True
        elif opcode=="G92":
            e=fields.get("E",e)
        elif opcode in ("G0","G00","G1","G01"):
            x=fields.get("X",x)
            y=fields.get("Y",y)
            if "E" in fields:
                delta=fields["E"] if relative else fields["E"]-e
                e=e+fields["E"] if relative else fields["E"]
                if (delta>1e-6 and x is not None and y is not None
                        and 125<=y<=200 and 0<=x<=250
                        and tool in (0,1)):
                    sampled.append((x,y))
                    tools[tool]=tools.get(tool,0)+1
    if len(sampled)<30 or len(tools)<2:
        raise AssertionError("Native Prusa wipe tower lacked identifiable multi-tool purge extrusion.")
    xs=[p[0] for p in sampled]
    ys=[p[1] for p in sampled]
    # Using a robust midrange rather than the mean avoids a tiny amount of
    # incidental travel/purge skewing an otherwise located tower.
    xs.sort()
    ys.sort()
    return {"count":len(sampled),"tools":tools,
            "median_x":round(xs[len(xs)//2],2),
            "median_y":round(ys[len(ys)//2],2)}


def main(binary,vendor,folder):
    upstream=Path(vendor).read_bytes()
    digest=hashlib.sha256(upstream).hexdigest()
    root=Path(folder)
    with TemporaryDirectory(prefix="prusa-wipe-tower-") as tmp:
        work=Path(tmp)
        profiles=[]
        for kind,name in (
            ("printer","Original Prusa i3 MK3S & MK3S+ MMU3"),
            ("filament","Generic PLA"),("print","0.20mm NORMAL")
        ):
            file=work/(kind+".ini")
            file.write_bytes(flatten_prusa_vendor_preset(
                upstream,kind=kind,name=name,expected_sha256=digest))
            profiles.extend(["--load",str(file)])
        results={}
        for name in ("west","east"):
            output=work/(name+".gcode")
            subprocess.run([binary,*profiles,"--export-gcode","--dont-arrange",
                            "--output",str(output),str(root/(name+".3mf"))],
                           check=True,cwd=work,timeout=300)
            data=output.read_bytes()
            assert audit_prusa_positive_e(data)["positive_e_moves"]>=100
            results[name]=tower_extrusion_xy(data)
            print("Native Prusa 2.9.7 relocated purge tower",name,results[name])
        shift=results["east"]["median_x"]-results["west"]["median_x"]
        assert shift>70,("Prusa ignored native 3MF wipe tower X",results)
        assert abs(results["east"]["median_y"]-results["west"]["median_y"])<15,results
        print("PASS: true native MMU wipe tower extrusion moved across bed by",shift,"mm")


if __name__=="__main__":
    main(*sys.argv[1:])
