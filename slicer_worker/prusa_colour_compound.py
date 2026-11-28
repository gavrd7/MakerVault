"""Narrow native Prusa MMU painted box-modifier plus box-cavity contract.

The signed native 3MF is the sole source of authorisation; request metadata
may not opt in to compound slicing. The pinned 2.9.7 fixture proves these
two disjoint, axis-aligned box volumes on a full-wall-painted ModelPart.
Every result is independently checked by the shared volumetric G-code audit.
"""
import math

from .runner import WorkerError
from .modifier_gcode_audit import modifier_bounds


def qualified_prusa_colour_compound(project):
    """Return True only for the pinned native three-volume layout.

    False means an existing noncompound painted project. An attempted
    compound with unknown topology, shapes, or overlapping volumes fails.
    """
    import io
    import zipfile
    from defusedxml import ElementTree as SafeET
    from .prusa_3mf_validation import CONFIG
    if not isinstance(project, bytes) or not 0 < len(project) <= 32 * 1024 * 1024:
        raise WorkerError("Invalid Prusa compound project.")
    try:
        with zipfile.ZipFile(io.BytesIO(project)) as z:
            raw = z.read(CONFIG)
        if b"<!" in raw or b"\x00" in raw:
            raise WorkerError("Unsafe Prusa compound metadata.")
        root = SafeET.fromstring(raw)
        objects = root.findall("./object")
        if len(objects) != 1:
            raise WorkerError("Prusa colour composition needs one native parent.")
        volumes = objects[0].findall("./volume")
        if len(volumes) <= 2:
            return False
        if len(volumes) != 3:
            raise WorkerError("Prusa painted compound must contain exactly two native regions.")
        roles = []
        for volume in volumes:
            metadata = volume.findall("./metadata")
            fields = {entry.get("key"): entry.get("value") for entry in metadata}
            if len(fields) != len(metadata):
                raise WorkerError("Duplicate Prusa compound volume metadata.")
            roles.append(fields)
        if (roles[0].get("volume_type") != "ModelPart" or
                {k: v for k, v in roles[0].items() if k != "volume_type"} !=
                {"extruder": "1"} or
                roles[1].get("volume_type") != "ParameterModifier" or
                set(roles[1]) != {"volume_type", "fill_density"} or
                roles[2] != {"volume_type": "NegativeVolume"}):
            raise WorkerError("Prusa compound must be one infill modifier and one cavity.")
        try:
            value = float(roles[1]["fill_density"].removesuffix("%"))
        except ValueError:
            raise WorkerError("Invalid Prusa compound infill density.") from None
        if not math.isfinite(value) or not 0 <= value <= 100:
            raise WorkerError("Prusa compound modifier density is unqualified.")
        bounds, kinds, meshes = modifier_bounds(
            project, "prusaslicer", include_meshes=True)
        if kinds != ["modifier_part", "negative_part"]:
            raise WorkerError("Prusa compound native volume order changed.")
        for box, mesh in zip(bounds, meshes):
            if len(mesh) != 12:
                raise WorkerError("Prusa compound only accepts closed native boxes.")
            coordinates = {tuple(round(v, 5) for v in point)
                           for triangle in mesh for point in triangle}
            corners = {(round(x, 5), round(y, 5), round(z, 5))
                       for x in box[0] for y in box[1] for z in box[2]}
            if (len(coordinates) != 8 or coordinates != corners or
                    any(high-low < .5 for low, high in box)):
                raise WorkerError("Prusa compound boxes must be axis-aligned.")
        if all(max(bounds[0][axis][0], bounds[1][axis][0]) <
               min(bounds[0][axis][1], bounds[1][axis][1])
               for axis in range(3)):
            raise WorkerError("Prusa painted modifier and cavity must be disjoint.")
        return True
    except WorkerError:
        raise
    except (OSError, ValueError, TypeError, KeyError, IndexError, OverflowError,
            AttributeError, zipfile.BadZipFile, SafeET.ParseError):
        raise WorkerError("Cannot verify signed Prusa compound volume layout.") from None


def audit_prusa_painted_volume_effects(data, project):
    """Audit EVERY present Prusa painted modifier/negative volume after slicing.

    The base ModelPart is not a typed modifier. A single native infill
    modifier has genuine native colour+modifier proof; the separately
    qualified two-volume route requires exactly one infill modifier plus
    one disjoint negative cavity. An absent region needs no extra scan.
    This audit runs independently in the worker and in owner-side preflight.
    """
    from .prusa_3mf_validation import CONFIG
    from .modifier_gcode_audit import audit_modifier_positive_e

    if not isinstance(project, bytes) or not 0 < len(project) <= 32 * 1024 * 1024:
        raise WorkerError("Invalid Prusa painted native region project.")
    try:
        with zipfile.ZipFile(io.BytesIO(project)) as archive:
            metadata = SafeET.fromstring(archive.read(CONFIG))
        objects = metadata.findall("./object")
        if len(objects) != 1:
            raise WorkerError("Prusa painted region audit expects one parent.")
        count = len(objects[0].findall("./volume")) - 1
    except WorkerError:
        raise
    except (OSError, ValueError, KeyError, AttributeError,
            zipfile.BadZipFile, SafeET.ParseError):
        raise WorkerError("Cannot inspect native Prusa coloured region count.") from None

    if count == 0:
        return None
    if count not in (1, 2):
        raise WorkerError("Unqualified count of Prusa painted native modifiers.")
    if count == 2 and not qualified_prusa_colour_compound(project):
        raise WorkerError("Prusa painted cavity and modifier geometry is not qualified.")
    receipt = audit_modifier_positive_e(data, project, "prusaslicer")
    if (receipt["modifier_count"] != count or
            receipt["modifier_region_paths"][0] <= 0 or
            receipt["negative_volume_count"] != (1 if count == 2 else 0) or
            any(receipt["modifier_region_paths"][i] != 0
                for i in range(1, count) if count == 2)):
        raise WorkerError(
            "Prusa coloured native modifier/cavity did not retain regional deposition.")
    return receipt
