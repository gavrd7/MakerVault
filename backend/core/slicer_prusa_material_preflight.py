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
            len(rows) != len(tools) or not 2 <= len(rows) <= 200 or
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
            len(rows) != len(tools) or not 2 <= len(rows) <= 200 or
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
        tools=list(prepared_settings["tools"]),tower=list(candidate["tower"]),
        process_ini=candidate["process"])
    # MMU modifier meshes are audited by the ordinary typed-volume project
    # validator and the independent native material-deposition guard above.
    # Per-Object layer-height ranges remain disabled for this pinned MMU
    # runtime after its genuine CLI produced no G-code for either
    # layer-only or layer-plus-modifier input.
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
        tools=list(prepared_settings["tools"]),process_ini=candidate["process"])
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
    colour_slot=None, colour_tool=None, colour_tool_indices=None,
    process_overrides=None
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
    process=apply_prusa_process_overrides(
        resolved_prusa_profile(process_profile),
        {} if process_overrides is None else process_overrides)
    filaments=[resolved_prusa_profile(profile) for profile in filament_profiles]
    palette=compile_prusa_filament_palette(printer,filaments)
    native_process=compile_prusa_purge_matrix(printer,process,purge_matrix)
    from .slicer_prusa_colour_project import build_prusa_colour_candidate
    from .slicer_modifier_volumes import validate_modifier_volumes
    try:
        volumes=validate_modifier_volumes(row.get("modifier_volumes"))
    except (TypeError,ValueError) as exc:
        raise SlicerProfileError("Invalid painted native volumes.") from exc
    fuzz_source=row.get("fuzzy_skin_paint") or {}
    fuzzy=(isinstance(fuzz_source,dict) and bool(fuzz_source.get("regions")))
    if row.get("fuzzy_skin_paint") and not fuzzy:
        raise SlicerProfileError("Prusa selective fuzzy requires native painted facets.")
    compound=bool(volumes) and len(volumes)==2
    if fuzzy and (volumes or len(colour_tool_indices)!=1 or
                  next(iter(colour_tool_indices.values()))!=1 or
                  row.get("support_paint") or row.get("seam_paint") or
                  row.get("variable_layer_profile")):
        raise SlicerProfileError(
            "Prusa MMU coloured fuzzy paint needs one T1 wall and no other combined edits.")
    if compound:
        # Native proof covers only one T1-painted full wall with exactly
        # one box density modifier and one independent, disjoint box cavity.
        if (colour_tool_indices != {next(iter(colour_tool_indices)):1} or
                [v["kind"] for v in volumes] != ["modifier","negative"] or
                any(v["shape"]!="box" or
                    v.get("coordinate_space")!="world" for v in volumes) or
                set(volumes[0]["settings"])!={"sparse_infill_density"} or
                volumes[1]["settings"]):
            raise SlicerProfileError(
                "Prusa painted modifier/cavity requires T1, one infill box and one disjoint negative box.")
    project=build_prusa_colour_candidate(
        row,model,printer_ini=printer,
        colour_tool_indices=colour_tool_indices,
        bed_width=bed_width,bed_depth=bed_depth,
        research_compound=compound or fuzzy)
    project=add_prusa_native_wipe_tower(
        project,x_mm=tower_xy[0],y_mm=tower_xy[1],rotation_deg=0,
        bed_width=bed_width,bed_depth=bed_depth)
    tower=(tower_xy[0],tower_xy[1],0,bed_width,bed_depth)
    from slicer_worker.prusa_offline_contract import validate_prusa_offline_colour_inputs
    if len(colour_tool_indices)==2:
        from slicer_worker.prusa_dual_partial import qualified_prusa_dual_colour_mode
        from slicer_worker.runner import WorkerError
        # Palette slot order does not encode source-wall direction. Derive
        # the physical T1/T2 positions from authenticated native facets.
        selected = tuple(colour_tool_indices.values())
        try:
            qualified_prusa_dual_colour_mode(project, selected)
        except WorkerError:
            selected = tuple(reversed(selected))
            try:
                qualified_prusa_dual_colour_mode(project, selected)
            except WorkerError as exc:
                raise SlicerProfileError(
                    "Prusa two-swatch painting requires qualified opposing "
                    "complete or independently split native exterior walls."
                ) from exc
        receipt = validate_prusa_offline_colour_inputs(
            project=project,printer=printer,filament=palette,process=native_process,
            tools=list(selected),tower=list(tower))
    else:
        selected = (next(iter(colour_tool_indices.values())),)
        receipt = validate_prusa_offline_colour_inputs(
            project=project,printer=printer,filament=palette,process=native_process,
            tool=selected[0],tower=list(tower))
    if (receipt["compound_volume"] != compound or
            receipt["colour_fuzzy"] != fuzzy):
        raise SlicerProfileError(
            "Prusa native project lost a requested modifier or fuzzy-painted facet.")
    return {"model":project,"printer":printer,"filament":palette,
            "process":native_process,"tower":tower,"tools":selected,
            "compound_volume":compound,
            "colour_fuzzy":fuzzy,
            "dual_partial":receipt["dual_partial"],
            "partial_wall":receipt.get("partial_wall", False),
            "partial_top":receipt["partial_top"],
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
        if candidate["dual_partial"]:
            from slicer_worker.prusa_dual_partial import audit_prusa_dual_partial_gcode
            audit_prusa_dual_partial_gcode(
                output,candidate["model"],printer_ini=candidate["printer"],
                tools=candidate["tools"],tower=candidate["tower"])
        else:
            from slicer_worker.prusa_colour_gcode_audit import audit_prusa_dual_colour_gcode
            audit_prusa_dual_colour_gcode(
                output,candidate["model"],printer_ini=candidate["printer"],
                tools=candidate["tools"],tower=candidate["tower"])
    elif candidate["partial_wall"]:
        from slicer_worker.prusa_partial_surface import audit_prusa_partial_wall_gcode
        audit_prusa_partial_wall_gcode(
            output, candidate["model"], tool=candidate["tool"],
            tower=candidate["tower"])
    elif candidate["partial_top"]:
        from slicer_worker.prusa_top_surface import audit_prusa_partial_top_gcode
        audit_prusa_partial_top_gcode(
            output, candidate["model"], tool=candidate["tool"],
            tower=candidate["tower"])
    else:
        audit_prusa_offline_colour_gcode(
            output,candidate["model"],printer_ini=candidate["printer"],
            tool=candidate["tool"],tower=candidate["tower"])
    from slicer_worker.prusa_colour_compound import audit_prusa_painted_volume_effects
    audit_prusa_painted_volume_effects(output, candidate["model"])
    if candidate["colour_fuzzy"]:
        from slicer_worker.prusa_colour_fuzzy import audit_prusa_colour_fuzzy_gcode
        audit_prusa_colour_fuzzy_gcode(output,candidate["model"])
    return output


def prepare_prusa_offline_xl_colour_candidate(
    *, owner_id, printer_profile, process_profile, filament_profiles,
    rows, tools, bed_width, bed_depth, colour_tool_indices,
    process_overrides=None,
):
    """Owner-scoped native XL one- or two-wall paint, no MMU purge or dispatch."""
    from .slicer_prusa_colour_project import build_prusa_colour_candidate
    from slicer_worker.prusa_offline_contract import validate_prusa_offline_xl_colour_inputs
    if (type(owner_id) is not int or owner_id < 1 or
            not isinstance(rows,(list,tuple)) or len(rows)!=1 or
            not isinstance(tools,(list,tuple)) or list(tools)!=[1] or
            not isinstance(colour_tool_indices,dict) or
            len(colour_tool_indices) not in (1,2,4) or
            any(type(slot) is not int or not 0<=slot<16 or
                type(tool) is not int or not 1<=tool<=7
                for slot,tool in colour_tool_indices.items()) or
            len(set(colour_tool_indices.values()))!=len(colour_tool_indices)):
        raise SlicerProfileError("Prusa XL colour requires one T0 model and distinct native wall tools.")
    if any(profile is None or profile.owner_id!=owner_id or
           profile.engine!="prusaslicer" or profile.engine_version!="2.9.7" or
           profile.kind!=kind for kind,profile in (
               ("printer",printer_profile),("process",process_profile))):
        raise SlicerProfileError("Prusa XL native profiles must be privately owned.")
    if not isinstance(filament_profiles,(list,tuple)) or any(
            profile.owner_id!=owner_id or profile.engine!="prusaslicer" or
            profile.engine_version!="2.9.7" or profile.kind!="filament"
            for profile in filament_profiles):
        raise SlicerProfileError("Prusa XL requires privately owned native filaments.")
    row,raw=rows[0]
    if not isinstance(row,dict) or not isinstance(raw,bytes):
        raise SlicerProfileError("Prusa XL painted model source is invalid.")
    printer=resolved_prusa_profile(printer_profile)
    topology=prusa_machine_topology(printer)
    if (topology["kind"] not in ("independent_tools","indx") or
            not 2<=topology["logical_tool_count"]<=8 or
            any(tool>=topology["logical_tool_count"]
                for tool in colour_tool_indices.values()) or
            len(filament_profiles)!=topology["logical_tool_count"]):
        raise SlicerProfileError("Prusa XL needs a matching independent-head printer palette.")
    process=apply_prusa_process_overrides(
        resolved_prusa_profile(process_profile),
        {} if process_overrides is None else process_overrides)
    filaments=[resolved_prusa_profile(profile) for profile in filament_profiles]
    palette=compile_prusa_filament_palette(printer,filaments)
    project=build_prusa_colour_candidate(
        row,raw,printer_ini=printer,colour_tool_indices=colour_tool_indices,
        bed_width=bed_width,bed_depth=bed_depth)
    if len(colour_tool_indices)==4:
        from slicer_worker.prusa_four_wall_audit import four_painted_wall_regions
        from slicer_worker.runner import WorkerError
        try:
            walls=four_painted_wall_regions(project)
        except WorkerError as exc:
            raise SlicerProfileError("Prusa XL requires four complete painted exterior walls.") from exc
        selected=tuple(walls["tools"][side] for side in
                       ("x_min","x_max","y_min","y_max"))
        if (set(selected)!=set(colour_tool_indices.values()) or
                topology["kind"]!="independent_tools" or
                topology["logical_tool_count"]!=5):
            raise SlicerProfileError("Four painted walls require the qualified native XL5 printer.")
        selection={"tools":list(selected)}
    elif len(colour_tool_indices)==2:
        from slicer_worker.prusa_colour_gcode_audit import _two_painted_wall_regions
        from slicer_worker.runner import WorkerError
        # Browser palette order is not native wall order; resolve from the
        # actual serialised source mesh and confirm the opposite arrangement.
        selected=tuple(colour_tool_indices.values())
        try:
            _two_painted_wall_regions(project,selected)
        except WorkerError:
            selected=tuple(reversed(selected))
            try:
                _two_painted_wall_regions(project,selected)
            except WorkerError as exc:
                raise SlicerProfileError(
                    "Prusa XL dual painting requires complete opposite vertical walls."
                ) from exc
        selection={"tools":list(selected)}
    else:
        selected=(next(iter(colour_tool_indices.values())),)
        selection={"tool":selected[0]}
    receipt=validate_prusa_offline_xl_colour_inputs(
        project=project,printer=printer,filament=palette,process=process,
        **selection)
    if (receipt["partial_wall"] or receipt["partial_top"] or
            receipt["partial_slanted"]) and (
            topology["kind"] != "independent_tools" or
            topology["logical_tool_count"] != 5):
        raise SlicerProfileError(
            "Prusa split-surface painting has native proof for XL5 only.")
    if receipt["partial_slanted"] and selection.get("tool")!=1:
        raise SlicerProfileError(
            "Prusa angled painting has native proof for XL5 T1 only.")
    return {"model":project,"printer":printer,"filament":palette,
            "process":process, "partial_wall":receipt["partial_wall"],
            "partial_top":receipt["partial_top"],
            "partial_slanted":receipt["partial_slanted"],
            "partial_curved":receipt["partial_curved"], **selection}


def slice_prusa_offline_xl_colour_candidate(job_id, **prepared):
    """Return only independently audited XL native face-painted G-code."""
    from .slicer_worker_client import run_remote_job
    candidate=prepare_prusa_offline_xl_colour_candidate(**prepared)
    selection=({"tools":candidate["tools"]} if "tools" in candidate
               else {"tool":candidate["tool"]})
    output=run_remote_job(
        job_id,"prusaslicer","2.9.7",
        candidate["model"],candidate["printer"],candidate["filament"],
        candidate["process"],model_format="3mf",
        prusa_offline_xl_colour=selection)
    if "tools" in candidate and len(candidate["tools"])==4:
        from slicer_worker.prusa_four_wall_audit import audit_prusa_four_wall_gcode
        audit_prusa_four_wall_gcode(
            output,candidate["model"],printer_ini=candidate["printer"],
            tools=candidate["tools"])
    elif "tools" in candidate:
        from slicer_worker.prusa_colour_gcode_audit import audit_prusa_dual_colour_gcode
        audit_prusa_dual_colour_gcode(
            output,candidate["model"],printer_ini=candidate["printer"],
            tools=candidate["tools"],tower=None)
    elif candidate["partial_wall"]:
        from slicer_worker.prusa_partial_surface import audit_prusa_partial_wall_gcode
        audit_prusa_partial_wall_gcode(
            output, candidate["model"], tool=candidate["tool"])
    elif candidate["partial_top"]:
        from slicer_worker.prusa_top_surface import audit_prusa_partial_top_gcode
        audit_prusa_partial_top_gcode(
            output, candidate["model"], tool=candidate["tool"])
    elif candidate["partial_slanted"]:
        from slicer_worker.prusa_slanted_surface import audit_prusa_slanted_surface_gcode
        audit_prusa_slanted_surface_gcode(
            output, candidate["model"], tool=candidate["tool"])
    elif candidate["partial_curved"]:
        from slicer_worker.prusa_curved_surface import audit_prusa_curved_surface_gcode
        audit_prusa_curved_surface_gcode(
            output, candidate["model"], tool=candidate["tool"])
    else:
        from slicer_worker.prusa_colour_gcode_audit import audit_prusa_xl_colour_gcode
        audit_prusa_xl_colour_gcode(
            output,candidate["model"],printer_ini=candidate["printer"],
            tool=candidate["tool"])
    from slicer_worker.prusa_colour_compound import audit_prusa_painted_volume_effects
    audit_prusa_painted_volume_effects(output, candidate["model"])
    return output


def prepare_prusa_offline_multi_colour_candidate(
    *, owner_id,printer_profile,process_profile,filament_profiles,
    rows,tools,purge_matrix,tower_xy,bed_width,bed_depth,
    colour_tool_indices,process_overrides=None
):
    """Compile two independently painted private ModelParts on a native MMU.

    Every selected source is independently fingerprinted and imported via
    MakerVault's existing Prusa colour encoder; the worker verifies the
    signed T1/T2 source objects, their separated footprints and final
    positive-E G-code before the owner may store the resulting slice.
    """
    if (type(owner_id) is not int or owner_id<1 or
            not isinstance(rows,(tuple,list)) or len(rows)!=2 or
            not isinstance(tools,(tuple,list)) or list(tools)!=[1,1] or
            not isinstance(tower_xy,(tuple,list)) or len(tower_xy)!=2 or
            not isinstance(colour_tool_indices,dict) or
            len(colour_tool_indices)!=2 or
            set(colour_tool_indices.values())!={1,2} or
            any(type(k) is not int or not 0<=k<16 or type(v) is not int
                for k,v in colour_tool_indices.items())):
        raise SlicerProfileError(
            "Prusa separate MMU colour models require T0 bases and distinct T1/T2 swatches.")
    for kind,profile in (("printer",printer_profile),("process",process_profile)):
        if (profile.owner_id!=owner_id or profile.kind!=kind or
                profile.engine!="prusaslicer" or
                profile.engine_version!="2.9.7"):
            raise SlicerProfileError("Prusa native coloured model profile is not owned.")
    if (not isinstance(filament_profiles,(tuple,list)) or
            any(profile.owner_id!=owner_id or profile.kind!="filament" or
                profile.engine!="prusaslicer" or
                profile.engine_version!="2.9.7" for profile in filament_profiles)):
        raise SlicerProfileError("Prusa independent colour filament profile is unowned.")
    source_slots=[]
    for pair in rows:
        if (not isinstance(pair,(tuple,list)) or len(pair)!=2 or
                not isinstance(pair[0],dict) or
                not isinstance(pair[1],bytes)):
            raise SlicerProfileError("Prusa independent native painted source is invalid.")
        item,_mesh=pair
        paint=item.get("colour_paint") or {}
        regions=paint.get("regions") if isinstance(paint,dict) else None
        if (not isinstance(regions,list) or len(regions)!=1 or
                not isinstance(regions[0],dict) or
                type(regions[0].get("slot")) is not int or
                any(item.get(k) for k in (
                    "modifier_volumes","negative_volumes","support_paint",
                    "seam_paint","fuzzy_skin_paint","variable_layer_profile",
                    "material_slot","process_overrides"))):
            raise SlicerProfileError(
                "Each independent native Prusa colour model needs one signed paint swatch.")
        source_slots.append(regions[0]["slot"])
    if (len(set(source_slots))!=2 or
            {colour_tool_indices.get(slot) for slot in source_slots}!={1,2} or
            colour_tool_indices[source_slots[0]]!=1 or
            colour_tool_indices[source_slots[1]]!=2):
        raise SlicerProfileError(
            "The two independently painted Prusa models require T1 then T2.")
    printer=resolved_prusa_profile(printer_profile)
    topology=prusa_machine_topology(printer)
    if (topology["kind"]!="single_nozzle_changer" or
            not 3<=topology["logical_tool_count"]<=5 or
            len(filament_profiles)!=topology["logical_tool_count"]):
        raise SlicerProfileError("Native Prusa independently painted models need a qualified MMU.")
    native_process=apply_prusa_process_overrides(
        resolved_prusa_profile(process_profile),
        {} if process_overrides is None else process_overrides)
    filament=compile_prusa_filament_palette(
        printer,[resolved_prusa_profile(profile)
                 for profile in filament_profiles])
    native_process=compile_prusa_purge_matrix(
        printer,native_process,purge_matrix)
    from .slicer_prusa_colour_project import build_prusa_multi_colour_candidate
    project=build_prusa_multi_colour_candidate(
        rows,printer_ini=printer,colour_tool_indices=colour_tool_indices,
        bed_width=bed_width,bed_depth=bed_depth)
    project=add_prusa_native_wipe_tower(
        project,x_mm=tower_xy[0],y_mm=tower_xy[1],rotation_deg=0,
        bed_width=bed_width,bed_depth=bed_depth)
    tower=(tower_xy[0],tower_xy[1],0,bed_width,bed_depth)
    from slicer_worker.prusa_offline_contract import (
        validate_prusa_offline_multi_colour_inputs)
    receipt=validate_prusa_offline_multi_colour_inputs(
        project=project,printer=printer,filament=filament,
        process=native_process,tools=[1,2],tower=list(tower))
    if receipt["tools"]!=[1,2]:
        raise SlicerProfileError("Prusa independent native swatches changed after export.")
    return {"model":project,"printer":printer,"filament":filament,
            "process":native_process,"tower":tower,"tools":[1,1],
            "colour_tools":[1,2]}


def slice_prusa_offline_multi_colour_candidate(job_id, **prepared):
    """Only return two separately painted ModelParts with audited T1/T2 G-code."""
    from .slicer_worker_client import run_remote_job
    from slicer_worker.prusa_multi_colour import audit_prusa_multi_colour_gcode
    candidate=prepare_prusa_offline_multi_colour_candidate(**prepared)
    output=run_remote_job(
        job_id,"prusaslicer","2.9.7",
        candidate["model"],candidate["printer"],candidate["filament"],
        candidate["process"],model_format="3mf",
        prusa_offline_multi_colour={"tools":[1,2],
                                    "tower":list(candidate["tower"])})
    audit_prusa_multi_colour_gcode(
        output,candidate["model"],printer_ini=candidate["printer"],
        tower=candidate["tower"])
    return output
