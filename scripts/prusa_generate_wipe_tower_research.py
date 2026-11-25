"""Prusa 2.9.7 wipe tower position moved from INI to per-bed 3MF in 2.9.0.

Build research-only, same-model ZIP variants. Never accept arbitrary 3MF
archives or change a user's Prusa preset as a side-effect of this fixture.
"""
import io
from pathlib import Path
import sys
import zipfile
from xml.etree import ElementTree as ET


PART="Metadata/Prusa_Slicer_wipe_tower_information.xml"


def relocated_project(data, *, x, y, rotation=0):
    buffer=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        if PART in source.namelist() or len(source.namelist())>12:
            raise ValueError("Research input must be a bare reviewed Prusa project.")
        with zipfile.ZipFile(buffer,"w",compression=zipfile.ZIP_DEFLATED) as output:
            for name in source.namelist():
                output.writestr(name,source.read(name))
            root=ET.Element("wipe_tower_information",{
                "bed_idx":"0","position_x":str(x),"position_y":str(y),
                "rotation_deg":str(rotation),
            })
            output.writestr(PART,ET.tostring(root,encoding="utf-8",
                                            xml_declaration=True))
    return buffer.getvalue()


def main(model,folder):
    source=Path(model).read_bytes()
    destination=Path(folder)
    destination.mkdir(parents=True,exist_ok=True)
    for label,x in (("west",35),("east",165)):
        (destination/(label+".3mf")).write_bytes(
            relocated_project(source,x=x,y=145))


if __name__=="__main__":
    main(*sys.argv[1:])
