"""Real Prusa modifier and negative-volume qualification; synthetic fixtures only."""
import hashlib
import math
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset
from slicer_worker.prusa_gcode_audit import audit_prusa_positive_e, WORD


def regional_extrusion(data):
    """Measure positive-E paths inside a fixed, deep 6x6mm central test region.

    Ignore purge/start/end movements and the top/bottom skin. Sample entire
    line segments so a crossing infill line cannot escape by its endpoints.
    """
    audit_prusa_positive_e(data)
    pos = [None, None, None]
    relative_e = False
    e = 0.
    inside = outside = 0.
    layer = False
    for line in data.decode("utf-8").splitlines():
        if line.strip() == ";LAYER_CHANGE":
            layer = True
        if line.startswith("; filament used"):
            layer = False
        cmd = line.split(";", 1)[0].strip()
        if not cmd:
            continue
        op = cmd.split(None, 1)[0].upper()
        fields = {k.upper(): float(v) for k, v in WORD.findall(cmd)}
        if op == "M82":
            relative_e = False
        elif op == "M83":
            relative_e = True
        elif op == "G92":
            e = fields.get("E", e)
            pos = [fields.get(a, pos[i]) for i, a in enumerate("XYZ")]
        elif op in {"G0", "G00", "G1", "G01"}:
            new = [fields.get(a, pos[i]) for i, a in enumerate("XYZ")]
            if "E" in fields:
                delta = fields["E"] if relative_e else fields["E"] - e
                e = e + fields["E"] if relative_e else fields["E"]
                if layer and delta > 1e-5 and None not in pos + new and 2 <= new[2] <= 18:
                    length = math.hypot(new[0] - pos[0], new[1] - pos[1])
                    if length > 1e-6:
                        samples = max(1, min(2000, math.ceil(length / .25)))
                        for i in range(samples):
                            t = (i + .5) / samples
                            x, y = (pos[a] + t * (new[a] - pos[a]) for a in (0, 1))
                            if 122 <= x <= 128 and 102 <= y <= 108:
                                inside += delta / samples
                            elif 116 <= x <= 134 and 96 <= y <= 114:
                                outside += delta / samples
            pos = new
    return inside, outside


def main(binary, vendor, baseline, modifier, negative):
    raw = Path(vendor).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    with TemporaryDirectory(prefix="prusa-native-regions-") as tmp:
        folder = Path(tmp)
        profiles = []
        for kind, name in (("printer", "Original Prusa i3 MK2S"),
                           ("filament", "Generic PLA"), ("print", "0.20mm NORMAL")):
            path = folder / (kind + ".ini")
            path.write_bytes(flatten_prusa_vendor_preset(raw, kind=kind, name=name, expected_sha256=digest))
            profiles.extend(["--load", str(path)])
        results = []
        for label, project in (("baseline", baseline), ("modifier", modifier), ("negative", negative)):
            output = folder / (label + ".gcode")
            subprocess.run([binary, *profiles, "--export-gcode", "--output", str(output),
                            "--dont-arrange", project], cwd=folder, check=True, timeout=300)
            result = regional_extrusion(output.read_bytes())
            results.append(result)
            print("Native Prusa regional deposition", label, result)
        base, changed, cut = results
        assert base[0] > .1 and base[1] > .1, ("missing baseline", base)
        assert changed[0] > 1.5 * base[0] and changed[1] > .1, ("modifier not applied", changed)
        assert cut[0] < .01 and cut[1] > .1, ("cavity deposition or empty part", cut)
        print("PASS: native Prusa parameter modifier increases regional extrusion; negative volume removes interior deposition.")


if __name__ == "__main__":
    main(*sys.argv[1:])
