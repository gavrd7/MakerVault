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


def build(output_dir):
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
        "shape": "box", "width_mm": 26, "depth_mm": 26,
        "height_mm": 12, "x_mm": 0, "y_mm": 0, "z_mm": 15,
        "settings": {"sparse_infill_density": 50},
    }
    baseline = build_plate_3mf([(parent, source)], bed_width=220, bed_depth=220)
    altered = export_modifier_3mf_fixture(
        [({**parent, "modifier_volumes": [modifier]}, source)],
        bed_width=220, bed_depth=220,
    )
    for name, blob in (("baseline.3mf", baseline), ("modified.3mf", altered)):
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            root = ET.fromstring(archive.read("3D/3dmodel.model"))
            items = root.findall(f"./{{{NS}}}build/{{{NS}}}item")
            if len(items) != 1 or items[0].attrib.get("objectid") != "1":
                raise ValueError("Modifier acceptance fixture must build exactly one parent model.")
        (target / name).write_bytes(blob)
    with zipfile.ZipFile(io.BytesIO(altered)) as archive:
        manifest = ET.fromstring(archive.read("Metadata/model_settings.config"))
        if len(manifest.findall("object/part[@subtype='modifier_part']")) != 1:
            raise ValueError("Native modifier metadata was not attached to the parent.")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print("Generated offline modifier A/B fixture:", build(args.output_dir))


if __name__ == "__main__":
    main()
