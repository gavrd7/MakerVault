"""Isolated, offline multi-filament test preparation for Orca.

The selected printer adapter must publish material architecture evidence.
This intentionally does NOT establish firmware changeover support or allow
printer transfer. Preview/painted facets require an independent integration.
"""
from .models import PrinterConnection, SlicerProfile
from .slicer_colour_painting import validate_colour_paint
from .slicer_material_routing import (
    MaterialRoutingError, detect_material_system, derive_native_tool_order,
)
from .slicer_native_material_palette import (
    ordered_material_profile_ids, prepare_multimaterial_plate,
)


def plan_native_multimaterial(job):
    settings = job.settings or {}
    objects = settings.get("plate_objects") or []
    if job.engine != "orcaslicer" or not 1 <= len(objects) <= 12:
        raise MaterialRoutingError("Multi-colour test slicing requires an Orca model.")
    if settings.get("flush_settings") is not None:
        raise MaterialRoutingError(
            "Custom purge settings are not verified for multi-colour test slicing."
        )
    if any(not isinstance(item, dict) for item in objects):
        raise MaterialRoutingError("Multi-colour models are invalid.")
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
    topology = detect_material_system(connections)
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
    preferred = primary_slots & assigned
    if not preferred:
        raise MaterialRoutingError(
            "Assign your main native filament preset to at least one selected model."
        )
    bindings = derive_native_tool_order(
        objects, printer_id=job.printer_id, topology=topology,
        preferred_slot_id=sorted(preferred)[0],
        painted_slot_ids=painted_slot_ids,
    )
    rows = [{"slot_id": slot_id, "tool_index": index}
            for slot_id, index in bindings.items()]
    profile_ids = ordered_material_profile_ids(
        rows, profile_rows, main_profile_id=job.filament_profile_id,
    )
    profiles = SlicerProfile.objects.filter(
        owner_id=job.owner_id, pk__in=profile_ids, kind="filament",
    )
    by_id = {str(profile.pk): profile for profile in profiles}
    if len(by_id) != len(set(str(pk) for pk in profile_ids)):
        raise MaterialRoutingError("One or more native material presets were removed.")
    palette = tuple(by_id[str(profile_id)] for profile_id in profile_ids)
    if any(profile.status != "verified"
           or profile.engine != job.engine
           or profile.engine_version != job.engine_version
           for profile in palette):
        raise MaterialRoutingError("An assigned native filament preset is not verified for Orca.")
    return topology, bindings, palette


def prepare_job_multimaterial(job, source_models, *, bed_width, bed_depth):
    topology, bindings, profiles = plan_native_multimaterial(job)
    result = prepare_multimaterial_plate(
        source_models, bed_width=bed_width, bed_depth=bed_depth,
        printer_id=job.printer_id, owner_id=job.owner_id,
        engine=job.engine, engine_version=job.engine_version,
        topology=topology, tool_bindings=bindings,
        native_filament_profiles=profiles,
    )
    return result
