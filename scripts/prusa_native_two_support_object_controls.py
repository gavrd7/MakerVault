"""Research PrusaSlicer 2.9.7 native per-object support-off controls.

Known two-object support case leaks support into unpainted right neighbour.
Test whether an upstream native per-object support disable can isolate it.
Research-only: no production 3MF acceptance or printer submission changes.
"""
import hashlib
import io
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import zipfile
from xml.etree import ElementTree as ET

from defusedxml import ElementTree as SafeET
from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset
from scripts.prusa_native_multi_support_smoke import count_native_support

CONFIG="Metadata/Slic3r_PE_model.config"


def disable_unpainted_object(project, keys):
    with zipfile.ZipFile(io.BytesIO(project)) as original:
        parts={name:original.read(name) for name in original.namelist()}
    root=SafeET.fromstring(parts[CONFIG])
    rows=root.findall("./object")
    if len(rows)!=2:
        raise AssertionError("Expected exactly two Prusa project objects.")
    other=rows[1]
    for key,value in keys.items():
        ET.SubElement(other,"metadata",{
            "type":"object","key":key,"value":str(value),
        })
    parts[CONFIG]=ET.tostring(root,encoding="utf-8",xml_declaration=True)
    output=io.BytesIO()
    with zipfile.ZipFile(output,"w",compression=zipfile.ZIP_DEFLATED) as target:
        for name,body in parts.items():
            target.writestr(name,body)
    return output.getvalue()


def main(binary,vendor,directory):
    source=Path(vendor).read_bytes()
    digest=hashlib.sha256(source).hexdigest()
    project=(Path(directory)/"left.3mf").read_bytes()
    with TemporaryDirectory(prefix="prusa-support-object-controls-") as temp:
        work=Path(temp)
        args=[]
        for kind,name in (("printer","Original Prusa i3 MK2S"),
                          ("filament","Generic PLA"),
                          ("print","0.20mm NORMAL")):
            preset=flatten_prusa_vendor_preset(
                source,kind=kind,name=name,expected_sha256=digest)
            if kind=="print":
                preset=b"\n".join(line for line in preset.splitlines()
                    if line.split(b"=",1)[0].strip() not in (
                        b"support_material",b"support_material_auto"))+b"\n"
                preset+=b"support_material = 1\nsupport_material_auto = 0\n"
            file=work/(kind+".ini")
            file.write_bytes(preset)
            args.extend(["--load",str(file)])
        variants={
            "baseline":project,
            "right-off":disable_unpainted_object(project,{
                "support_material":0,
            }),
            "right-off-auto":disable_unpainted_object(project,{
                "support_material":0,"support_material_auto":0,
            }),
        }
        for name,archive in variants.items():
            infile=work/(name+".3mf")
            outfile=work/(name+".gcode")
            infile.write_bytes(archive)
            subprocess.run([binary,*args,"--export-gcode","--dont-arrange",
                            "--output",str(outfile),str(infile)],
                           cwd=work,check=True,timeout=300)
            counters=count_native_support(outfile.read_bytes())
            print("Research Prusa per-object native support override",
                  name,counters,flush=True)
            if name=="baseline" and not counters["right"]>5:
                raise AssertionError("Baseline no longer reproduces support leakage.")
            if name!="baseline" and counters["left"]>50 and counters["right"]<5:
                print("PASS: Prusa per-object support-off isolates right neighbour",
                      name,flush=True)
                return
        raise AssertionError("Prusa object-local support-off did not isolate neighbour.")


if __name__=="__main__":
    main(*sys.argv[1:])
