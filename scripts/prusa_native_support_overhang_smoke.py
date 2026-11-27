"""Offline Prusa support enforcer native G-code semantic comparison.

The same-triangulation geometry control distinguishes painted support from
support that happens simply because a mesh was split by the patch exporter.
"""
import hashlib
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory

from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset
from slicer_worker.prusa_gcode_audit import audit_prusa_positive_e, WORD


def _set_keys(source, updates):
    lines = []
    for line in source.decode("utf-8").splitlines():
        if "=" in line and line.split("=",1)[0].strip() in updates:
            continue
        lines.append(line)
    for key,value in updates.items():
        lines.append(key+" = "+value)
    return ("\n".join(lines)+"\n").encode()


def _support_audit(gcode):
    role = ""
    relative = False
    e = 0.
    counts = {}
    for line in gcode.decode("utf-8").splitlines():
        if line.startswith(";TYPE:"):
            role = line.partition(":")[2].strip().lower()
        command = line.split(";",1)[0].strip()
        if not command:
            continue
        op = command.split(None,1)[0].upper()
        fields = {k.upper(): float(v) for k,v in WORD.findall(command)}
        if op == "M82":
            relative = False
        elif op == "M83":
            relative = True
        elif op == "G92":
            e = fields.get("E",e)
        elif op in {"G1","G01"} and "E" in fields:
            delta = fields["E"] if relative else fields["E"]-e
            e = e+fields["E"] if relative else fields["E"]
            if delta > 1e-6 and role:
                counts[role] = counts.get(role,0)+1
    return {k:v for k,v in counts.items() if "support" in k.lower()}


def main(binary, vendor, *projects):
    upstream = Path(vendor).read_bytes()
    checksum = hashlib.sha256(upstream).hexdigest()
    with TemporaryDirectory(prefix="prusa-support-overhang-") as tmp:
        folder = Path(tmp)
        args = []
        original_process = None
        for kind,name in (("printer","Original Prusa i3 MK2S"),
                          ("filament","Generic PLA"),("print","0.20mm NORMAL")):
            data = flatten_prusa_vendor_preset(upstream,kind=kind,name=name,
                                               expected_sha256=checksum)
            if kind=="print":
                original_process = data
                # Explicitly enable *manual-only* support enforcers for a
                # CLI qualification fixture, never change saved user presets.
                data = _set_keys(data,{"support_material":"1","support_material_auto":"0"})
            file=folder/(kind+".ini")
            file.write_bytes(data)
            args.extend(["--load",str(file)])
        results={}
        for label,path in (entry.split("=",1) for entry in projects):
            output=folder/(label+".gcode")
            subprocess.run([binary,*args,"--export-gcode","--dont-arrange",
                            "--output",str(output),path],
                           cwd=folder,check=True,timeout=300)
            data=output.read_bytes()
            audit_prusa_positive_e(data)
            metrics=_support_audit(data)
            motion=b"\n".join(line.split(b";",1)[0].strip() for line in data.splitlines()
                              if line.lstrip().startswith((b"G0 ",b"G1 ")))
            results[label]={"support":metrics,
                            "motion":hashlib.sha256(motion).hexdigest()[:16]}
            print("Native Prusa support painting",label,results[label])
        # This diagnostic does not approve a support feature solely because
        # a painted archive loads. A release gate needs spatial support E.
        print("Candidate support comparison (enforced vs geometry control):",
              results["enforced"]!=results["geometry-control"])
        if "blocked" in results:
            (folder/"print.ini").write_bytes(_set_keys(original_process, {
                "support_material":"1", "support_material_auto":"1"}))
            auto_results = {}
            for label,path in (entry.split("=",1) for entry in projects if
                               entry.startswith(("geometry-control=", "blocked="))):
                output = folder / ("auto-" + label + ".gcode")
                subprocess.run([binary,*args,"--export-gcode","--dont-arrange",
                                "--output",str(output),path],cwd=folder,
                               check=True,timeout=300)
                raw = output.read_bytes()
                audit_prusa_positive_e(raw)
                auto_results[label] = _support_audit(raw)
                print("Native Prusa automatic support/blocker",label,auto_results[label])
            print("Candidate blocker comparison with automatic supports:",
                  auto_results.get("geometry-control") != auto_results.get("blocked"))


if __name__=="__main__":
    main(*sys.argv[1:])
