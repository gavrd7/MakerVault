"""Real Prusa 2.9.7 seam acceptance: exact painted patch versus baseline."""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
from tempfile import TemporaryDirectory

from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset

audit = runpy.run_path("/tmp/prusa_seam_audit.py")["audit_prusa_seam_enforcer_gcode"]


def main(binary, vendor, directory):
    raw = Path(vendor).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    model = Path(directory)
    item = json.loads((model / "seam-enforced.json").read_text())
    with TemporaryDirectory(prefix="prusa-seam-acceptance-") as temp:
        root = Path(temp)
        options = []
        for kind, preset in (("printer", "Original Prusa i3 MK2S"),
                             ("filament", "Generic PLA"),
                             ("print", "0.20mm NORMAL")):
            ini = root / (kind + ".ini")
            ini.write_bytes(flatten_prusa_vendor_preset(
                raw, kind=kind, name=preset, expected_sha256=digest))
            options.extend(["--load", str(ini)])
        for name in ("baseline", "seam-enforced"):
            output = root / (name + ".gcode")
            subprocess.run([binary, *options, "--export-gcode", "--dont-arrange",
                            "--output", str(output), str(model / (name + ".3mf"))],
                           cwd=root, check=True, timeout=300)
        accepted = audit((root / "seam-enforced.gcode").read_bytes(), item,
                         bed_width=250, bed_depth=210)
        try:
            audit((root / "baseline.gcode").read_bytes(), item,
                  bed_width=250, bed_depth=210)
        except ValueError:
            pass
        else:
            raise AssertionError("Native unpainted seam was mistaken for enforcer")
        print("PASS: exact Prusa painted seam follows annotated face:", accepted)


if __name__ == "__main__":
    main(*sys.argv[1:])
