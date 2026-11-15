"""Version-pinned OrcaSlicer source correction for upstream's native K2 CLI mismatch.

The v2.5.0 official Creality K2 profile contains a 30 mm cut-retraction
distance, but the exact same engine's validation schema caps the parameter
at 18 mm. This opt-in SOURCE patch changes the schema upper bound to 30 mm.
It does NOT rewrite any vendor profile, suppress validation, or modify a
downloaded official AppImage. The corrected engine must be compiled, audited,
checksum-pinned, and tested independently before staging.

Do not automatically apply this to future upstream engine revisions.
"""
import argparse
from pathlib import Path
import subprocess

ORCA_TAG = "v2.5.0"
ORCA_COMMIT = "40ecc66f78ed72dc368e0c1ebe40d77f00cc8a19"
TARGET = Path("src/libslic3r/PrintConfig.cpp")
BEFORE = '''    def = this->add("retraction_distances_when_cut",coFloats);
    def->label = L("Retraction distance when cut");
    def->tooltip = L("Experimental feature: Retraction length before cutting off during filament change.");
    def->mode = comDevelop;
    def->min = 10;
    def->max = 18;
    def->set_default_value(new ConfigOptionFloats {18});'''
AFTER = BEFORE.replace("    def->max = 18;", "    def->max = 30;")


def patched_source(source: str) -> str:
    """Patch only the known schema entry; fail on unexpected upstream changes."""
    if source.count(BEFORE) != 1 or AFTER in source:
        raise ValueError("Orca source does not match the reviewed v2.5.0 validation block.")
    return source.replace(BEFORE, AFTER, 1)


def apply_to_checkout(root: Path, *, dry_run=False):
    root = root.resolve(strict=True)
    if not (root / ".git").exists() or not (root / TARGET).is_file():
        raise ValueError("Expected a complete OrcaSlicer source checkout.")
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                         capture_output=True, text=True, check=True).stdout.strip()
    if sha != ORCA_COMMIT:
        raise ValueError("Unexpected Orca source revision; only pinned v2.5.0 is supported.")
    changes = subprocess.run(["git", "status", "--porcelain"], cwd=root,
                             capture_output=True, text=True, check=True).stdout
    if changes:
        raise ValueError("Source checkout must be clean before applying the patch.")
    path = root / TARGET
    original = path.read_text(encoding="utf-8")
    revised = patched_source(original)
    if not dry_run:
        path.write_text(revised, encoding="utf-8")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path, help="Clean, verified OrcaSlicer v2.5.0 checkout")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        path = apply_to_checkout(args.checkout, dry_run=args.dry_run)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Orca compatibility source patch refused: {exc}\n")
    print(f"{'Validated' if args.dry_run else 'Patched'}: {path}")
    print("Review the diff; build a new AppImage from source. Do not deploy the official")
    print("unmodified AppImage and expect this source correction to take effect.")


if __name__ == "__main__":
    main()
