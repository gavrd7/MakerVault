"""Offline-only Orca CFS flushing/prime tower acceptance process fixture.

This uses the same validated MakerVault native override path as future job
preflight. The values are deliberately explicit *test fixtures*, not official
Creality calibration or manufacturer recommendations. No printer connection.
"""
import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from core.slicer_flush_settings import apply_orca_flush_settings


def generate(source, destination, *, prime_tower="enabled"):
    source = Path(source)
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ValueError("Refusing to overwrite a native process fixture.")
    data = json.loads(source.read_bytes())
    if not isinstance(data, dict):
        raise ValueError("Native Orca process must be a JSON object.")
    # Exactly two explicitly verified native slots in the isolated CI fixture:
    # remove incompatible broad default matrices rather than guessing their
    # dimension or mapping, and supply every directional transition.
    data.pop("flush_volumes_matrix", None)
    settings = {
        "multiplier": 1.0,
        "prime_tower": prime_tower,
        "transitions": [
            {"from_slot_id": "test-tool-0", "to_slot_id": "test-tool-1",
             "volume_mm3": 300},
            {"from_slot_id": "test-tool-1", "to_slot_id": "test-tool-0",
             "volume_mm3": 220},
        ],
    }
    routes = [
        SimpleNamespace(slot_id="test-tool-0", tool_index=0),
        SimpleNamespace(slot_id="test-tool-1", tool_index=1),
    ]
    output = apply_orca_flush_settings(
        json.dumps(data, ensure_ascii=False).encode(), settings,
        routes=routes, tool_count=2, topology="single_nozzle_changer",
    )
    destination.write_bytes(output)
    print("Offline two-tool flush settings prepared: 300/220 mm³, prime tower enabled.")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--process", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--prime-tower", choices=("native", "enabled", "disabled"), default="enabled")
    args = parser.parse_args(argv)
    generate(args.process, args.output, prime_tower=args.prime_tower)


if __name__ == "__main__":
    main()
