"""Determine real PrusaSlicer 2.9.7 MMU object-tool metadata semantics.

Offline G-code test under the immutable upstream vendor profile and binary.
All variants are *candidate research inputs*: do not enable the worker or UI.
"""
import hashlib
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory

from slicer_worker.prusa_vendor_profiles import (
    flatten_prusa_vendor_preset, validate_flat_prusa_preset,
)
from slicer_worker.prusa_gcode_audit import audit_prusa_positive_e


def main(binary, source, directory):
    raw = Path(source).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    printer_name = "Original Prusa i3 MK3S & MK3S+ MMU3"
    vendor_profiles = (
        ("printer", printer_name),
        ("filament", "Generic PLA"),
        ("print", "0.20mm NORMAL"),
    )
    with TemporaryDirectory(prefix="prusa-mmu-dialect-") as tmp:
        root = Path(tmp)
        native = []
        for kind,name in vendor_profiles:
            data = flatten_prusa_vendor_preset(raw, kind=kind,
                                               name=name, expected_sha256=digest)
            parsed = validate_flat_prusa_preset(data, kind=kind)
            if kind == "printer":
                assert parsed.get("single_extruder_multi_material") == "1"
                assert len(parsed["nozzle_diameter"].split(",")) == 5
                print("PINNED", printer_name, "5 virtual nozzles and MMU changer")
            file = root / (kind + ".ini")
            file.write_bytes(data)
            native.extend(["--load", str(file)])
        winners = []
        for dialect in ("object", "volume", "both"):
            model = str(Path(directory) / (dialect + ".3mf"))
            dest = root / (dialect + ".gcode")
            command = [binary, *native, "--export-gcode", "--dont-arrange",
                       "--output", str(dest), model]
            result = subprocess.run(command, cwd=root, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, timeout=300)
            if result.returncode != 0 or not dest.exists():
                print("CANDIDATE", dialect, "native CLI did not slice",
                      "code", result.returncode)
                continue
            data = dest.read_bytes()
            audited = audit_prusa_positive_e(data)
            tools = {int(v): len(re.findall(rb"(?m)^T"+v+rb"(?:[ ;\r\n]|$)", data))
                     for v in (b"0",b"1",b"2",b"3",b"4")}
            meaningful = tools[0] > 0 and tools[1] > 0
            print("CANDIDATE", dialect, "extrusion", audited["positive_e_moves"],
                  "selected_tools", tools, "two_tool_selection", meaningful,
                  "gcode_bytes", len(data))
            if meaningful:
                winners.append(dialect)
        if not winners:
            raise RuntimeError("No native Prusa MMU3 project variant proved dual tool selection.")
        print("PASS: native upstream Prusa 2.9.7 MMU3 selected more than one logical tool in", winners)
        print("NOTE: dual tool selection is NOT sufficient to approve purge, hardware, colours or worker admission.")


if __name__ == "__main__":
    main(*sys.argv[1:])
