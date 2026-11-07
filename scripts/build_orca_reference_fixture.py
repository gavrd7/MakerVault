"""Build isolated *test-only* native Orca profile fixtures from upstream v2.4.2.

This utility NEVER imports or approves profiles in MakerVault. Parent chains
are loaded only from the pinned upstream Creality namespace and flattened for
the offline, single-model real CLI acceptance test.
"""
import argparse
import json
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

REF = "v2.4.2"
SOURCE = f"https://raw.githubusercontent.com/OrcaSlicer/OrcaSlicer/{REF}/resources/profiles/Creality"
FIXTURES = {
    "k1": {
        "printer": "Creality K1 (0.4 nozzle)",
        "process": "0.20mm Standard @Creality K1 (0.4 nozzle)",
        "filament": "Creality Generic PLA",
    },
    "k2": {
        "printer": "Creality K2 0.4 nozzle",
        "process": "0.20mm Standard @Creality K2 0.4 nozzle",
        "filament": "Creality Generic PLA @K2-all",
    },
}
DIRECTORIES = {"printer": "machine", "process": "process", "filament": "filament"}


def _get(kind, name, opener=urlopen):
    if not isinstance(name, str) or not 1 <= len(name) <= 160 or any(
        ch in name for ch in ("/", chr(92), chr(0))
    ) or name in {".", ".."}:
        raise ValueError("Unsafe upstream profile name.")
    url = SOURCE + "/" + DIRECTORIES[kind] + "/" + quote(name + ".json", safe="")
    with opener(Request(url, headers={"User-Agent": "MakerVault-Orca-Offline-Fixture"}), timeout=30) as response:
        raw = response.read(1024 * 1024 + 1)
    if not raw or len(raw) > 1024 * 1024:
        raise ValueError("Official native profile is empty or exceeds 1 MiB.")
    obj = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(obj, dict) or obj.get("name") != name or obj.get("type") != DIRECTORIES[kind]:
        raise ValueError("Official native profile kind or name mismatch.")
    return obj


def resolved(kind, name, *, opener=urlopen, ancestors=()):
    if name in ancestors or len(ancestors) >= 12:
        raise ValueError("Official native profile inheritance is circular or too deep.")
    child = _get(kind, name, opener=opener)
    parent = child.get("inherits")
    if parent:
        if not isinstance(parent, str):
            raise ValueError("Invalid native parent name.")
        result = resolved(kind, parent, opener=opener, ancestors=ancestors + (name,))
        result.update(child)
    else:
        result = child.copy()
    result.pop("inherits", None)
    return result


def generate(destination, printer, *, opener=urlopen):
    if printer not in FIXTURES:
        raise ValueError("Only pinned K1 and K2 reference fixtures are supported.")
    target = Path(destination)
    if target.is_symlink() or (target.exists() and any(target.iterdir())):
        raise ValueError("Output fixture directory must be empty and not a symlink.")
    target.mkdir(parents=True, exist_ok=True)
    for kind, name in FIXTURES[printer].items():
        data = resolved(kind, name, opener=opener)
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
