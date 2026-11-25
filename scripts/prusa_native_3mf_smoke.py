"""Native Prusa project acceptance; test only, never an HTTP worker route."""
import hashlib
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
import sys

from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset
from slicer_worker.prusa_gcode_audit import audit_prusa_positive_e


def main(binary, vendor, project):
    raw = Path(vendor).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    with TemporaryDirectory(prefix="prusa-native-project-") as tmp:
        folder = Path(tmp)
        profiles = []
        for kind, name in (("printer", "Original Prusa i3 MK2S"),
                           ("filament", "Generic PLA"), ("print", "0.20mm NORMAL")):
            path = folder / (kind + ".ini")
            path.write_bytes(flatten_prusa_vendor_preset(raw, kind=kind, name=name, expected_sha256=digest))
            profiles.extend(["--load", str(path)])
        output = folder / "output.gcode"
        subprocess.run([binary, *profiles, "--export-gcode", "--output", str(output),
                        "--dont-arrange", project], cwd=folder, check=True, timeout=300)
        data = output.read_bytes()
        assert audit_prusa_positive_e(data)["positive_e_moves"] >= 40
        # At each deposited path, attribute actual extrusion to the two
        # disjoint model X bands. Exclude skirt and non-infill features.
        positions = [0, 0]
        infill = [0, 0]
        feature = ""
        x = None
        e = 0.
        relative = False
        for line in data.decode("utf-8").splitlines():
            if line.startswith(";TYPE:"):
                feature = line[6:].strip().lower()
            cmd = line.split(";", 1)[0].strip().split()
            if not cmd:
                continue
            if cmd[0] == "M82":
                relative = False
            elif cmd[0] == "M83":
                relative = True
            elif cmd[0] == "G92":
                for token in cmd[1:]:
                    if token.startswith("E"):
                        e = float(token[1:])
            elif cmd[0] in ("G1", "G0"):
                fields = {token[0]: float(token[1:]) for token in cmd[1:] if re.fullmatch(r"[XYZE]-?\d+(?:\.\d+)?", token)}
                new_x = fields.get("X", x)
                if "E" in fields:
                    delta = fields["E"] if relative else fields["E"] - e
                    e = e + delta if relative else fields["E"]
                    if delta > 0 and x is not None and new_x is not None and ("X" in fields or "Y" in fields):
                        for i, (lo, hi) in enumerate(((79, 101), (149, 171))):
                            if lo <= x <= hi and lo <= new_x <= hi:
                                positions[i] += 1
                                if feature == "internal infill":
                                    infill[i] += delta
                x = new_x
        assert min(positions) > 20, positions
        assert infill[0] > 0 and infill[1] > infill[0] * 1.5, infill
        print("PASS: native 3MF preserved both model positions and distinct object infill:", positions, infill)


if __name__ == "__main__":
    main(*sys.argv[1:])
