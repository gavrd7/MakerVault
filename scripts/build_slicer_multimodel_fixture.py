"""Create a disposable two-object 3MF using MakerVault's real plate builder.

This must run in CI before building the isolated engine image. It contains
two separated native STL instances and no external assets, scripts or URLs.
"""
import argparse
import io
from pathlib import Path
import sys
import zipfile
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from core.slicer_plate_3mf import build_plate_3mf, NS
from slicer_worker.probe import fixture_stl
from slicer_worker.three_mf_validation import validate_worker_3mf


def generate(path):
    output = Path(path)
    if output.exists() or output.is_symlink():
        raise ValueError("Fixture output already exists.")
    stl = fixture_stl()
    objects = [
        ({"x_mm": -35, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100}, stl),
        ({"x_mm": 35, "y_mm": 0, "rotation_deg": 90, "scale_percent": 100}, stl),
    ]
    data = build_plate_3mf(objects, bed_width=220, bed_depth=220)
    validate_worker_3mf(data)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        root = ET.fromstring(archive.read("3D/3dmodel.model"))
    items = root.findall("./{%s}build/{%s}item" % (NS, NS))
    if len(items) != 2:
        raise ValueError("The MakerVault plate builder did not preserve both instances.")
    positions = [float(item.attrib["transform"].split()[9]) for item in items]
    if abs(positions[1] - positions[0]) < 60:
        raise ValueError("Fixture STL objects were not separated far enough.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    print("Created validated two-object MakerVault 3MF fixture: " + str(output))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    generate(args.output)


if __name__ == "__main__":
    main()
