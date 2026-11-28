"""Native Prusa 2.9.7 full-plate independent seam-paint acceptance inputs."""
import json
from pathlib import Path
import sys

from core.slicer_prusa_3mf import build_prusa_native_3mf
from scripts.prusa_real_binary_smoke import cube_stl


def main(destination, paint_directory):
    folder=Path(destination)
    folder.mkdir(parents=True,exist_ok=True)
    source=cube_stl()
    painted_root=Path(paint_directory)
    front=json.loads((painted_root/"seam-front.json").read_text())["seam_paint"]
    back=json.loads((painted_root/"seam-back.json").read_text())["seam_paint"]
    for name,selected in (("baseline",{}),("one",{7:front}),
                          ("two",{7:front,8:back})):
        rows=[]
        for index,(x,y) in enumerate(
                (pos for ypos in (-55,0,55) for pos in
                 ((x,ypos) for x in (-90,-45,0,45,90)))):
            item={"asset_id":f"seam-{index}",
                  "x_mm":x,"y_mm":y,"z_mm":0,
                  "rotation_deg":0,"scale_percent":100}
            if index in selected:
                item["seam_paint"]=selected[index]
            rows.append((item,source))
        project=build_prusa_native_3mf(rows,bed_width=250,bed_depth=210)
        (folder/(name+".3mf")).write_bytes(project)
        (folder/(name+".json")).write_text(json.dumps(
            [item for item,_raw in rows]))


if __name__=="__main__":
    main(*sys.argv[1:])
