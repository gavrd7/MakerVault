"""Wrap disposable two-model native region cases in pinned Creality project format."""
import argparse
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"backend"),str(ROOT)]
from core.slicer_creality_modifier_project import build_creality_modifier_native_project
from slicer_worker.creality_modifier_validation import validate_creality_modifier_project


def build(fixtures):
    base=Path(fixtures)
    profiles=[(base/(kind+".json")).read_bytes() for kind in ("printer","process","filament")]
    for name in ("baseline","region","negative"):
        source=base/(name+".3mf")
        destination=base/("native-"+name+".3mf")
        if source.is_symlink() or not source.is_file() or destination.exists():
            raise ValueError("Unsafe native composite fixture path.")
        result=build_creality_modifier_native_project(
            source.read_bytes(),printer=profiles[0],process=profiles[1],
            filament=profiles[2],version="7.3.1",
            bed_width=220,bed_depth=220,
            label=uuid.uuid5(uuid.NAMESPACE_URL,"composite-"+name))
        validate_creality_modifier_project(result)
        destination.write_bytes(result)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures",type=Path,required=True)
    build(parser.parse_args().fixtures)
    print("Packaged disposable native Creality composite acceptance cases.")
