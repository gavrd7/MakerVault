"""Create a disposable two-object 3MF using MakerVault's real plate builder.

This must run in CI before building the isolated engine image. It contains
two separated native STL instances and no external assets, scripts or URLs.
"""
import argparse
import io
import struct
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


def cube_fixture_stl(side=20.0):
    """Closed 12-triangle cube, large enough to compare native wall/infill paths."""
    p = [
        (0, 0, 0), (side, 0, 0), (side, side, 0), (0, side, 0),
        (0, 0, side), (side, 0, side), (side, side, side), (0, side, side),
    ]
    faces = [
        (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
        (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7),
    ]
    triangles = b"".join(
        struct.pack("<12fH", 0, 0, 1, *p[a], *p[b], *p[d], 0)
        for a, b, d in faces
    )
    return b"MakerVault native object process fixture".ljust(80, b" ") + (
        struct.pack("<I", len(faces)) + triangles
    )


def object_settings_fixture(target, *, reverse=False, setting="combined"):
    """Create the exact per-object project the real Orca CLI must accept.

    Both objects are equal geometry at separated X positions, with distinct
    wall loops and infill percentages. The G-code probe must confirm *both*
    positions extrude before this route is eligible for runtime use.
    """
    source = cube_fixture_stl()
    if setting == "combined":
        settings = [
            {"wall_loops": 2, "sparse_infill_density": 15},
            {"wall_loops": 5, "sparse_infill_density": 37},
        ]
    elif setting == "wall_loops":
        settings = [{"wall_loops": 2}, {"wall_loops": 5}]
    elif setting == "sparse_infill_density":
        # An 80% difference is large enough to detect even with 20mm cubes
        # and the manufacturer's top/bottom solid layers.
        settings = [{"sparse_infill_density": 0}, {"sparse_infill_density": 80}]
    else:
        raise ValueError("Unsupported object settings acceptance fixture.")
    if reverse:
        settings.reverse()
    entries = [
        ({"x_mm": -35, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100,
          "process_overrides": settings[0]}, source),
        ({"x_mm": 35, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100,
          "process_overrides": settings[1]}, source),
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
        # Native process floats may serialise as 80.0%, not 80%. Compare
        # numerical values while requiring the correct native unit.
        high, low, key = (5, 2, "wall_loops") if setting != "sparse_infill_density" \
            else (80, 0, "sparse_infill_density")
        expected = (high, low) if reverse else (low, high)
        actual = tuple(float(row[key].removesuffix("%")) for row in values)
        if actual != expected or (key == "sparse_infill_density" and
                                 any(not row[key].endswith("%") for row in values)):
            raise ValueError("Per-object process settings were not saved correctly.")
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise ValueError("Object fixture output already exists.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    print("Created independent Orca per-object settings fixture: " + str(target))


def material_fixture(target):
    """Two independent physical models bound to native tools 0 and 1.

    Both use the same benign cube shape. Different object colours are not
    evidence of tool changes; the isolated real Orca probe must prove G-code.
    """
    source = cube_fixture_stl()
    entries = [
        ({"x_mm": -35, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100}, source),
        ({"x_mm": 35, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100}, source),
    ]
    data = build_plate_3mf(entries, bed_width=220, bed_depth=220,
                           native_tool_indices=[0, 1])
    validate_worker_3mf(data, native_tool_count=2)
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise ValueError("Material fixture output already exists.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    print("Created independent two-tool Orca 3MF acceptance fixture: " + str(target))


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
    parser.add_argument("--object-reverse-output", type=Path)
    parser.add_argument("--object-wall-output", type=Path)
    parser.add_argument("--object-wall-reverse-output", type=Path)
    parser.add_argument("--object-infill-output", type=Path)
    parser.add_argument("--object-infill-reverse-output", type=Path)
    parser.add_argument("--material-output", type=Path)
    args = parser.parse_args()
    generate(args.output)
    if args.compound_output:
        compound_preview(args.output, args.compound_output)
    if args.material_output:
        material_fixture(args.material_output)
    if args.object_output:
        object_settings_fixture(args.object_output)
    if args.object_reverse_output:
        object_settings_fixture(args.object_reverse_output, reverse=True)
    if args.object_wall_output:
        object_settings_fixture(args.object_wall_output, setting="wall_loops")
    if args.object_wall_reverse_output:
        object_settings_fixture(args.object_wall_reverse_output, reverse=True, setting="wall_loops")
    if args.object_infill_output:
        object_settings_fixture(args.object_infill_output, setting="sparse_infill_density")
    if args.object_infill_reverse_output:
        object_settings_fixture(args.object_infill_reverse_output, reverse=True,
                                setting="sparse_infill_density")


if __name__ == "__main__":
    main()
