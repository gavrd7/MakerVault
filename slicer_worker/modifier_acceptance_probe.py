"""Offline diagnostic for actual Orca modifier-region G-code (never production).

Runs only with repository-generated fixture files inside a networkless disposable
container. Temporarily bypasses the *production* flat-3MF admission validator
for this one trusted test fixture so native parser/effectiveness can be examined.
A pass is diagnostic evidence, NOT approval to enable modifier execution.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile
from unittest.mock import patch

from .orca_runner import run_orca
from .runner import WorkerError


_COMMAND = re.compile(r"^(G0?0|G0?1|G92|M82|M83|G90|G91)\b", re.I)
_WORDS = re.compile(r"\b([XYZE])([-+]?(?:\d+(?:\.\d*)?|\.\d+))", re.I)


def regional_extrusion(gcode):
    """Sum genuine planar positive E within central XY and fixed Z slices."""
    x = y = z = e = 0.0
    relative_e = False
    relative_xyz = False
    totals = {"control": 0.0, "changed": 0.0}
    moves = {"control": 0, "changed": 0}
    for raw in gcode.decode("utf-8", "replace").splitlines():
        code = raw.partition(";")[0].strip().upper()
        command = _COMMAND.match(code)
        if not command:
            continue
        op = command.group(1)
        if op in ("M82", "M83"):
            relative_e = op == "M83"
            continue
        if op in ("G90", "G91"):
            relative_xyz = op == "G91"
            continue
        words = {key: float(value) for key, value in _WORDS.findall(code)}
        if op == "G92":
            x, y, z, e = (words.get("X", x), words.get("Y", y),
                           words.get("Z", z), words.get("E", e))
            continue
        new_x = x + words["X"] if relative_xyz and "X" in words else words.get("X", x)
        new_y = y + words["Y"] if relative_xyz and "Y" in words else words.get("Y", y)
        new_z = z + words["Z"] if relative_xyz and "Z" in words else words.get("Z", z)
        extrusion = 0.0
        if "E" in words:
            extrusion = words["E"] if relative_e else words["E"] - e
            if not relative_e:
                e = words["E"]
        if op in ("G1", "G01") and extrusion > 0 and (new_x != x or new_y != y):
            # Use the segment midpoint, not its endpoint, for XY bounds.
            cx, cy = (x + new_x) / 2, (y + new_y) / 2
            if 98 <= cx <= 122 and 98 <= cy <= 122:
                region = "control" if 3 <= new_z <= 8 else (
                    "changed" if 12 <= new_z <= 18 else None)
                if region:
                    totals[region] += extrusion
                    moves[region] += 1
        x, y, z = new_x, new_y, new_z
    return {"totals": totals, "moves": moves}


def probe(fixtures, binary):
    fixtures = Path(fixtures)
    result = {}
    with tempfile.TemporaryDirectory(prefix="modifier-real-orca-") as tmp:
        root = Path(tmp)
        for name in ("printer.json", "filament.json", "process.json"):
            shutil.copyfile(fixtures / name, root / name)
        for label in ("baseline", "modified"):
            source = fixtures / (label + ".3mf")
            if source.is_symlink() or not source.is_file():
                raise WorkerError("Native modifier test fixture missing.")
            shutil.copyfile(source, root / "input.3mf")
            # Test-only admission bypass: do not import this into service.py.
            with patch("slicer_worker.orca_runner.validate_worker_3mf", return_value=True):
                receipt = run_orca(Path(binary), root, timeout_seconds=180)
            if receipt.get("status") != "completed":
                raise WorkerError("Actual Orca CLI did not complete " + label + " fixture.")
            gcode = root.joinpath("output.gcode").read_bytes()
            result[label] = regional_extrusion(gcode)
            root.joinpath("input.3mf").unlink()
            root.joinpath("output.gcode").unlink()
    baseline = result["baseline"]
    modified = result["modified"]
    for label in ("control", "changed"):
        if min(baseline["moves"][label], modified["moves"][label]) < 20:
            raise WorkerError("Native modifier fixture has insufficient " + label + " positive-E paths.")
    original = baseline["totals"]["changed"]
    altered = modified["totals"]["changed"]
    if original <= 0 or altered <= original * 1.20:
        raise WorkerError("Native 50% modifier did not increase central-region extrusion by >=20%.")
    baseline_control = baseline["totals"]["control"]
    changed_control = modified["totals"]["control"]
    if baseline_control <= 0 or abs(changed_control - baseline_control) > .10 * baseline_control:
        raise WorkerError("Native modifier changed the unaffected lower control region.")
    return {"status": "passed", "engine": "orcaslicer",
            "change_ratio": round(altered / original, 3),
            "control_ratio": round(changed_control / baseline_control, 3),
            "evidence": result,
            "note": "Offline actual CLI G-code evidence; production modifier admission remains disabled."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(probe(args.fixtures, args.binary), indent=2))
    except (WorkerError, OSError, ValueError) as exc:
        parser.exit(1, "Native modifier real Orca diagnostic failed: " + str(exc) + "\n")


if __name__ == "__main__":
    main()
