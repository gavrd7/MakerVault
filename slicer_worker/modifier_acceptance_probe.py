"""Offline diagnostic for actual Orca modifier-region G-code (never production).

Runs only with repository-generated fixture files inside a networkless disposable
container. Uses an explicit, strictly validated fixture-only 3MF gate for the nested
modifier object so real native parser/effectiveness can be examined.
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
from .bambu_runner import run_bambu
from .creality_runner import run_creality
from .runner import WorkerError
from .three_mf_validation import validate_worker_3mf as strict_worker_3mf


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


def probe(fixtures, binary, *, engine="orcaslicer"):
    if engine not in {"orcaslicer", "bambustudio", "crealityprint"}:
        raise WorkerError("Unsupported modifier acceptance engine.")
    fixtures = Path(fixtures)
    result = {}
    for label in ("baseline", "modified", "lower", "both"):
        with tempfile.TemporaryDirectory(prefix="modifier-real-orca-") as tmp:
            root = Path(tmp)
            for name in ("printer.json", "filament.json", "process.json"):
                shutil.copyfile(fixtures / name, root / name)
            source = fixtures / (label + ".3mf")
            if source.is_symlink() or not source.is_file():
                raise WorkerError("Native modifier test fixture missing.")
            shutil.copyfile(source, root / "input.3mf")
            # Test-only alternate admission: the default worker validator
            # still rejects nested modifier parts for production requests.
            # Never bypass the new explicit nested 3MF structural allowlist.
            def validate_fixture(data, **kwargs):
                # Bambu's test-only fixture has no vendor printer/material
                # project-settings sidecar; require the identical bounded
                # nested geometry/metadata validator without assuming Bambu
                # accepts the format. Real CLI acceptance remains mandatory.
                if engine == "bambustudio":
                    if kwargs.get("native_tool_count") is not None:
                        raise WorkerError("Modifier trial requires one native filament.")
                    kwargs.pop("allow_bambu_project", None)
                    kwargs.pop("allow_bambu_combined_paint", None)
                    kwargs.pop("allow_bambu_layer_ranges", None)
                if label != "baseline":
                    return strict_worker_3mf(
                        data, allow_native_modifier_fixture=True, **kwargs)
                return strict_worker_3mf(data, **kwargs)
            module = {
                "orcaslicer": "slicer_worker.orca_runner.validate_worker_3mf",
                "bambustudio": "slicer_worker.bambu_runner.validate_worker_3mf",
                "crealityprint": "slicer_worker.creality_runner.validate_worker_3mf",
            }[engine]
            runner = {
                "orcaslicer": run_orca, "bambustudio": run_bambu,
                "crealityprint": run_creality,
            }[engine]
            with patch(module, side_effect=validate_fixture):
                receipt = runner(Path(binary), root, timeout_seconds=180)
            if receipt.get("status") != "completed":
                raise WorkerError("Actual " + engine + " CLI did not complete " + label + " fixture.")
            result[label] = regional_extrusion(root.joinpath("output.gcode").read_bytes())
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
    # Move the same modifier to the opposite Z band: the effect must
    # reverse, and two independent modifiers must change both bands.
    lower = result["lower"]
    both = result["both"]
    def enough_moves(case, region):
        if case["moves"][region] < 20:
            raise WorkerError("Missing positive-E deposition for " + region)
    for label in ("lower", "both"):
        for region in ("control", "changed"):
            enough_moves(result[label], region)
    if lower["totals"]["control"] <= baseline_control * 1.20:
        raise WorkerError("Moving the modifier to the lower region did not increase lower extrusion.")
    if abs(lower["totals"]["changed"] - original) > original * .10:
        raise WorkerError("Lower modifier unexpectedly changed the upper control region.")
    for region, isolated in (("control", lower), ("changed", modified)):
        expected = isolated["totals"][region]
        actual = both["totals"][region]
        if abs(actual - expected) > expected * .12:
            raise WorkerError("Paired modifiers did not preserve isolated " + region + " effect.")
    return {"status": "passed", "engine": engine,
            "change_ratio": round(altered / original, 3),
            "control_ratio": round(changed_control / baseline_control, 3),
            "lower_change_ratio": round(lower["totals"]["control"] / baseline_control, 3),
            "evidence": result,
            "note": "Offline actual CLI G-code evidence; production modifier admission remains disabled."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--engine", choices=("orcaslicer", "bambustudio", "crealityprint"), default="orcaslicer")
    parser.add_argument("--binary", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(probe(args.fixtures, args.binary, engine=args.engine), indent=2))
    except (WorkerError, OSError, ValueError) as exc:
        parser.exit(1, "Native modifier real Orca diagnostic failed: " + str(exc) + "\n")


if __name__ == "__main__":
    main()
