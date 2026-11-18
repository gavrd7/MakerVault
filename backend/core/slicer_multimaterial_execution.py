"""Isolated, offline multi-filament preparation for Orca and Creality.

The selected printer adapter must publish material architecture evidence.
This intentionally does NOT establish firmware changeover support or allow
printer transfer. Preview/painted facets require an independent integration.
"""
from .models import PrinterConnection, SlicerProfile
from .slicer_colour_painting import validate_colour_paint
from .slicer_material_routing import (
    MaterialRoutingError, offline_material_system, derive_native_tool_order,
)
from .slicer_native_material_palette import (
    ordered_material_profile_ids, prepare_multimaterial_plate,
)


def plan_native_multimaterial(job, *, settings=None):
    settings = (job.settings or {}) if settings is None else settings
    objects = settings.get("plate_objects") or []
    if job.engine not in {"orcaslicer", "crealityprint"} or not 1 <= len(objects) <= 12:
        raise MaterialRoutingError("Multi-colour test slicing requires an Orca model.")
    if any(not isinstance(item, dict) for item in objects):
        raise MaterialRoutingError("Multi-colour models are invalid.")
    if job.engine == "crealityprint" and any(
        (item.get("colour_paint") or {}).get("regions") or
        (item.get("colour_paint") or {}).get("faces")
        for item in objects
    ):
        raise MaterialRoutingError(
            "Creality Print colour painting requires native 3MF integration.")
    # Colour painting is now converted to Orca's native per-triangle
    # paint_color states by prepare_multimaterial_plate. This remains an
    # offline test; no G-code may be submitted to a printer.
    painted_slot_ids = []
    for item in objects:
        painting = item.get("colour_paint") or {}
        if not (painting.get("regions") or painting.get("faces")):
            continue
        validated = validate_colour_paint(painting)
        if validated["version"] != 2:
            raise MaterialRoutingError(
                "Legacy whole-face colour painting needs surface-region conversion.")
        for region in validated["regions"]:
            swatch = validated["palette"][region["slot"]]
            slot_id = swatch.get("slot_id")
            if str(swatch.get("printer_id")) != str(job.printer_id) or not slot_id:
                raise MaterialRoutingError(
                    "Each painted colour must be assigned to a slot on the selected printer.")
            if slot_id not in painted_slot_ids:
                painted_slot_ids.append(slot_id)
    connections = PrinterConnection.objects.filter(
        printer_id=job.printer_id, enabled=True,
    )
    topology = offline_material_system(connections, printer=getattr(job, "printer", None))
    profile_rows = settings.get("slot_filament_profiles") or []
    primary_slots = {
        row.get("slot_id") for row in profile_rows
        if isinstance(row, dict)
        and str(row.get("profile_id")) == str(job.filament_profile_id)
    }
    assigned = {
        item["material_slot"]["slot_id"]
        for item in objects if isinstance(item.get("material_slot"), dict)
        and isinstance(item["material_slot"].get("slot_id"), str)
    }
    preferred = primary_slots & (assigned | set(painted_slot_ids))
    if job.engine == "crealityprint":
        # Creality multi-STL has explicit, per-model slot presets. A global
        # setup filament may be different and must not override the assigned
        # model's actual material. Tool 0 follows the first model, not a CFS
        # bay index or an unrelated globally selected profile.
        first_slot = objects[0].get("material_slot")
        if not isinstance(first_slot, dict) or first_slot.get("slot_id") not in assigned:
            raise MaterialRoutingError("Assign a filament slot to the first Creality model.")
        preferred_slot = first_slot["slot_id"]
    else:
        if not preferred:
            raise MaterialRoutingError(
                "Assign your main native filament preset to at least one selected model."
            )
        preferred_slot = sorted(preferred)[0]
    bindings = derive_native_tool_order(
        objects, printer_id=job.printer_id, topology=topology,
        preferred_slot_id=preferred_slot,
        painted_slot_ids=painted_slot_ids,
    )
    rows = [{"slot_id": slot_id, "tool_index": index}
            for slot_id, index in bindings.items()]
    # The printer may have 4+ loaded filaments while a plate uses only two.
    # Demand a profile for every used tool but do not confuse unrelated
    # installed bay presets with slicer-native tools.
    used_profile_rows = [row for row in profile_rows
                         if isinstance(row, dict) and row.get("slot_id") in bindings]
    if job.engine == "crealityprint":
        first_profile = next(
            (row["profile_id"] for row in used_profile_rows
             if row.get("slot_id") == preferred_slot), None
        )
        if first_profile is None:
            raise MaterialRoutingError(
                "The first assigned Creality model needs a native filament preset."
            )
    else:
        first_profile = job.filament_profile_id
    profile_ids = ordered_material_profile_ids(
        rows, used_profile_rows, main_profile_id=first_profile,
    )
    profiles = SlicerProfile.objects.filter(
        owner_id=job.owner_id, pk__in=profile_ids, kind="filament",
    )
    by_id = {str(profile.pk): profile for profile in profiles}
    if len(by_id) != len(set(str(pk) for pk in profile_ids)):
        raise MaterialRoutingError("One or more native material presets were removed.")
    palette = tuple(by_id[str(profile_id)] for profile_id in profile_ids)
    if any(profile.kind != "filament"
           or profile.status not in {"candidate", "verified"}
           or profile.engine != job.engine
           or profile.engine_version != job.engine_version
           for profile in palette):
        raise MaterialRoutingError("An assigned filament preset is incompatible with the selected slicing engine.")
    # Manual worker fixture approval is not required. Resolve each candidate
    # from its owned, hash-checked source and complete parent lineage before
    # it reaches the isolated native tool palette.
    from .slicer_native_resolution import resolved_native_profile
    from .slicer_profiles import SlicerProfileError
    try:
        for profile in palette:
            resolved_native_profile(profile)
    except (SlicerProfileError, ValueError, OSError) as exc:
        raise MaterialRoutingError(
            "An assigned filament preset is invalid, has changed or is missing native parents: "
            + str(exc)) from exc
    return topology, bindings, palette


def prepare_job_multimaterial(job, source_models, *, bed_width, bed_depth):
    if job.engine != "orcaslicer":
        raise MaterialRoutingError("Orca native 3MF preparation cannot be used for Creality Print.")
    topology, bindings, profiles = plan_native_multimaterial(job)
    result = prepare_multimaterial_plate(
        source_models, bed_width=bed_width, bed_depth=bed_depth,
        printer_id=job.printer_id, owner_id=job.owner_id,
        engine=job.engine, engine_version=job.engine_version,
        topology=topology, tool_bindings=bindings,
        native_filament_profiles=profiles,
    )
    # Internal execution metadata: never a firmware-side slot mapping.
    result["tool_bindings"] = bindings
    return result


def prepare_creality_multistl(job, source_models):
    """Stage a two-STL Creality offline test with the existing CFS-neutral map.

    Creality's multi-STL CLI arranges its own geometry. This explicitly
    acknowledges auto-arrangement; it must not silently discard MakerVault
    placement while presenting the result as an exact interactive plate.
    """
    settings = job.settings or {}
    if job.engine != "crealityprint" or settings.get("creality_auto_arrange_offline") is not True:
        raise MaterialRoutingError(
            "Creality multi-STL slicing requires explicit offline auto-arrangement.")
    if not isinstance(source_models, list) or len(source_models) != 2:
        raise MaterialRoutingError("Creality offline material test requires exactly two STLs.")
    objects = settings.get("plate_objects") or []
    if len(objects) != len(source_models):
        raise MaterialRoutingError("Creality native model list does not match the draft.")
    for index, (item, raw) in enumerate(source_models):
        if item != objects[index] or not isinstance(raw, bytes) or not raw:
            raise MaterialRoutingError("Creality native STL identity is invalid.")
        if (item.get("process_overrides") or
            (item.get("support_paint") or {}).get("regions") or
            (item.get("seam_paint") or {}).get("regions") or
            (item.get("fuzzy_skin_paint") or {}).get("regions") or
            (item.get("colour_paint") or {}).get("regions") or
            (item.get("colour_paint") or {}).get("faces") or
            (item.get("variable_layer_profile") or {}).get("bands")):
            raise MaterialRoutingError(
                "Creality offline STL mode does not support painted or per-object overrides.")
        import math
        angles = item.get("rotation_xyz_deg", [0, 0])
        scales = item.get("scale_xyz_percent", [100, 100, 100])
        if (not isinstance(angles, (list, tuple)) or len(angles) not in (2, 3)
                or not isinstance(scales, (list, tuple)) or len(scales) != 3):
            raise MaterialRoutingError("Creality STL transformation is malformed.")
        try:
            rotation = [float(item.get("rotation_deg", 0)), *map(float, angles)]
            size = [float(item.get("scale_percent", 100)), *map(float, scales)]
            z = float(item.get("z_mm", 0))
        except (TypeError, ValueError):
            raise MaterialRoutingError("Creality STL transformation is invalid.") from None
        if (not all(math.isfinite(v) for v in [*rotation, *size, z])
                or any(abs(v) > 1e-6 for v in rotation)
                or any(abs(v - 100) > 1e-6 for v in size)
                or abs(z) > 1e-6):
            raise MaterialRoutingError(
                "Creality multi-STL auto-arrangement cannot preserve transformed models.")
    topology, bindings, profiles = plan_native_multimaterial(job)
    from .slicer_native_resolution import resolved_native_profile
    model_tools = [bindings[item["material_slot"]["slot_id"]] + 1
                   for item, _raw in source_models]
    if len(set(model_tools)) != 2:
        raise MaterialRoutingError("Two distinct Creality logical filaments are required.")
    palette = tuple(resolved_native_profile(profile) for profile in profiles)
    return {
        "model_stls": tuple(raw for _item, raw in source_models),
        "tool_ids": tuple(model_tools),
        "filament_profiles": palette,
        "tool_bindings": bindings,
        "topology": topology,
        "expected_tools": set(tool - 1 for tool in model_tools),
    }
