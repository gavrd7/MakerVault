"""Pinned native acceptance for two independent Prusa printable model volumes."""
import hashlib
from pathlib import Path
import runpy
import subprocess
import sys
from tempfile import TemporaryDirectory
from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset

def main(binary, vendor, baseline, modifier, negative):
    sample = runpy.run_path("/tmp/prusa_regions.py")["regional_extrusion"]
    raw = Path(vendor).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    with TemporaryDirectory(prefix="prusa-two-object-regions-") as tmp:
        work = Path(tmp)
        profiles = []
        for kind, name in (("printer", "Original Prusa i3 MK2S"),
                           ("filament", "Generic PLA"), ("print", "0.20mm NORMAL")):
            path = work / (kind + ".ini")
            path.write_bytes(flatten_prusa_vendor_preset(raw, kind=kind,
                            name=name, expected_sha256=digest))
            profiles.extend(["--load", str(path)])
        receipts = {}
        for label, project in (("baseline", baseline), ("modifier", modifier), ("negative", negative)):
            output = work / (label + ".gcode")
            subprocess.run([binary, *profiles, "--export-gcode", "--dont-arrange",
                            "--output", str(output), project], cwd=work,
                            check=True, timeout=300)
            data = output.read_bytes()
            receipts[label] = tuple(sample(data, center_x=x, center_y=105)
                                    for x in (90, 160))
            print("Prusa two-object regional extrusion", label, receipts[label])
        for i in range(2):
            original = receipts["baseline"][i]
            changed = receipts["modifier"][i]
            negative = receipts["negative"][i]
            assert original[0] > .1 and original[1] > .1, ("no baseline", i, original)
            assert changed[0] > original[0]*1.5 and changed[1] > .1, (
                "modifier not applied to independent object", i, original, changed)
            assert negative[0] < .01 and negative[1] > .1, (
                "negative did not cut independent object", i, negative)
        print("PASS: both native Prusa 3MF printable objects independently honour their modifiers and negative volumes.")

if __name__ == "__main__":
    main(*sys.argv[1:])
