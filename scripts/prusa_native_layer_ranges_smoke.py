"""Real PrusaSlicer 2.9.7 CLI acceptance of native object-local Z ranges."""
import hashlib
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset
from slicer_worker.prusa_gcode_audit import audit_prusa_positive_e

# Separate from the backend! This script audits actual Prusa G-code.
def observed(gcode, lower=5, upper=15):
    positions = []
    pending = 0
    for line in gcode.decode("utf-8").splitlines():
        line = line.strip()
        if line == ";LAYER_CHANGE":
            pending = 8
            continue
        if pending:
            pending -= 1
            if line.startswith(";Z:"):
                try:
                    z = float(line[3:].strip())
                except ValueError:
                    continue
                if not positions or z > positions[-1]:
                    positions.append(z)
                pending = 0
    pairs = [(a,b) for a,b in zip(positions,positions[1:])
             if a >= lower and b <= upper]
    return [round(b-a, 4) for a,b in pairs], positions


def main(binary, vendor, plain, ranged, modifier=None, mixed=None):
    source = Path(vendor).read_bytes()
    identity = hashlib.sha256(source).hexdigest()
    with TemporaryDirectory(prefix="prusa-layer-ranges-") as tmp:
        home = Path(tmp)
        presets = []
        for kind, name in (("printer", "Original Prusa i3 MK2S"),
                           ("filament", "Generic PLA"), ("print", "0.20mm NORMAL")):
            dest = home / (kind + ".ini")
            dest.write_bytes(flatten_prusa_vendor_preset(
                source, kind=kind, name=name, expected_sha256=identity))
            presets.extend(["--load", str(dest)])
        data = []
        for label, project in (("baseline", plain), ("range", ranged)):
            output = home / (label + ".gcode")
            subprocess.run([binary, *presets, "--export-gcode", "--dont-arrange",
                            "--output", str(output), project],
                           cwd=home, check=True, timeout=300)
            raw = output.read_bytes()
            audit = audit_prusa_positive_e(raw)
            assert audit["positive_e_moves"] > 40, audit
            steps, z = observed(raw)
            assert len(steps) >= 12, (label, steps, z[:8])
            data.append(steps)
            print("Native Prusa layer steps", label, len(steps), sorted(set(steps))[:12])
        plain_steps, ranged_steps = data
        assert sum(abs(x-.2) <= .015 for x in plain_steps) > len(plain_steps)*.70, plain_steps
        assert sum(abs(x-.12) <= .016 for x in ranged_steps) > len(ranged_steps)*.70, ranged_steps
        assert abs(len(ranged_steps) - len(plain_steps)) > 15, (len(plain_steps),len(ranged_steps))
        print("PASS: real Prusa 2.9.7 native 3MF layer ranges changed actual toolpath Z steps.")

        if modifier is not None and mixed is not None:
            import runpy
            regional = runpy.run_path("/tmp/prusa_regions.py")["regional_extrusion"]
            # Native per-layer Z transitions must remain independent of the
            # parameter modifier's requested internal infill density.
            controls = {}
            for label, project in (("baseline", plain), ("layer", ranged),
                                   ("modifier", modifier), ("mixed", mixed)):
                output = home / ("proof-" + label + ".gcode")
                subprocess.run([binary, *presets, "--export-gcode",
                    "--dont-arrange", "--output", str(output), project],
                    cwd=home, check=True, timeout=300)
                raw = output.read_bytes()
                steps, _positions = observed(raw)
                inside, outside = regional(raw)
                controls[label] = (steps, inside, outside)
                print("Prusa native layer plus modifier", label,
                    "steps", sorted(set(steps)), "inside", round(inside, 3),
                    "outside", round(outside, 3), flush=True)
            plain_inside = controls["baseline"][1]
            layer_inside = controls["layer"][1]
            modified_inside = controls["modifier"][1]
            mixed_inside = controls["mixed"][1]
            if (plain_inside <= .1 or layer_inside <= .1 or
                    modified_inside <= plain_inside * 1.5 or
                    mixed_inside <= layer_inside * 1.5):
                raise AssertionError(
                    ("Native variable layers lost regional modifier deposition",
                     plain_inside, layer_inside, modified_inside, mixed_inside))
            steps = controls["mixed"][0]
            if (len(steps) < 12 or
                    sum(abs(x-.12) <= .016 for x in steps) <= len(steps) * .70):
                raise AssertionError(
                    ("Native modifier changed the requested variable Z schedule",
                     sorted(set(steps)), len(steps)))
            if controls["mixed"][2] <= .1:
                raise AssertionError(
                    "Native modifier plus variable layers lost outer model deposition.")
            print("PASS: pinned Prusa native variable layers and local parameter "
                  "modifier independently alter Z steps and regional extrusion.",
                  flush=True)



if __name__ == "__main__":
    main(*sys.argv[1:])
