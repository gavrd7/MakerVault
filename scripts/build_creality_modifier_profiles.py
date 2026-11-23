"""Pinned, resolved Creality Print v7.3.1 K1 presets for offline modifier tests.

Never imports native presets or modifies MakerVault's stored profile records.
Only fixed upstream Creality vendor files can be fetched.
"""
import argparse
import json
from pathlib import Path
import re
from urllib.parse import quote
from urllib.request import Request, urlopen

BASE = "https://raw.githubusercontent.com/CrealityOfficial/CrealityPrint/v7.3.1/resources/profiles/Creality"
FIXED = {
    "printer": ("machine", "Creality K1 0.4 nozzle"),
    "process": ("process", "0.20mm Standard @Creality K1 0.4 nozzle"),
    "filament": ("filament", "Generic PLA @Creality K1 0.4 nozzle"),
}
_NAME = re.compile(r"^[A-Za-z0-9 @_.+-]{1,128}$")


def _read(kind, name):
    if kind not in {"machine", "process", "filament"} or not _NAME.fullmatch(name):
        raise ValueError("Unsafe pinned native preset identity.")
    url = BASE + "/" + kind + "/" + quote(name + ".json", safe="")
    req = Request(url, headers={"User-Agent": "MakerVault-Creality-Modifier-CI/1"})
    with urlopen(req, timeout=30) as response:
        raw = response.read(1024 * 1024 + 1)
    if not 0 < len(raw) <= 1024 * 1024:
        raise ValueError("Official Creality preset exceeded fixture bound.")
    document = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(document, dict) or document.get("type") != kind:
        raise ValueError("Incorrect pinned Creality native preset type.")
    return document


def resolve(kind, name, seen=()):
    if name in seen or len(seen) >= 12:
        raise ValueError("Invalid native Creality preset inheritance chain.")
    profile = _read(kind, name)
    parent = profile.get("inherits")
    if parent:
        if not isinstance(parent, str):
            raise ValueError("Invalid inherited preset identity.")
        value = resolve(kind, parent, seen + (name,))
        value.update(profile)
    else:
        value = profile.copy()
    value.pop("inherits", None)
    return value


def generate(outdir):
    target = Path(outdir)
    if target.is_symlink() or (target.exists() and any(target.iterdir())):
        raise ValueError("Fixture target must be a fresh or empty directory.")
    target.mkdir(parents=True, exist_ok=True)
    for outname, (kind, profile) in FIXED.items():
        value = resolve(kind, profile)
        # Prevent network hosts/post-processing in the disposable diagnostic.
        from slicer_worker.orca_runner import FORBIDDEN_KEYS
        for key in list(value):
            if key.lower() in FORBIDDEN_KEYS:
                value.pop(key)
        if outname == "process":
            value["sparse_infill_density"] = "15%"
        (target / (outname + ".json")).write_text(
            json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print("Resolved pinned K1 Creality candidate presets:", generate(args.output))


if __name__ == "__main__":
    main()
