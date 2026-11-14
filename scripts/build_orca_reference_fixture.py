"""Build isolated *test-only* native Orca profile fixtures from upstream v2.5.0.

This utility NEVER imports or approves profiles in MakerVault. Parent chains
are loaded only from each pinned upstream vendor namespace and flattened for
the offline, single-model real CLI acceptance test.
"""
import argparse
import sys

import json
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from slicer_worker.orca_runner import FORBIDDEN_KEYS

REF = "v2.5.0"
SOURCE = f"https://raw.githubusercontent.com/OrcaSlicer/OrcaSlicer/{REF}/resources/profiles"
FIXTURES = {
    "k1": {
        "vendor": "Creality",
        "printer": "Creality K1 (0.4 nozzle)",
        "process": "0.20mm Standard @Creality K1 (0.4 nozzle)",
        "filament": "Generic PLA @Creality K1-all",
    },
    "k2": {
        "vendor": "Creality",
        "printer": "Creality K2 0.4 nozzle",
        "process": "0.20mm Standard @Creality K2 0.4 nozzle",
        "filament": "Generic PLA @K2-all",
    },
    "prusa-mk4": {
        "vendor": "Prusa",
        "printer": "Prusa MK4 0.4 nozzle",
        "process": "0.20mm Standard @MK4",
        "filament": "Generic PLA @Prusa MK4",
    },
}
DIRECTORIES = {"printer": "machine", "process": "process", "filament": "filament"}


def _get(kind, name, opener=urlopen, vendor="Creality"):
    if not isinstance(name, str) or not 1 <= len(name) <= 160 or any(
        ch in name for ch in ("/", chr(92), chr(0))
    ) or name in {".", ".."}:
        raise ValueError("Unsafe upstream profile name.")
    if vendor not in ("Creality", "Prusa"):
        raise ValueError("Unsupported pinned fixture vendor.")
    url = SOURCE + "/" + vendor + "/" + DIRECTORIES[kind] + "/" + quote(name + ".json", safe="")
    with opener(Request(url, headers={"User-Agent": "MakerVault-Orca-Offline-Fixture"}), timeout=30) as response:
        raw = response.read(1024 * 1024 + 1)
    if not raw or len(raw) > 1024 * 1024:
        raise ValueError("Official native profile is empty or exceeds 1 MiB.")
    obj = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(obj, dict) or obj.get("name") != name or obj.get("type") != DIRECTORIES[kind]:
        raise ValueError("Official native profile kind or name mismatch.")
    return obj


def resolved(kind, name, *, opener=urlopen, ancestors=(), vendor="Creality"):
    if name in ancestors or len(ancestors) >= 12:
        raise ValueError("Official native profile inheritance is circular or too deep.")
    child = _get(kind, name, opener=opener, vendor=vendor)
    parent = child.get("inherits")
    if parent:
        if not isinstance(parent, str):
            raise ValueError("Invalid native parent name.")
        result = resolved(kind, parent, opener=opener, ancestors=ancestors + (name,), vendor=vendor)
        result.update(child)
    else:
        result = child.copy()
    result.pop("inherits", None)
    return result


def generate(destination, printer, *, opener=urlopen):
    if printer not in FIXTURES:
        raise ValueError("Only pinned reference fixtures are supported.")
    target = Path(destination)
    if target.is_symlink() or (target.exists() and any(target.iterdir())):
        raise ValueError("Output fixture directory must be empty and not a symlink.")
    target.mkdir(parents=True, exist_ok=True)
    fixture = FIXTURES[printer]
    for kind in ("printer", "filament", "process"):
        name = fixture[kind]
        data = resolved(kind, name, opener=opener, vendor=fixture["vendor"])
        if printer == "k2" and kind == "printer" and data.get("retraction_distances_when_cut") == "30":
            # Reference-only workaround for the earlier 2.4.2 validation
            # discrepancy. Keep disabled when the new upstream profile has
            # corrected it; never modify production manufacturer profiles.
            data["retraction_distances_when_cut"] = "18"
            print("K2 TEST-ONLY override: retraction_distances_when_cut 30 -> 18; NOT production-approved.", file=sys.stderr)
        # Real upstream system presets may contain print-host/postprocess keys.
        # Test-only sandbox strips these even if empty; production's normal
        # validator remains strict and must still independently approve files.
        stripped = [key for key in data if key.strip().lower() in FORBIDDEN_KEYS]
        for key in stripped:
            del data[key]
        if stripped:
            print(f"Fixture-only stripped forbidden {kind} settings: {', '.join(sorted(stripped))}", file=sys.stderr)
        (target / (kind + ".json")).write_text(json.dumps(data, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--printer", choices=sorted(FIXTURES), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    generate(args.output, args.printer)


if __name__ == "__main__":
    main()
