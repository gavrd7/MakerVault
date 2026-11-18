"""Creality native 3MF placement-preservation preparation (not yet CLI-enabled).

Creality Print 7.3.1 requires embedded printer/process/filament config for
3MF project slicing; passing --load-settings or --load-filaments alongside a
project returns CLI_INVALID_PARAMS. This module prepares and verifies exact
MakerVault model placements before a separately verified profile packager.
"""
import io
import math
import zipfile
from defusedxml import ElementTree as SafeET

from .slicer_plate_3mf import build_plate_3mf, NS
from .slicer_profiles import SlicerProfileError

_MAX_PROJECT = 32 * 1024 * 1024


def build_creality_positioned_plate(source_models, *, bed_width, bed_depth, tool_ids):
    """Return core 3MF with baked positions and per-object logical filament IDs.

    Input tools are zero-based, checked against the assigned palette. This is
    an intermediate geometry package, NOT a self-contained Creality project.
    Never send it to Creality's CLI before embedding verified native presets.
    """
    if (not isinstance(source_models, (list, tuple)) or
            not 2 <= len(source_models) <= 12 or
            not isinstance(tool_ids, (list, tuple)) or
            len(tool_ids) != len(source_models) or
            any(type(v) is not int or v not in (0, 1) for v in tool_ids) or
            set(tool_ids) != {0, 1}):
        raise SlicerProfileError("Creality positioned two-material plate has invalid assignments.")
    data = build_plate_3mf(
        list(source_models), bed_width=bed_width, bed_depth=bed_depth,
        native_tool_indices=list(tool_ids))
    if len(data) > _MAX_PROJECT:
        raise SlicerProfileError("Creality positioned plate exceeds the project limit.")
    ns = "{" + NS + "}"
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            model = SafeET.fromstring(archive.read("3D/3dmodel.model"))
            settings = SafeET.fromstring(archive.read("Metadata/model_settings.config"))
    except (KeyError, ValueError, OSError, zipfile.BadZipFile) as exc:
        raise SlicerProfileError("Creality positioned 3MF archive is incomplete.") from exc
    objects = model.findall("./" + ns + "resources/" + ns + "object")
    instances = model.findall("./" + ns + "build/" + ns + "item")
    settings_objects = settings.findall("object")
    if len(objects) != len(tool_ids) or len(instances) != len(tool_ids) or len(settings_objects) != len(tool_ids):
        raise SlicerProfileError("Creality positioned plate lost model identity.")
    for index, (obj, instance, record, tool) in enumerate(
            zip(objects, instances, settings_objects, tool_ids), 1):
        if obj.attrib.get("id") != str(index) or instance.attrib.get("objectid") != str(index):
            raise SlicerProfileError("Creality positioned plate has mismatched object identities.")
        if record.attrib.get("id") != str(index):
            raise SlicerProfileError("Creality positioned material metadata is misaligned.")
        extruders = [row.attrib.get("value") for row in record.findall("metadata")
                     if row.attrib.get("key") == "extruder"]
        if extruders != [str(tool + 1)]:
            raise SlicerProfileError("Creality positioned plate lost filament assignment.")
        if instance.attrib.get("transform") != "1 0 0 0 1 0 0 0 1 0 0 0":
            raise SlicerProfileError("Creality project positions must be baked into the mesh.")
        vertices = obj.findall("./" + ns + "mesh/" + ns + "vertices/" + ns + "vertex")
        if not vertices:
            raise SlicerProfileError("Creality positioned plate contains an empty model.")
        xs = [float(v.attrib["x"]) for v in vertices]
        ys = [float(v.attrib["y"]) for v in vertices]
        if (not all(math.isfinite(v) for v in xs + ys) or
                min(xs) < -1e-5 or max(xs) > bed_width + 1e-5 or
                min(ys) < -1e-5 or max(ys) > bed_depth + 1e-5):
            raise SlicerProfileError("Creality positioned model exceeds the printable bed.")
    return data
