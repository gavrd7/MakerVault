"""Generate reviewed Prusa 2.9.7 native per-bed tower placement fixtures.

Research uses the exact same bounded backend serializer that future MMU
routing will use, while ordinary production MMU admission stays disabled.
"""
from pathlib import Path
import sys

from core.slicer_prusa_wipe_tower import add_prusa_native_wipe_tower


def main(model, folder):
    source=Path(model).read_bytes()
    destination=Path(folder)
    destination.mkdir(parents=True,exist_ok=True)
    for label,x in (("west",35),("east",165)):
        result=add_prusa_native_wipe_tower(
            source,x_mm=x,y_mm=145,rotation_deg=0,
            bed_width=250,bed_depth=210)
        (destination/(label+".3mf")).write_bytes(result)


if __name__=="__main__":
    main(*sys.argv[1:])
