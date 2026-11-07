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


def compound_preview(path, target):
    """Test-only flattening: preserve two islands' XY placement as one mesh.

    This does not support per-object material assignment and is NOT selected by
    production slicing. It isolates Orca's plate-assignment behaviour.
    """
    with zipfile.ZipFile(path) as archive:
        original = ET.fromstring(archive.read("3D/3dmodel.model"))
        content_types = archive.read("[Content_Types].xml")
        relationships = archive.read("_rels/.rels")
    ns = "{" + NS + "}"
    originals = original.findall("./" + ns + "resources/" + ns + "object")
    transforms = original.findall("./" + ns + "build/" + ns + "item")
    if len(originals) != 2 or len(transforms) != 2:
        raise ValueError("Compound probe requires two model instances.")
    merged = ET.Element(ns + "model", {
        "unit": "millimeter", "{http://www.w3.org/XML/1998/namespace}lang": "en-US"
    })
    resources = ET.SubElement(merged, ns + "resources")
    composite = ET.SubElement(resources, ns + "object", {"id": "1", "type": "model"})
    mesh = ET.SubElement(composite, ns + "mesh")
    vertices = ET.SubElement(mesh, ns + "vertices")
    triangles = ET.SubElement(mesh, ns + "triangles")
    for obj, item in zip(originals, transforms):
        m = [float(value) for value in item.attrib["transform"].split()]
        if len(m) != 12:
            raise ValueError("Unexpected 3MF model transform.")
        source_vertices = obj.findall("./" + ns + "mesh/" + ns + "vertices/" + ns + "vertex")
        source_faces = obj.findall("./" + ns + "mesh/" + ns + "triangles/" + ns + "triangle")
        offset = len(vertices)
        for vertex in source_vertices:
            x, y, z = (float(vertex.attrib[key]) for key in ("x", "y", "z"))
            placed = (
                m[0] * x + m[3] * y + m[6] * z + m[9],
                m[1] * x + m[4] * y + m[7] * z + m[10],
                m[2] * x + m[5] * y + m[8] * z + m[11],
            )
            ET.SubElement(vertices, ns + "vertex", {
                axis: format(value, ".6f")
                for axis, value in zip(("x", "y", "z"), placed)
            })
        for face in source_faces:
            ET.SubElement(triangles, ns + "triangle", {
                name: str(offset + int(face.attrib[name]))
                for name in ("v1", "v2", "v3")
            })
    build = ET.SubElement(merged, ns + "build")
    ET.SubElement(build, ns + "item", {"objectid": "1"})
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise ValueError("Composite output already exists.")
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("3D/3dmodel.model", ET.tostring(merged, encoding="utf-8", xml_declaration=True))
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", relationships)
    validate_worker_3mf(target.read_bytes())
    print("Created test-only combined-mesh 3MF fixture: " + str(target))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compound-output", type=Path)
    args = parser.parse_args()
    generate(args.output)
    if args.compound_output:
        compound_preview(args.output, args.compound_output)


if __name__ == "__main__":
    main()
