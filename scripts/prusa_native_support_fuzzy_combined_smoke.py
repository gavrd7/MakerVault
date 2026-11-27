"""Pinned Prusa 2.9.7 qualification of simultaneous support and fuzzy wall paint.

A successful import or changed G-code hash is not sufficient. Require moving
support deposition and short external perimeter paths on disjoint native facets.
The same geometry is sliced four times as independent controls.
"""
import hashlib
import math
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset
from slicer_worker.prusa_gcode_audit import audit_prusa_positive_e, WORD


def measure(data):
    audit_prusa_positive_e(data)
    x = y = z = None
    e = 0.
    relative_e = False
    relative_xy = False
    role = ""
    supports = 0
    fuzzy_front = 0
    for line in data.decode("utf-8").splitlines():
        if line.startswith(";TYPE:"):
            role = line.partition(":")[2].strip().lower()
        code = line.split(";", 1)[0].strip()
        if not code:
            continue
        op = code.split(None, 1)[0].upper()
        values = {key.upper(): float(value) for key, value in WORD.findall(code)}
        if op == "M82":
            relative_e = False
        elif op == "M83":
            relative_e = True
        elif op == "G90":
            relative_xy = False
        elif op == "G91":
            relative_xy = True
        elif op == "G92":
            e = values.get("E", e)
            x, y, z = (values.get(k, old) for k, old in
                       zip("XYZ", (x, y, z)))
        elif op in ("G0", "G00", "G1", "G01"):
            old_x, old_y, old_z = x, y, z
            if relative_xy:
                x = (x + values["X"]) if x is not None and "X" in values else x
                y = (y + values["Y"]) if y is not None and "Y" in values else y
            else:
                x, y = values.get("X", x), values.get("Y", y)
            z = values.get("Z", z)
            if "E" not in values:
                continue
            delta = values["E"] if relative_e else values["E"] - e
            e = e + values["E"] if relative_e else values["E"]
            if (op not in ("G1", "G01") or delta <= 1e-6 or
                    None in (x, y, z, old_x, old_y, old_z)):
                continue
            length = math.hypot(x - old_x, y - old_y)
            if length <= 1e-6:
                continue  # stationary E recovery is not deposited support
            if ("support material" in role and 1 < z < 26 and
                    106 <= (x + old_x)/2 <= 144 and
                    95 <= (y + old_y)/2 <= 115):
                supports += 1
            if ("external perimeter" in role and .01 < length < 1.25
                    and 3 <= z <= 23
                    and 109 <= (x + old_x)/2 <= 141
                    and 97.5 <= (y + old_y)/2 <= 100.5):
                fuzzy_front += 1
    return supports, fuzzy_front


def main(binary, vendor, folder):
    root = Path(folder)
    raw = Path(vendor).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    with TemporaryDirectory(prefix="prusa-support-fuzzy-") as temp:
        work = Path(temp)
        arguments = []
        for kind, name in (("printer", "Original Prusa i3 MK2S"),
                           ("filament", "Generic PLA"),
                           ("print", "0.20mm NORMAL")):
            data = flatten_prusa_vendor_preset(raw, kind=kind, name=name,
                                               expected_sha256=digest)
            if kind == "print":
                # Support enforcers only: never let automatic supports mask
                # unrelated paint-region leakage.
                options = [line for line in data.decode("utf-8").splitlines()
                           if line.split("=", 1)[0].strip() not in
                           {"support_material", "support_material_auto"}]
                data = ("\n".join(options + [
                    "support_material = 1", "support_material_auto = 0"
                ]) + "\n").encode("utf-8")
            path = work / (kind + ".ini")
            path.write_bytes(data)
            arguments.extend(["--load", str(path)])
        receipts = {}
        for name in ("baseline", "support", "fuzzy", "combined"):
            output = work / (name + ".gcode")
            subprocess.run([binary, *arguments, "--export-gcode",
                            "--dont-arrange", "--output", str(output),
                            str(root / (name + ".3mf"))],
                           check=True, timeout=300, cwd=work)
            receipts[name] = measure(output.read_bytes())
            print("Native Prusa support/fuzzy combination", name,
                  receipts[name], flush=True)
        base, support, fuzzy, both = (receipts[name] for name in
                                      ("baseline", "support", "fuzzy", "combined"))
        if (base[0] > 2 or fuzzy[0] > 2 or
                support[0] < 25 or both[0] < support[0] * .65 or
                both[0] > support[0] * 1.4):
            raise AssertionError(("Combined support deposition unqualified",
                                  receipts))
        if (base[1] > 10 or support[1] > 10 or
                fuzzy[1] < 30 or both[1] < fuzzy[1] * .65):
            raise AssertionError(("Combined fuzzy front-wall unqualified",
                                  receipts))
        print("PASS: native Prusa support and selective fuzzy skin coexist "
              "on distinct facets with independently audited moving G-code.",
              flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
