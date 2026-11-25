"""Prusa 2.9.7 native painted-project parser smoke; not semantic painting approval."""
import hashlib
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset
from slicer_worker.prusa_gcode_audit import audit_prusa_positive_e, WORD
import math



def _fuzzy_wall_audit(gcode):
    """Count short external perimeters on the one painted -Y wall vs +Y."""
    role = ""
    xyz = [None, None, None]
    relative = False
    e = 0.
    counts = {"painted_wall": 0, "opposite_wall": 0}
    for line in gcode.decode("utf-8").splitlines():
        if line.startswith(";TYPE:"):
            role = line.partition(":")[2].strip().lower()
        cmd = line.split(";", 1)[0].strip()
        if not cmd:
            continue
        op = cmd.split(None, 1)[0].upper()
        words = {k.upper(): float(v) for k, v in WORD.findall(cmd)}
        if op == "M82":
            relative = False
        elif op == "M83":
            relative = True
        elif op == "G92":
            e = words.get("E", e)
            xyz = [words.get(k, xyz[i]) for i, k in enumerate("XYZ")]
        elif op in ("G0", "G00", "G1", "G01"):
            new = [words.get(k, xyz[i]) for i, k in enumerate("XYZ")]
            if "E" in words:
                delta = words["E"] if relative else words["E"] - e
                e = e + words["E"] if relative else words["E"]
                if (delta > 1e-5 and None not in xyz + new and
                        2 <= new[2] <= 18 and "external perimeter" in role):
                    length = math.hypot(new[0]-xyz[0], new[1]-xyz[1])
                    middle = [(new[i]+xyz[i])/2 for i in (0,1)]
                    if .01 < length < 1.25 and 116 <= middle[0] <= 134:
                        if 94 <= middle[1] <= 97:
                            counts["painted_wall"] += 1
                        if 113 <= middle[1] <= 116:
                            counts["opposite_wall"] += 1
            xyz = new
    return counts


def main(binary, vendor, *projects):
    source = Path(vendor).read_bytes()
    identity = hashlib.sha256(source).hexdigest()
    digests = {}
    wall_counts = {}
    with TemporaryDirectory(prefix="prusa-paint-import-") as tmp:
        folder = Path(tmp)
        args = []
        for kind, preset in (("printer", "Original Prusa i3 MK2S"),
                             ("filament", "Generic PLA"), ("print", "0.20mm NORMAL")):
            path = folder / (kind + ".ini")
            path.write_bytes(flatten_prusa_vendor_preset(
                source, kind=kind, name=preset, expected_sha256=identity))
            args.extend(["--load", str(path)])
        for model in projects:
            name = Path(model).stem
            output = folder / (name + ".gcode")
            subprocess.run([binary, *args, "--export-gcode", "--dont-arrange",
                            "--output", str(output), model], cwd=folder,
                           check=True, timeout=300)
            raw = output.read_bytes()
            result = audit_prusa_positive_e(raw)
            assert result["positive_e_moves"] >= 40, (name, result)
            motion = "\\n".join(line.split(";", 1)[0].strip() for line in raw.decode("utf-8").splitlines()
                               if line.lstrip().startswith(("G0 ", "G1 "))).encode()
            digests[name] = hashlib.sha256(motion).hexdigest()[:16]
            wall_counts[name] = _fuzzy_wall_audit(raw)
            print("PASS: Prusa 2.9.7 native painted project import and slice:", name,
                  result["positive_e_moves"], "positive extrusion moves",
                  "motion-sha256", digests[name])
    print("Motion comparison against unpainted baseline:",
          {key: value != digests.get("baseline") for key, value in digests.items()})
    print("Native fuzzy wall-local short external perimeter audit:", wall_counts)
    print("NOTE: patch import alone does not demonstrate support, seam or fuzzy semantic effect.")


if __name__ == "__main__":
    main(*sys.argv[1:])
