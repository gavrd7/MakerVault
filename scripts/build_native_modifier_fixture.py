"""Build an offline, single-object native modifier A/B fixture for real CLI tests.

No stored MakerVault records, printer communication, network or fixture approval.
"""
import argparse
import io
from pathlib import Path
import sys
import uuid
import zipfile
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from core.slicer_modifier_3mf import export_modifier_3mf_fixture
from core.slicer_plate_3mf import build_plate_3mf, NS
from scripts.build_slicer_multimodel_fixture import cube_fixture_stl


def build(output_dir, *, shape="box", world_pose=False):
    if shape not in {"box", "cylinder", "sphere", "cone", "disc", "torus"}:
        raise ValueError("Unsupported primitive test shape.")
    target = Path(output_dir)
    if target.is_symlink() or (target.exists() and any(target.iterdir())):
        raise ValueError("Modifier fixture target must be an empty directory.")
    target.mkdir(parents=True, exist_ok=True)
    source = cube_fixture_stl(30)
    parent = {
        "x_mm": 0, "y_mm": 0, "z_mm": 0, "rotation_deg": 0,
        "scale_percent": 100, "process_overrides": {"wall_loops": 2},
    }
    modifier = {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "makervault-modifier-acceptance")),
        "shape": shape, "width_mm": 26, "depth_mm": 26,
        "height_mm": 12, "x_mm": 0, "y_mm": 0, "z_mm": 15,
        "settings": {"sparse_infill_density": 50},
    }
    if world_pose:
        modifier.update({
            "coordinate_space": "world",
            "rotation_xyz_deg": [12, -8, 35],
            "scale_xyz_percent": [110, 90, 105],
        })
    lower = {
        **modifier, "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "makervault-modifier-lower")),
        "z_mm": 6,
    }
    baseline = build_plate_3mf([(parent, source)], bed_width=220, bed_depth=220)
    cases = {
        "baseline.3mf": baseline,
        "modified.3mf": export_modifier_3mf_fixture(
            [({**parent, "modifier_volumes": [modifier]}, source)],
            bed_width=220, bed_depth=220),
        "lower.3mf": export_modifier_3mf_fixture(
            [({**parent, "modifier_volumes": [lower]}, source)],
            bed_width=220, bed_depth=220),
        "both.3mf": export_modifier_3mf_fixture(
            [({**parent, "modifier_volumes": [modifier, lower]}, source)],
            bed_width=220, bed_depth=220),
    }
    for name, blob in cases.items():
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            root = ET.fromstring(archive.read("3D/3dmodel.model"))
            items = root.findall(f"./{{{NS}}}build/{{{NS}}}item")
            if len(items) != 1 or items[0].attrib.get("objectid") != "1":
                raise ValueError("Modifier acceptance fixture must build exactly one parent model.")
        (target / name).write_bytes(blob)
    for name, expected in (("modified.3mf", 1), ("lower.3mf", 1), ("both.3mf", 2)):
        with zipfile.ZipFile(io.BytesIO(cases[name])) as archive:
            manifest = ET.fromstring(archive.read("Metadata/model_settings.config"))
            if len(manifest.findall("object/part[@subtype='modifier_part']")) != expected:
                raise ValueError("Native modifier metadata was not attached to the parent.")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--shape", choices=("box", "cylinder", "sphere", "cone", "disc", "torus"), default="box")
    parser.add_argument("--world-pose", action="store_true",
                        help="Independent tilted, rotated, anisotropically scaled plate-space modifier")
    args = parser.parse_args()
    print("Generated offline baseline, reversed and paired modifier fixtures:", build(args.output_dir, shape=args.shape, world_pose=args.world_pose))


if __name__ == "__main__":
    main()
