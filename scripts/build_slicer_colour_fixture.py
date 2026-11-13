"""Generate a separate, test-only native Orca filament-colour fixture.

Uses an already resolved, verified upstream filament profile; only the
native display-colour field changes. It does NOT calibrate a physical spool,
create CFS commands, or enable printing. The two resulting presets can be
passed independently through the pinned Orca 2.5 worker acceptance test.
"""
import argparse
import json
from pathlib import Path
import re

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def generate(source, destination, colour):
    src, dest = Path(source), Path(destination)
    if not HEX.fullmatch(colour):
        raise ValueError("Native filament colour must be an RGB hex value.")
    if src.is_symlink() or not src.is_file() or not 0 < src.stat().st_size <= 1024 * 1024:
        raise ValueError("Invalid source native filament preset.")
    if dest.exists() or dest.is_symlink():
        raise ValueError("Refusing to overwrite a native filament preset.")
    profile = json.loads(src.read_bytes())
    if not isinstance(profile, dict) or profile.get("inherits"):
        raise ValueError("Filament preset must be resolved native JSON.")
    profile["default_filament_colour"] = [colour.upper()]
    dest.write_text(json.dumps(profile, separators=(",", ":")), encoding="utf-8")
    return dest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filament", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--colour", required=True)
    args = parser.parse_args(argv)
    generate(args.filament, args.output, args.colour)


if __name__ == "__main__":
    main()
