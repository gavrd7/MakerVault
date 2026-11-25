"""Prepare a complete Prusa MMU *offline research* job from private assets.

This is an intermediate artefact, not worker admission or printer submission.
The normal production worker continues to reject these multi-material 3MFs.
Every native input and physical/logical tool binding is explicit and immutable.
"""
from .slicer_prusa_filament_palette import compile_prusa_filament_palette
from .slicer_prusa_machine_topology import prusa_machine_topology
from .slicer_prusa_multitool_project import build_prusa_multitool_candidate
from .slicer_prusa_native_resolution import resolved_prusa_profile
from .slicer_prusa_purge import compile_prusa_purge_matrix
from .slicer_prusa_wipe_tower import add_prusa_native_wipe_tower
from .slicer_profiles import SlicerProfileError
from slicer_worker.prusa_material_validation import validate_prusa_material_candidate


def prepare_prusa_offline_mmu_candidate(
    *, owner_id, printer_profile, process_profile, filament_profiles,
    rows, tools, purge_matrix, tower_xy, bed_width, bed_depth
):
    """Return a validated candidate, not a user-uploadable/dispatchable job.

    The exact selected native tool sequence is one-based; filament profiles
    are ordered T0..Tn-1, not in model order. A distinct owned profile must
    be selected for every native logical tool, including unused MMU slots.
    """
    if (type(owner_id) is not int or owner_id < 1 or
            printer_profile.owner_id != owner_id or
            process_profile.owner_id != owner_id or
            printer_profile.kind != "printer" or
            process_profile.kind != "process" or
            printer_profile.engine != "prusaslicer" or
            process_profile.engine != "prusaslicer"):
        raise SlicerProfileError("Prusa MMU candidate requires privately owned matching profiles.")
    if (not isinstance(filament_profiles, (tuple, list)) or
            any(p.owner_id != owner_id or p.kind != "filament" or
                p.engine != "prusaslicer" for p in filament_profiles)):
        raise SlicerProfileError("Every Prusa MMU filament preset must be owned and native.")
    if (not isinstance(rows, (tuple, list)) or not isinstance(tools, (tuple, list)) or
            len(rows) != len(tools) or not 2 <= len(rows) <= 5 or
            any(type(tool) is not int for tool in tools) or
            not isinstance(tower_xy, (list, tuple)) or len(tower_xy) != 2):
        raise SlicerProfileError("Prusa MMU models, tools or wipe tower are incomplete.")
    # Check all metadata ownership and kinds *before* reading any asset.
    printer = resolved_prusa_profile(printer_profile)
    process = resolved_prusa_profile(process_profile)
    filaments = [resolved_prusa_profile(p) for p in filament_profiles]
    topology = prusa_machine_topology(printer)
    if topology["kind"] != "single_nozzle_changer":
        raise SlicerProfileError("This research route is for an MMU changer, not XL independent tools.")
    if len(filaments) != topology["logical_tool_count"]:
        raise SlicerProfileError("Each native MMU tool requires its own owned filament preset.")
    palette = compile_prusa_filament_palette(printer, filaments)
    print_settings = compile_prusa_purge_matrix(printer, process, purge_matrix)
    project, assigned = build_prusa_multitool_candidate(
        rows, printer_ini=printer, tools=tools,
        bed_width=bed_width, bed_depth=bed_depth)
    project = add_prusa_native_wipe_tower(
        project, x_mm=tower_xy[0], y_mm=tower_xy[1], rotation_deg=0,
        bed_width=bed_width, bed_depth=bed_depth)
    receipt = validate_prusa_material_candidate(
        project, printer_ini=printer, tools=tools,
        tower=(tower_xy[0], tower_xy[1], 0, bed_width, bed_depth))
    if (receipt["objects"] != len(rows) or not receipt["wipe_tower"] or
            tuple(sorted(set(tools))) != assigned["selected_tools"]):
        raise SlicerProfileError("Prusa MMU native candidate verification failed.")
    return {
        "model": project, "printer": printer, "filament": palette,
        "process": print_settings, "expected_tools": assigned["selected_tools"],
        "topology": topology["kind"],
        "research_only": True,
    }


def prepare_prusa_offline_xl_candidate(
    *, owner_id, printer_profile, process_profile, filament_profiles,
    rows, tools, bed_width, bed_depth
):
    """Research-only independent-toolhead model assignment, no MMU purge.

    Do not synthesize changer purge/tower settings for an XL; tool pickup,
    physical offsets and firmware start codes need independent qualification.
    """
    if (type(owner_id) is not int or owner_id < 1 or
            printer_profile.owner_id != owner_id or
            process_profile.owner_id != owner_id or
            printer_profile.kind != "printer" or
            process_profile.kind != "process" or
            printer_profile.engine != "prusaslicer" or
            process_profile.engine != "prusaslicer" or
            not isinstance(filament_profiles, (tuple, list)) or
            any(p.owner_id != owner_id or p.kind != "filament" or
                p.engine != "prusaslicer" for p in filament_profiles)):
        raise SlicerProfileError("Prusa XL candidate requires privately owned native profiles.")
    if (not isinstance(rows, (tuple, list)) or not isinstance(tools, (tuple, list)) or
            len(rows) != len(tools) or not 2 <= len(rows) <= 5 or
            any(type(tool) is not int for tool in tools)):
        raise SlicerProfileError("Prusa XL model/tool assignment is incomplete.")
    printer = resolved_prusa_profile(printer_profile)
    process = resolved_prusa_profile(process_profile)
    filaments = [resolved_prusa_profile(p) for p in filament_profiles]
    topology = prusa_machine_topology(printer)
    if (topology["kind"] != "independent_tools" or
            len(filaments) != topology["logical_tool_count"]):
        raise SlicerProfileError("Prusa XL candidate needs one preset per independent toolhead.")
    palette = compile_prusa_filament_palette(printer, filaments)
    project, assignment = build_prusa_multitool_candidate(
        rows, printer_ini=printer, tools=tools,
        bed_width=bed_width, bed_depth=bed_depth)
    receipt = validate_prusa_material_candidate(
        project, printer_ini=printer, tools=tools)
    if (receipt["objects"] != len(rows) or receipt["wipe_tower"] or
            assignment["selected_tools"] != tuple(sorted(set(tools)))):
        raise SlicerProfileError("Prusa XL native candidate verification failed.")
    return {
        "model": project, "printer": printer, "filament": palette,
        "process": process, "expected_tools": assignment["selected_tools"],
        "topology": topology["kind"], "research_only": True,
    }
