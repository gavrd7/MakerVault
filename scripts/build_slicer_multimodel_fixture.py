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

from core.slicer_plate_3mf import build_plate_3mf, build_compound_plate_3mf, NS
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


def object_settings_fixture(target):
    """Create the exact per-object project the real Orca CLI must accept.

    Both objects are equal geometry at separated X positions, with distinct
    wall loops and infill percentages. The G-code probe must confirm *both*
    positions extrude before this route is eligible for runtime use.
    """
    source = fixture_stl()
    entries = [
        ({"x_mm": -35, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100,
          "process_overrides": {"wall_loops": 2, "sparse_infill_density": 15}}, source),
        ({"x_mm": 35, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100,
          "process_overrides": {"wall_loops": 5, "sparse_infill_density": 37}}, source),
    ]
    data = build_plate_3mf(entries, bed_width=220, bed_depth=220)
    validate_worker_3mf(data)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        manifest = ET.fromstring(archive.read("Metadata/model_settings.config"))
        objects = manifest.findall("object")
        if len(objects) != 2 or [x.attrib.get("id") for x in objects] != ["1", "2"]:
            raise ValueError("Object IDs were lost in the generated native 3MF.")
        values = [{
            v.attrib["key"]: v.attrib["value"] for v in obj.findall("metadata")
        } for obj in objects]
        if values[0]["wall_loops"] != "2" or values[1]["wall_loops"] != "5":
            raise ValueError("Per-object wall settings were not saved correctly.")
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise ValueError("Object fixture output already exists.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    print("Created independent Orca per-object settings fixture: " + str(target))


def compound_preview(path, target):
    """Run the production compound builder against the same two source STLs."""
    targets = [
        ({"x_mm": -35, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100}, fixture_stl()),
        ({"x_mm": 35, "y_mm": 0, "rotation_deg": 90, "scale_percent": 100}, fixture_stl()),
    ]
    data = build_compound_plate_3mf(targets, bed_width=220, bed_depth=220)
    validate_worker_3mf(data)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        root = ET.fromstring(archive.read("3D/3dmodel.model"))
    ns = "{" + NS + "}"
    meshes = root.findall("./" + ns + "resources/" + ns + "object/" + ns + "mesh")
    if len(meshes) != 1:
        raise ValueError("The production compound builder did not generate one safe mesh.")
    vertices = meshes[0].find(ns + "vertices")
    triangles = meshes[0].find(ns + "triangles")
    positions = [float(v.attrib["x"]) for v in vertices]
    if len(triangles) != 8 or max(positions) - min(positions) < 60:
        raise ValueError("The production builder lost geometry or the separate X positions.")
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise ValueError("Compound output already exists.")
    target.write_bytes(data)
    print("Created production-builder compound 3MF fixture: " + str(target))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compound-output", type=Path)
    parser.add_argument("--object-output", type=Path)
    args = parser.parse_args()
    generate(args.output)
    if args.compound_output:
        compound_preview(args.output, args.compound_output)
    if args.object_output:
        object_settings_fixture(args.object_output)


if __name__ == "__main__":
    main()
