"""Diagnostic only: compare Bambu single-model negative subtraction against a plain cube.

No production feature approvals, image publishing, deployment, or printer I/O.
The independent two-model composite test remains the required acceptance gate.
"""
import argparse
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from .bambu_runner import run_bambu
from .composite_acceptance_probe import two_model_region_extrusion
from .runner import WorkerError
from .three_mf_validation import validate_worker_3mf


def diagnose(fixtures, binary):
    fixtures = Path(fixtures)
    output = {}
    for name in ("single-baseline", "single-negative"):
        model = (fixtures / (name + ".3mf")).read_bytes()
        # An ordinary baseline 3MF has no nested non-printing parts and
        # must pass the normal worker validator; only the negative fixture
        # is eligible for the strictly bounded composite-fixture validator.
        validate_worker_3mf(model, allow_native_modifier_fixture=(name == "single-negative"))
        with TemporaryDirectory(prefix="single-negative-proof-") as temp:
            root = Path(temp)
            for profile in ("printer.json", "process.json", "filament.json"):
                shutil.copyfile(fixtures / profile, root / profile)
            (root / "input.3mf").write_bytes(model)
            if name == "single-negative":
                (root / "native-modifier-project.marker").write_text("v1")
            result = run_bambu(Path(binary), root, timeout_seconds=180)
            if result.get("status") != "completed":
                raise WorkerError("Bambu single negative diagnostic failed to complete.")
            output[name] = two_model_region_extrusion(Path(result["gcode_path"]).read_bytes())
            print("Single model native negative diagnostic:", name,
                  json.dumps(output[name], sort_keys=True), flush=True)
    base = output["single-baseline"]["totals"]["left"]
    cut = output["single-negative"]["totals"]["left"]
    result = {"engine": "bambustudio", "baseline_left_e_mm": round(base, 4),
              "negative_left_e_mm": round(cut, 4),
              "subtraction_indicated": base > 0 and cut < base * 0.9,
              "note": "Diagnostic only; production gate remains closed."}
    print(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    args = parser.parse_args()
    diagnose(args.fixtures, args.binary)


if __name__ == "__main__":
    main()
