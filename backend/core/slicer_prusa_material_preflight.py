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
from .slicer_prusa_process_settings import apply_prusa_process_overrides
from .slicer_prusa_wipe_tower import add_prusa_native_wipe_tower
from .slicer_profiles import SlicerProfileError
from slicer_worker.prusa_material_validation import validate_prusa_material_candidate


def prepare_prusa_offline_mmu_candidate(
    *, owner_id, printer_profile, process_profile, filament_profiles,
    rows, tools, purge_matrix, tower_xy, bed_width, bed_depth,
    process_overrides=None
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
    process = apply_prusa_process_overrides(
        resolved_prusa_profile(process_profile),
        {} if process_overrides is None else process_overrides)
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
        "research_only": True, "tower": (tower_xy[0],tower_xy[1],0,bed_width,bed_depth),
    }


def prepare_prusa_offline_xl_candidate(
    *, owner_id, printer_profile, process_profile, filament_profiles,
    rows, tools, bed_width, bed_depth, process_overrides=None
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
        raise SlicerProfileError("Prusa XL/INDX candidate requires privately owned native profiles.")
    if (not isinstance(rows, (tuple, list)) or not isinstance(tools, (tuple, list)) or
            len(rows) != len(tools) or not 2 <= len(rows) <= 12 or
            any(type(tool) is not int for tool in tools)):
        raise SlicerProfileError("Prusa independent-head model/tool assignment is incomplete.")
    printer = resolved_prusa_profile(printer_profile)
    process = apply_prusa_process_overrides(
        resolved_prusa_profile(process_profile),
        {} if process_overrides is None else process_overrides)
    filaments = [resolved_prusa_profile(p) for p in filament_profiles]
    topology = prusa_machine_topology(printer)
    if (topology["kind"] not in ("independent_tools", "indx") or
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
        raise SlicerProfileError("Prusa independent native candidate verification failed.")
    return {
        "model": project, "printer": printer, "filament": palette,
        "process": process, "expected_tools": assignment["selected_tools"],
        "topology": topology["kind"], "research_only": True,
    }


def slice_prusa_offline_mmu_candidate(job_id, **prepared_settings):
    """Authenticated, ephemeral G-code research. Never persists or dispatches.

    Ownership is rechecked by the full preflight BEFORE any worker request;
    this entry point is intentionally not linked to SliceJob or printer APIs.
    """
    from .slicer_worker_client import run_remote_job
    from slicer_worker.prusa_material_gcode_audit import audit_prusa_material_model_gcode
    candidate = prepare_prusa_offline_mmu_candidate(**prepared_settings)
    output = run_remote_job(
        job_id, "prusaslicer", "2.9.7",
        candidate["model"], candidate["printer"], candidate["filament"],
        candidate["process"], model_format="3mf",
        prusa_offline_mmu={"tools":list(prepared_settings["tools"]),
                           "tower":list(candidate["tower"])},
    )
    # Defence in depth: the isolated worker has already checked this same
    # material-to-object relationship, but transport returns arbitrary bytes.
    audit_prusa_material_model_gcode(
        output,candidate["model"],printer_ini=candidate["printer"],
        tools=list(prepared_settings["tools"]),tower=list(candidate["tower"]))
    return output


def slice_prusa_offline_xl_candidate(job_id, **prepared_settings):
    """Ephemeral independent-XL toolhead research; no model or G-code persisted."""
    from .slicer_worker_client import run_remote_job
    from slicer_worker.prusa_material_gcode_audit import audit_prusa_material_model_gcode
    candidate=prepare_prusa_offline_xl_candidate(**prepared_settings)
    output=run_remote_job(
        job_id,"prusaslicer","2.9.7",
        candidate["model"],candidate["printer"],candidate["filament"],
        candidate["process"],model_format="3mf",
        prusa_offline_xl={"tools":list(prepared_settings["tools"])})
    audit_prusa_material_model_gcode(
        output,candidate["model"],printer_ini=candidate["printer"],
        tools=list(prepared_settings["tools"]))
    # Native multi-head 3MF may retain object-specific layer ranges. Do not
    # accept a successful CLI exit if the requested Z schedule was ignored
    # on a particular model. The existing spatial auditor measures actual
    # moving extrusion within each original object's independent footprint.
    rows = prepared_settings["rows"]
    if any(isinstance(row.get("variable_layer_profile"), dict) and
           row["variable_layer_profile"].get("bands") for row, _ in rows):
        from .slicer_prusa_native_resolution import parse_prusa_profile
        from .slicer_prusa_spatial_layers import audit_prusa_multi_object_layer_ranges
        process_settings = parse_prusa_profile(candidate["process"], "process")
        try:
            base_layer_mm = float(process_settings["layer_height"])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise SlicerProfileError(
                "Prusa multi-head variable layers need a numeric process layer height."
            ) from exc
        try:
            audit_prusa_multi_object_layer_ranges(
                output, list(rows), bed_width=prepared_settings["bed_width"],
                bed_depth=prepared_settings["bed_depth"],
                base_layer_mm=base_layer_mm)
        except (ValueError, TypeError, OverflowError) as exc:
            raise SlicerProfileError(
                "Native Prusa output did not preserve each requested object layer schedule."
            ) from exc
    return output


def prepare_prusa_offline_colour_candidate(
    *, owner_id, printer_profile, process_profile, filament_profiles,
    rows, tools, purge_matrix, tower_xy, bed_width, bed_depth,
    colour_slot=None, colour_tool=None, colour_tool_indices=None
):
    """Compile exactly one fingerprinted MMU front-painted STL with private profiles."""
    if (type(owner_id) is not int or owner_id<1 or
            not isinstance(rows,(list,tuple)) or len(rows)!=1 or
            not isinstance(tools,(list,tuple)) or list(tools)!=[1] or
            not isinstance(tower_xy,(list,tuple)) or len(tower_xy)!=2):
        raise SlicerProfileError("Prusa painted MMU selection needs one T0 model and native wipe tower.")
    if colour_tool_indices is None:
        if (type(colour_slot) is not int or not 0<=colour_slot<16 or
                type(colour_tool) is not int or not 1<=colour_tool<=4):
            raise SlicerProfileError("Prusa native paint swatch and tool are invalid.")
        colour_tool_indices={colour_slot:colour_tool}
    if (not isinstance(colour_tool_indices,dict) or
            not 1<=len(colour_tool_indices)<=2 or
            any(type(slot) is not int or not 0<=slot<16 or
                type(tool) is not int or not 1<=tool<=4
                for slot,tool in colour_tool_indices.items()) or
            len(set(colour_tool_indices.values()))!=len(colour_tool_indices)):
        raise SlicerProfileError("Prusa painted MMU needs one or two distinct native tools.")

    for kind,profile in (("printer",printer_profile),("process",process_profile)):
        if (profile.owner_id!=owner_id or profile.kind!=kind or
                profile.engine!="prusaslicer" or
                profile.engine_version!="2.9.7"):
            raise SlicerProfileError("Prusa painted native printer or process profile is not owned.")
    if (not isinstance(filament_profiles,(list,tuple)) or
            any(profile.owner_id!=owner_id or profile.kind!="filament" or
                profile.engine!="prusaslicer" or
                profile.engine_version!="2.9.7" for profile in filament_profiles)):
        raise SlicerProfileError("Every Prusa painted filament must be owned.")
    row,model=rows[0]
    if not isinstance(row,dict) or not isinstance(model,bytes):
        raise SlicerProfileError("Invalid Prusa native painted model.")
    if (row.get("colour_paint") or {}).get("regions") is None:
        raise SlicerProfileError("Prusa native painting requires a fingerprinted region.")
    printer=resolved_prusa_profile(printer_profile)
    topology=prusa_machine_topology(printer)
    if (topology["kind"]!="single_nozzle_changer" or
            not 2<=topology["logical_tool_count"]<=5 or
            any(tool>=topology["logical_tool_count"] for tool in colour_tool_indices.values()) or
            len(filament_profiles)!=topology["logical_tool_count"]):
        raise SlicerProfileError("Prusa native painting requires a qualified MMU tool palette.")
    process=resolved_prusa_profile(process_profile)
    filaments=[resolved_prusa_profile(profile) for profile in filament_profiles]
    palette=compile_prusa_filament_palette(printer,filaments)
    native_process=compile_prusa_purge_matrix(printer,process,purge_matrix)
    from .slicer_prusa_colour_project import build_prusa_colour_candidate
    project=build_prusa_colour_candidate(
        row,model,printer_ini=printer,
        colour_tool_indices=colour_tool_indices,
        bed_width=bed_width,bed_depth=bed_depth)
    project=add_prusa_native_wipe_tower(
        project,x_mm=tower_xy[0],y_mm=tower_xy[1],rotation_deg=0,
        bed_width=bed_width,bed_depth=bed_depth)
    tower=(tower_xy[0],tower_xy[1],0,bed_width,bed_depth)
    from slicer_worker.prusa_offline_contract import validate_prusa_offline_colour_inputs
    if len(colour_tool_indices)==2:
        from slicer_worker.prusa_colour_gcode_audit import _two_painted_wall_regions
        from slicer_worker.runner import WorkerError
        # Browser palette slots are not front/back directions. Derive and
        # verify exact wall order from the *signed source-mesh 3MF* before
        # submitting tool order. Never assume slot 1 means front.
        selected = tuple(colour_tool_indices.values())
        try:
            _two_painted_wall_regions(project, selected)
        except WorkerError:
            selected = tuple(reversed(selected))
            try:
                _two_painted_wall_regions(project, selected)
            except WorkerError as exc:
                raise SlicerProfileError(
                    "Prusa two-swatch painting requires complete opposite front/back walls."
                ) from exc
        receipt = validate_prusa_offline_colour_inputs(
            project=project,printer=printer,filament=palette,process=native_process,
            tools=list(selected),tower=list(tower))
    else:
        selected = (next(iter(colour_tool_indices.values())),)
        receipt = validate_prusa_offline_colour_inputs(
            project=project,printer=printer,filament=palette,process=native_process,
            tool=selected[0],tower=list(tower))
    return {"model":project,"printer":printer,"filament":palette,
            "process":native_process,"tower":tower,"tools":selected,
            **({"tool":selected[0]} if len(selected)==1 else {})}


def slice_prusa_offline_colour_candidate(job_id, **prepared):
    """Return genuine authenticated and independently audited painted MMU G-code."""
    from .slicer_worker_client import run_remote_job
    from slicer_worker.prusa_colour_gcode_audit import audit_prusa_offline_colour_gcode
    candidate=prepare_prusa_offline_colour_candidate(**prepared)
    multi=len(candidate["tools"])==2
    selection=({"tools":list(candidate["tools"])} if multi
               else {"tool":candidate["tool"]})
    output=run_remote_job(
        job_id,"prusaslicer","2.9.7",
        candidate["model"],candidate["printer"],candidate["filament"],
        candidate["process"],model_format="3mf",
        prusa_offline_colour={**selection,"tower":list(candidate["tower"])})
    if multi:
        from slicer_worker.prusa_colour_gcode_audit import audit_prusa_dual_colour_gcode
        audit_prusa_dual_colour_gcode(
            output,candidate["model"],printer_ini=candidate["printer"],
            tools=candidate["tools"],tower=candidate["tower"])
    else:
        audit_prusa_offline_colour_gcode(
            output,candidate["model"],printer_ini=candidate["printer"],
            tool=candidate["tool"],tower=candidate["tower"])
    return output
