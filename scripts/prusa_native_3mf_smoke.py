"""Native Prusa project acceptance; test only, never an HTTP worker route."""
import hashlib
from collections import Counter
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
import sys

from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset
from slicer_worker.prusa_gcode_audit import audit_prusa_positive_e, WORD


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
        quality = audit_prusa_positive_e(data)
        assert quality["positive_e_moves"] >= 40
        print("Native 3MF total audited extrusion moves:", quality)
        # At each deposited path, attribute actual extrusion to the two
        # disjoint model X bands. Exclude skirt and non-infill features.
        positions = [0, 0]
        infill = [0, 0]
        feature = ""
        histogram = Counter()
        features = Counter()
        y = None
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
                for key, value in WORD.findall(" ".join(cmd)):
                    if key.upper() == "E":
                        e = float(value)
            elif cmd[0] in ("G1", "G0", "G01", "G00"):
                fields = {key.upper(): float(value) for key, value in WORD.findall(" ".join(cmd))}
                new_x = fields.get("X", x)
                new_y = fields.get("Y", y)
                if "E" in fields:
                    delta = fields["E"] if relative else fields["E"] - e
                    e = e + delta if relative else fields["E"]
                    if delta > 0 and x is not None and new_x is not None and ("X" in fields or "Y" in fields):
                        if feature not in ("", "skirt/brim", "skirt", "brim"):
                            histogram[int(new_x // 10) * 10] += 1
                            features[feature] += 1
                        for i, (lo, hi) in enumerate(((79, 101), (149, 171))):
                            if lo <= x <= hi and lo <= new_x <= hi:
                                positions[i] += 1
                                if feature == "internal infill":
                                    infill[i] += delta
                x, y = new_x, new_y
        print("Native 3MF diagnostic: X bands", sorted(histogram.items()), "features", dict(features), "expected-band counts", positions, "infill", infill)
        assert min(positions) > 20, positions
        assert infill[0] > 0 and infill[1] > infill[0] * 1.5, infill
        print("PASS: native 3MF preserved both model positions and distinct object infill:", positions, infill)


if __name__ == "__main__":
    main(*sys.argv[1:])
