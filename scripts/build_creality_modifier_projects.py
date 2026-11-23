"""Wrap verified modifier fixtures in Creality Print v7.3.1 native projects.

Diagnostic only. This uses the existing strict MakerVault Creality project
packager with official fully resolved K1 presets. No production slice approval.
"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from core.slicer_creality_project import build_creality_project_candidate


def prepare(fixtures):
    directory = Path(fixtures)
    printer = (directory / "printer.json").read_bytes()
    process = (directory / "process.json").read_bytes()
    filament = (directory / "filament.json").read_bytes()
    output = []
    for label in ("baseline", "modified", "lower", "both"):
        src = directory / (label + ".3mf")
        dest = directory / ("native-" + label + ".3mf")
        if src.is_symlink() or not src.is_file() or dest.exists() or dest.is_symlink():
            raise ValueError("Invalid Creality modifier project fixture source or output.")
        project = build_creality_project_candidate(
            src.read_bytes(), printer=printer, process=process,
            filaments=[filament, filament], version="7.3.1",
            bed_width=220, bed_depth=220,
        )
        dest.write_bytes(project)
        output.append(dest.name)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    args = parser.parse_args()
    print("Built test-only Creality native modifier projects:", ", ".join(prepare(args.fixtures)))


if __name__ == "__main__":
    main()
