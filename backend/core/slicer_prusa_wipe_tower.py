"""Validated Prusa 2.9.7 per-bed native 3MF wipe-tower placement.

Prusa removed wipe_tower_x/y/rotation_angle INI keys in upstream 2.9.0.
The reviewed 2.9.7 importer reads an explicit
Metadata/Prusa_Slicer_wipe_tower_information.xml member instead.

This helper never enables MMU/XL slicing or printer upload by itself.
It only accepts an already internally generated bounded Prusa project.
"""
import io
import math
import zipfile
from xml.etree import ElementTree as ET

from .slicer_profiles import SlicerProfileError

PART = "Metadata/Prusa_Slicer_wipe_tower_information.xml"
REQUIRED = frozenset({
    "3D/3dmodel.model", "Metadata/Slic3r_PE_model.config",
    "[Content_Types].xml", "_rels/.rels",
})
OPTIONAL = frozenset({"Metadata/Prusa_Slicer_layer_config_ranges.xml"})


def add_prusa_native_wipe_tower(project, *, x_mm, y_mm, rotation_deg,
                                bed_width, bed_depth):
    """Append native per-bed tower placement without mutable input presets.

    Exact printer-specific tower size and purge clearance must be checked
    separately against generated G-code; this only enforces conservative
    origin bounds and a correctly namespaced, single-bed input dialect.
    """
    if not isinstance(project, bytes) or not 0<len(project)<=32*1024*1024:
        raise SlicerProfileError("Invalid internally generated Prusa 3MF.")
    values = (x_mm,y_mm,rotation_deg,bed_width,bed_depth)
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in values):
        raise SlicerProfileError("Prusa wipe tower dimensions must be finite numbers.")
    if not 70<=bed_width<=1000 or not 60<=bed_depth<=1000:
        raise SlicerProfileError("Prusa native wipe tower needs a bounded bed.")
    if not (5<=x_mm<=bed_width-65 and 5<=y_mm<=bed_depth-45 and
            -360<=rotation_deg<=360):
        raise SlicerProfileError("Prusa wipe tower position is outside the safe plate area.")
    try:
        source=zipfile.ZipFile(io.BytesIO(project))
        with source:
            parts=source.namelist()
            if (len(parts) != len(set(parts)) or
                    not REQUIRED.issubset(parts) or
                    set(parts)-REQUIRED-OPTIONAL or
                    any(source.getinfo(part).file_size>96*1024*1024
                        for part in parts)):
                raise SlicerProfileError("Invalid native Prusa project members.")
            new=io.BytesIO()
            xml=ET.Element("wipe_tower_information",{
                "bed_idx":"0",
                "position_x":format(float(x_mm),".3f"),
                "position_y":format(float(y_mm),".3f"),
                "rotation_deg":format(float(rotation_deg),".3f"),
            })
            with zipfile.ZipFile(new,"w",compression=zipfile.ZIP_DEFLATED,
                                 allowZip64=False) as target:
                for part in parts:
                    target.writestr(part,source.read(part))
                target.writestr(PART,ET.tostring(xml,encoding="utf-8",
                                                xml_declaration=True))
    except (OSError,ValueError,zipfile.BadZipFile,RuntimeError) as exc:
        raise SlicerProfileError("Invalid generated Prusa project archive.") from exc
    output=new.getvalue()
    if len(output)>32*1024*1024:
        raise SlicerProfileError("Prusa project with wipe tower exceeds size limits.")
    return output
