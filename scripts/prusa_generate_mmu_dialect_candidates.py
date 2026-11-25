"""Generate research-only Prusa MMU 3MF projects from owned synthetic cubes.

NOT accepted by the production worker until native Prusa MMU tool changes,
filament vectors, purge and printer submission restrictions have been audited.
"""
import io
from pathlib import Path
import sys
import zipfile
from defusedxml import ElementTree as SafeET
from xml.etree import ElementTree as ET

from core.slicer_prusa_3mf import build_prusa_native_3mf
from scripts.prusa_real_binary_smoke import cube_stl


def make_variant(source, dialect):
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source)) as z, zipfile.ZipFile(output, "w",
            compression=zipfile.ZIP_DEFLATED) as target:
        for entry in z.infolist():
            raw = z.read(entry.filename)
            if entry.filename == "Metadata/Slic3r_PE_model.config":
                root = SafeET.fromstring(raw)
                for idx, obj in enumerate(root.findall("./object"), start=1):
                    if dialect in ("object", "both"):
                        ET.SubElement(obj, "metadata", {"type": "object",
                            "key": "extruder", "value": str(idx)})
                    if dialect in ("volume", "both"):
                        first = obj.find("./volume")
                        if first is None:
                            raise ValueError("Missing native object volume")
                        ET.SubElement(first, "metadata", {"type": "volume",
                            "key": "extruder", "value": str(idx)})
                raw = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            target.writestr(entry.filename, raw)
    return output.getvalue()


def main(destination):
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    source = cube_stl()
    def item(x):
        return {"asset_id": "synthetic-mm3-cube", "x_mm": x, "y_mm": 0,
                "z_mm": 0, "rotation_deg": 0, "scale_percent": 100}
    pristine = build_prusa_native_3mf([
        (item(-35), source), (item(35), source)], bed_width=250, bed_depth=210)
    for dialect in ("object", "volume", "both"):
        (root / (dialect + ".3mf")).write_bytes(make_variant(pristine, dialect))

if __name__ == "__main__":
    main(sys.argv[1])
