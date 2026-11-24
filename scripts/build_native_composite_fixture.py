"""Disposable two-model native region fixtures for exact-binary CLI acceptance."""
import argparse
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
from core.slicer_modifier_3mf import export_modifier_3mf_fixture
from core.slicer_plate_3mf import build_plate_3mf
from scripts.build_slicer_multimodel_fixture import cube_fixture_stl


def build(output_dir):
    output = Path(output_dir)
    if output.is_symlink() or (output.exists() and any(output.iterdir())):
        raise ValueError("Fixture target must be an empty directory.")
    output.mkdir(parents=True, exist_ok=True)
    model = cube_fixture_stl(30)
    def base(x):
        return {"instance_id":str(uuid.uuid4()), "asset_id":str(uuid.uuid4()),
                "x_mm":x, "y_mm":0, "z_mm":0, "rotation_deg":0,
                "scale_percent":100, "color":"#00aaff", "modifier_volumes":[]}
    first, second = base(-20), base(20)
    volumes = {
        "region": {"id":str(uuid.uuid4()),"shape":"box",
                   "width_mm":94,"depth_mm":24,"height_mm":12,
                   "x_mm":0,"y_mm":0,"z_mm":15,"coordinate_space":"world",
                   "rotation_xyz_deg":[0,0,0],"scale_xyz_percent":[100,100,100],
                   "kind":"modifier","assembly_id":None,
                   "settings":{"sparse_infill_density":60}},
        "negative": {"id":str(uuid.uuid4()),"shape":"box",
                     "width_mm":94,"depth_mm":20,"height_mm":12,
                     "x_mm":0,"y_mm":0,"z_mm":15,"coordinate_space":"world",
                     "rotation_xyz_deg":[0,0,0],"scale_xyz_percent":[100,100,100],
                     "kind":"negative","assembly_id":None,"settings":{}},
    }
    # The baseline is itself a native two-printable assembly; a neutral 15%
    # region keeps a single real 3MF build object across all three engines,
    # including the Creality external-object loader.
    neutral={**volumes["region"],"id":str(uuid.uuid4()),
             "settings":{"sparse_infill_density":15}}
    (output/"baseline.3mf").write_bytes(export_modifier_3mf_fixture(
        [({**first,"modifier_volumes":[neutral]},model),(second,model)],
        bed_width=220,bed_depth=220))
    for label,volume in volumes.items():
        selected={**first,"modifier_volumes":[volume]}
        (output/(label+".3mf")).write_bytes(
            export_modifier_3mf_fixture([(selected,model),(second,model)],
                                        bed_width=220,bed_depth=220))
    # Isolate Bambu CLI negative-volume behaviour on a single printable.
    # This is diagnostic only: it never changes native production approvals.
    (output/"single-baseline.3mf").write_bytes(build_plate_3mf(
        [(first, model)],bed_width=220,bed_depth=220))
    (output/"single-negative.3mf").write_bytes(export_modifier_3mf_fixture(
        [({**first,"modifier_volumes":[volumes["negative"]]},model)],
        bed_width=220,bed_depth=220))
    return output


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",required=True,type=Path)
    print("Generated native composite G-code fixtures:",build(parser.parse_args().output_dir))
