"""Prusa 2.9.7 native painted-project parser smoke; not semantic painting approval."""
import hashlib
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset
from slicer_worker.prusa_gcode_audit import audit_prusa_positive_e


def main(binary, vendor, *projects):
    source = Path(vendor).read_bytes()
    identity = hashlib.sha256(source).hexdigest()
    digests = {}
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
            print("PASS: Prusa 2.9.7 native painted project import and slice:", name,
                  result["positive_e_moves"], "positive extrusion moves",
                  "motion-sha256", digests[name])
    print("Motion comparison against unpainted baseline:",
          {key: value != digests.get("baseline") for key, value in digests.items()})
    print("NOTE: patch import alone does not demonstrate support, seam or fuzzy semantic effect.")


if __name__ == "__main__":
    main(*sys.argv[1:])
