"""Owner-bound workbench adapter for qualified offline Prusa MMU/XL G-code.

This module deliberately never infers a native tool from a physical feeder slot.
It accepts only a complete explicitly ordered palette and simple independent
models, then delegates to the already authenticated and audited Prusa worker.
No printer submission, physical toolchange or multi-material painting.
"""
from .models import SlicerProfile
from .slicer_bed_dimensions import trusted_plate_dimensions
from .slicer_prusa_machine_topology import prusa_machine_topology
from .slicer_prusa_native_resolution import resolved_prusa_profile
from .slicer_prusa_material_preflight import (
    slice_prusa_offline_mmu_candidate, slice_prusa_offline_xl_candidate,
)
from .slicer_profiles import SlicerProfileError


def _virtual_native_tools(job, settings, objects, kind, count):
    """Resolve browser-assigned native tools without physical feeder telemetry."""
    from .slicer_prusa_tool_configuration import validate_prusa_native_tools
    config = validate_prusa_native_tools(settings["prusa_native_tools"])
    expected = "mmu" if kind == "single_nozzle_changer" else "xl"
    if config["mode"] != expected or config["tool_count"] != count:
        raise SlicerProfileError("Native Prusa profile and selected tool architecture disagree.")
    if (settings.get("material_tool_bindings") or settings.get("slot_filament_profiles")
            or settings.get("flush_settings")
            or any(row.get("material_slot") for row in objects)):
        raise SlicerProfileError("Clear physical feeder assignments before using Prusa virtual tools.")
    ids = config["filament_profile_ids"]
    if any(not value for value in ids):
        raise SlicerProfileError("Choose a native Prusa filament profile for every tool.")
    by_id = {str(row.pk):row for row in SlicerProfile.objects.filter(
        owner_id=job.owner_id, pk__in=ids, kind="filament",
        engine="prusaslicer", engine_version="2.9.7")}
    if set(ids) - set(by_id):
        raise SlicerProfileError("A selected Prusa filament is not owned or has been deleted.")
    filaments = [by_id[value] for value in ids]
    if str(job.filament_profile_id) not in ids:
        raise SlicerProfileError("The Setup filament must be among selected Prusa tool profiles.")
    for profile in filaments:
        if (profile.owner_id != job.owner_id or profile.engine != "prusaslicer"
                or profile.engine_version != "2.9.7" or profile.kind != "filament"):
            raise SlicerProfileError("Invalid Prusa native filament ownership or version.")
    selected = config["model_tools"]
    if len(selected) != len(objects):
        raise SlicerProfileError("Assign an explicit Prusa tool to every printable object.")
    mapping = {row["instance_id"]:row["tool"] for row in selected}
    if set(mapping) != {str(row.get("instance_id")) for row in objects}:
        raise SlicerProfileError("Prusa tool selections do not match active model identities.")
    tools = [mapping[str(row["instance_id"])] for row in objects]
    if len(set(tools)) < 2:
        raise SlicerProfileError("Prusa offline slicing requires two distinct native tools.")
    width, depth = trusted_plate_dimensions(job.printer_profile)
    result = {
        "owner_id":job.owner_id, "printer_profile":job.printer_profile,
        "process_profile":job.process_profile, "filament_profiles":filaments,
        "tools":tools, "bed_width":width, "bed_depth":depth,
    }
    if expected == "mmu":
        tower = settings.get("prime_tower")
        matrix = config["purge_matrix"]
        if (not isinstance(tower, dict) or set(tower) != {"x", "y"} or
                any(value is None for row in matrix for value in row)):
            raise SlicerProfileError("Complete MMU purge volumes and choose a native wipe tower.")
        result.update(purge_matrix=matrix, tower_xy=(tower["x"],tower["y"]))
    elif settings.get("prime_tower") is not None:
        raise SlicerProfileError("Independent Prusa XL heads do not use an MMU wipe tower.")
    return expected,result


def prepare_prusa_workbench_material(job, *, settings=None):
    """Resolve a full owner-scoped selection before loading any model bytes.

    The UI stores native bindings as zero-based tool indices and 3MF extruders
    as one-based indices. Physical slot_index is never an extruder number.
    """
    settings = (job.settings or {}) if settings is None else settings
    if (job.engine != "prusaslicer" or job.engine_version != "2.9.7" or
            settings.get("multi_material_test") is not True):
        raise SlicerProfileError("A verified Prusa offline material job is required.")
    if not getattr(job, "printer_profile_id", None) or not getattr(job, "process_profile_id", None):
        raise SlicerProfileError("Prusa multi-material slicing requires owned native printer and process profiles.")
    for profile, kind in ((job.printer_profile, "printer"),
                          (job.process_profile, "process")):
        if (profile is None or profile.owner_id != job.owner_id or
                profile.engine != "prusaslicer" or profile.engine_version != "2.9.7"
                or profile.kind != kind):
            raise SlicerProfileError("Prusa native printer and process profiles do not match.")
    printer = resolved_prusa_profile(job.printer_profile)
    topology = prusa_machine_topology(printer)
    count = topology["logical_tool_count"]
    if topology["requires_new_toolchanger_qualification"] or not 2 <= count <= 5:
        raise SlicerProfileError("This Prusa toolchanger has not been qualified.")
    kind = topology["kind"]
    expected = ("single_nozzle_changer" if kind == "single_nozzle_changer"
                else "independent_toolheads" if kind == "independent_tools" else None)
    if settings.get("prusa_native_tools") is None and settings.get("material_topology") != expected:
        raise SlicerProfileError("Select the matching native Prusa material topology.")

    objects = settings.get("plate_objects")
    if not isinstance(objects, list) or not 2 <= len(objects) <= 5:
        raise SlicerProfileError("Prusa offline materials require two to five models.")
    plates = settings.get("plates")
    if plates is not None:
        if not isinstance(plates, list) or not isinstance(settings.get("active_plate_id"), str):
            raise SlicerProfileError("Prusa active plate metadata is invalid.")
        selected = [plate for plate in plates if isinstance(plate, dict)
                    and plate.get("id") == settings["active_plate_id"]]
        if (len(selected) != 1 or selected[0].get("objects") != objects
                or selected[0].get("volumes")
                or selected[0].get("prime_tower") != settings.get("prime_tower")):
            raise SlicerProfileError("Prusa active plate, models and tower must match saved project.")
    forbidden = ("modifier_volumes", "process_overrides", "colour_paint",
                 "support_paint", "seam_paint", "fuzzy_skin_paint",
                 "variable_layer_profile", "negative_volumes")
    for row in objects:
        if not isinstance(row, dict) or any(row.get(key) for key in forbidden):
            raise SlicerProfileError("Prusa multi-material models cannot combine unqualified edits.")
        if row.get("z_mm", 0) != 0 or row.get("text_model"):
            raise SlicerProfileError("Prusa offline materials require non-elevated STL models.")
    if (settings.get("process_overrides") or settings.get("plate_volumes") or
            settings.get("creality_auto_arrange_offline")):
        raise SlicerProfileError("Unqualified global settings or independent volumes cannot be dropped.")

    if settings.get("prusa_native_tools") is not None:
        return _virtual_native_tools(job, settings, objects, kind, count)

    routes = settings.get("material_tool_bindings")
    selections = settings.get("slot_filament_profiles")
    if not isinstance(routes, list) or len(routes) != count or not isinstance(selections, list) or len(selections) != count:
        raise SlicerProfileError("Assign every native tool a unique slot and filament preset.")
    by_slot = {}
    seen_tools = set()
    for route in routes:
        if (not isinstance(route, dict) or set(route) != {"slot_id", "tool_index"}
                or type(route["tool_index"]) is not int
                or not 0 <= route["tool_index"] < count
                or not isinstance(route["slot_id"], str)
                or not route["slot_id"] or route["slot_id"] in by_slot
                or route["tool_index"] in seen_tools):
            raise SlicerProfileError("Invalid or duplicated Prusa native material binding.")
        by_slot[route["slot_id"]] = route["tool_index"]
        seen_tools.add(route["tool_index"])
    if seen_tools != set(range(count)):
        raise SlicerProfileError("Prusa native tool indices must be contiguous.")
    chosen = {}
    for entry in selections:
        if (not isinstance(entry, dict) or set(entry) != {"slot_id", "profile_id"}
                or entry["slot_id"] not in by_slot or entry["slot_id"] in chosen):
            raise SlicerProfileError("Prusa selected filament mapping is incomplete.")
        chosen[entry["slot_id"]] = entry["profile_id"]
    if set(chosen) != set(by_slot):
        raise SlicerProfileError("Prusa needs a filament preset for each native tool.")

    ids = list(chosen.values())
    profiles = SlicerProfile.objects.filter(
        owner_id=job.owner_id, pk__in=ids, kind="filament",
        engine="prusaslicer", engine_version="2.9.7",
    )
    owned = {str(profile.pk): profile for profile in profiles}
    if len(owned) != len(set(str(v) for v in ids)):
        raise SlicerProfileError("A selected native filament preset is unavailable.")
    ordered = [None] * count
    for slot, tool in by_slot.items():
        profile = owned.get(str(chosen[slot]))
        if (profile is None or profile.owner_id != job.owner_id or
                profile.engine != "prusaslicer" or profile.engine_version != "2.9.7"
                or profile.kind != "filament"):
            raise SlicerProfileError("A selected native filament preset is not owned.")
        ordered[tool] = profile
    if job.filament_profile_id not in {p.pk for p in ordered}:
        raise SlicerProfileError("Selected primary filament must match an assigned Prusa tool.")

    tools = []
    for item in objects:
        slot = item.get("material_slot")
        if (not isinstance(slot, dict) or
                str(slot.get("printer_id")) != str(job.printer_id) or
                slot.get("slot_id") not in by_slot):
            raise SlicerProfileError("Every Prusa model needs an explicit selected-printer tool binding.")
        tools.append(by_slot[slot["slot_id"]] + 1)
    if len(set(tools)) < 2:
        raise SlicerProfileError("Prusa multi-material workbench needs two distinct tools.")
    width, depth = trusted_plate_dimensions(job.printer_profile)
    result = {
        "owner_id": job.owner_id, "printer_profile": job.printer_profile,
        "process_profile": job.process_profile, "filament_profiles": ordered,
        "tools": tools, "bed_width": width, "bed_depth": depth,
    }
    if kind == "single_nozzle_changer":
        tower = settings.get("prime_tower")
        flush = settings.get("flush_settings")
        if (not isinstance(tower, dict) or set(tower) != {"x", "y"}
                or not isinstance(flush, dict) or
                flush.get("prime_tower") == "disabled" or
                flush.get("multiplier") not in (None, 1, 1.0)):
            raise SlicerProfileError("Prusa MMU requires a tower and unscaled complete purge matrix.")
        transitions = flush.get("transitions")
        if not isinstance(transitions, list) or len(transitions) != count * (count - 1):
            raise SlicerProfileError("Specify every directional Prusa MMU purge transition.")
        matrix = [[0 if x == y else None for y in range(count)] for x in range(count)]
        seen_pairs = set()
        for entry in transitions:
            if not isinstance(entry, dict) or set(entry) != {"from_slot_id", "to_slot_id", "volume_mm3"}:
                raise SlicerProfileError("Invalid Prusa MMU purge transition.")
            source, dest = entry["from_slot_id"], entry["to_slot_id"]
            if source not in by_slot or dest not in by_slot or source == dest or (source, dest) in seen_pairs:
                raise SlicerProfileError("Prusa MMU purge transitions must be unique and complete.")
            seen_pairs.add((source, dest))
            matrix[by_slot[source]][by_slot[dest]] = entry["volume_mm3"]
        result.update(purge_matrix=matrix, tower_xy=(tower["x"], tower["y"]))
        return "mmu", result
    if settings.get("flush_settings") is not None or settings.get("prime_tower") is not None:
        raise SlicerProfileError("Prusa XL independent heads cannot use unqualified MMU flushing.")
    return "xl", result


def slice_prusa_workbench_material(job, source_models):
    """Return audited offline G-code for the normal private job store."""
    kind, prepared = prepare_prusa_workbench_material(job)
    if len(source_models) != len(prepared["tools"]):
        raise SlicerProfileError("Prusa native model source count changed.")
    prepared["rows"] = source_models
    if kind == "mmu":
        return slice_prusa_offline_mmu_candidate(job.pk, **prepared)
    return slice_prusa_offline_xl_candidate(job.pk, **prepared)
