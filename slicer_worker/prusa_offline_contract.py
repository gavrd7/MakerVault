"""Independent worker-side MMU offline admission checks (not printer dispatch).

Unlike the backend's owner-scoped compiler, this module trusts no request
metadata. The worker re-parses the exact bytes it will feed to Prusa 2.9.7.
"""
import math

from .prusa_material_validation import validate_prusa_material_candidate, _qualified_topology
from .prusa_vendor_profiles import validate_flat_prusa_preset, PrusaPresetError
from .runner import WorkerError


def validate_prusa_offline_mmu_inputs(*, project, printer, filament, process,
                                      tools, tower):
    count, same_nozzle = _qualified_topology(printer)
    if not same_nozzle or not 2 <= count <= 5:
        raise WorkerError("Prusa offline MMU requires an explicit changer machine.")
    if (not isinstance(tools, list) or not 2 <= len(tools) <= 200
            or any(type(t) is not int or not 1 <= t <= count for t in tools)
            or len(set(tools)) < 2):
        raise WorkerError("Prusa offline MMU model tool selection is invalid.")
    if (not isinstance(tower, list) or len(tower) != 5 or
            any(type(v) not in (int, float) or not math.isfinite(v) for v in tower)):
        raise WorkerError("Prusa offline MMU wipe tower specification is invalid.")
    try:
        filament_settings = validate_flat_prusa_preset(filament, kind="filament")
        process_settings = validate_flat_prusa_preset(process, kind="print")
    except PrusaPresetError:
        raise WorkerError("Prusa offline MMU native profiles are invalid.") from None
    if (process_settings.get("wipe_tower") != "1" or
            process_settings.get("wipe_into_infill") != "0" or
            process_settings.get("wipe_into_objects") != "0"):
        raise WorkerError("Prusa offline MMU requires isolated native wipe tower purging.")
    for key in ("temperature", "first_layer_temperature"):
        raw = filament_settings.get(key, "").split(",")
        if (len(raw) != count or any(
                not value.isascii() or not value.isdecimal()
                or not 0 <= int(value) <= 350 for value in raw)):
            raise WorkerError("Prusa offline MMU native temperature vector is invalid.")
    # Prusa's logical material transition matrix is row-major, tool->tool.
    parts = process_settings.get("wiping_volumes_matrix", "").split(",")
    if len(parts) != count * count:
        raise WorkerError("Prusa offline MMU purge matrix dimensions are invalid.")
    for index, value in enumerate(parts):
        try:
            number = float(value)
        except ValueError:
            raise WorkerError("Prusa offline MMU purge volume is invalid.") from None
        diagonal = index // count == index % count
        if (not math.isfinite(number) or number < 0 or number > 1000
                or (diagonal and number != 0)
                or (not diagonal and number < 1)):
            raise WorkerError("Prusa offline MMU transition volume is invalid.")
    receipt = validate_prusa_material_candidate(
        project, printer_ini=printer, tools=tools, tower=tower)
    if (receipt["objects"] != len(tools) or not receipt["wipe_tower"]
            or set(receipt["tools"]) != set(tools)):
        raise WorkerError("Prusa offline MMU project/tool assignment mismatch.")
    return {"tools": tuple(tools), "tool_count": count,
            "wipe_tower": True, "offline_only": True}


def validate_prusa_offline_xl_inputs(*, project, printer, filament, process, tools):
    """Independent-head XL research must never inherit MMU changer purging."""
    count, same_nozzle = _qualified_topology(printer)
    if same_nozzle or not 2 <= count <= 8:
        raise WorkerError("Prusa offline XL/INDX requires independent native tools.")
    if (not isinstance(tools, list) or not 2 <= len(tools) <= 200
            or any(type(t) is not int or not 1 <= t <= count for t in tools)
            or len(set(tools)) < 2):
        raise WorkerError("Prusa offline XL/INDX model tools are invalid.")
    try:
        material = validate_flat_prusa_preset(filament, kind="filament")
        settings = validate_flat_prusa_preset(process, kind="print")
    except PrusaPresetError:
        raise WorkerError("Prusa offline XL native profiles are invalid.") from None
    if (settings.get("wipe_tower", "0") not in ("0", "", "false") or
            settings.get("wipe_into_objects","0") not in ("0", "", "false") or
            settings.get("wipe_into_infill","0") not in ("0", "", "false")):
        raise WorkerError("Unqualified XL wipe tower and model flushing are disabled.")
    for key in ("temperature", "first_layer_temperature"):
        parts=material.get(key,"").split(",")
        if (len(parts)!=count or any(
                not p.isascii() or not p.isdecimal() or
                not 0 <= int(p) <= 350 for p in parts)):
            raise WorkerError("Prusa offline independent-head temperature vector is invalid.")
    receipt=validate_prusa_material_candidate(
        project, printer_ini=printer, tools=tools)
    if (receipt["objects"]!=len(tools) or receipt["wipe_tower"]
            or set(receipt["tools"])!=set(tools)):
        raise WorkerError("Prusa offline XL model tool assignment mismatch.")
    return {"tools":tuple(tools), "tool_count":count,
            "wipe_tower":False, "offline_only":True}


def validate_prusa_offline_colour_inputs(*, project, printer, filament, process,
                                        tool=None, tools=None, tower):
    """Owner-compiled MMU-painted model with one or two bounded wall swatches.

    The worker accepts neither unverified multi-facet mixes nor physical
    printer upload. Exact native 3MF geometry and G-code attribution are
    independently audited after the CLI returns.
    """
    count, changer=_qualified_topology(printer)
    dual=tools is not None
    if dual:
        if (tool is not None or not isinstance(tools,list) or len(tools)!=2 or
                any(type(v) is not int or not 1<=v<count for v in tools) or
                len(set(tools))!=2):
            raise WorkerError("Prusa two-swatch MMU requires exactly two distinct tools.")
        selected=tuple(tools)
    else:
        if type(tool) is not int or not 1<=tool<count:
            raise WorkerError("Prusa offline painted native tool is invalid.")
        selected=(tool,)
    if (not changer or not 2<=count<=5 or
            not isinstance(tower,list) or len(tower)!=5 or
            any(type(x) not in (int,float) or not math.isfinite(x) for x in tower)):
        raise WorkerError("Prusa offline painted MMU tool and tower are invalid.")
    try:
        material=validate_flat_prusa_preset(filament,kind="filament")
        settings=validate_flat_prusa_preset(process,kind="print")
    except PrusaPresetError:
        raise WorkerError("Prusa offline colour profiles are invalid.") from None
    if (settings.get("wipe_tower")!="1" or
            settings.get("wipe_into_infill")!="0" or
            settings.get("wipe_into_objects")!="0"):
        raise WorkerError("Prusa offline painted MMU requires isolated native tower purging.")
    for name in ("temperature","first_layer_temperature"):
        values=material.get(name,"").split(",")
        if (len(values)!=count or any(not v.isascii() or not v.isdecimal() or
                not 0<=int(v)<=350 for v in values)):
            raise WorkerError("Prusa offline painted filament temperatures are invalid.")
    matrix=settings.get("wiping_volumes_matrix","").split(",")
    if len(matrix)!=count*count:
        raise WorkerError("Prusa offline painted purge matrix is incomplete.")
    for index,raw in enumerate(matrix):
        try:
            value=float(raw)
        except ValueError:
            raise WorkerError("Prusa offline painted purge entry is invalid.") from None
        same=index//count==index%count
        if (not math.isfinite(value) or not 0<=value<=1000 or
                (same and value!=0) or (not same and value<1)):
            raise WorkerError("Prusa offline painted purge entry is invalid.")
    from .prusa_colour_compound import qualified_prusa_colour_compound
    from .prusa_colour_fuzzy import qualified_prusa_colour_fuzzy
    compound = qualified_prusa_colour_compound(project)
    fuzzy = qualified_prusa_colour_fuzzy(project)
    if (compound and (dual or tuple(selected)!=(1,))) or (
            fuzzy and (dual or compound or tuple(selected)!=(1,))):
        raise WorkerError(
            "Mixed Prusa paint needs exactly one signed T1 native effect.")
    receipt=validate_prusa_material_candidate(
        project,printer_ini=printer,colour=True,tower=tower,
        compound_colour=compound,fuzzy_colour=fuzzy)
    if receipt["objects"]!=1 or receipt["tools"]!=tuple(sorted((1, *(v+1 for v in selected)))):
        raise WorkerError("Prusa offline painted native tool selection changed.")
    if dual:
        from .prusa_dual_partial import qualified_prusa_dual_colour_mode
        dual_mode = qualified_prusa_dual_colour_mode(project,selected)
    else:
        from .prusa_partial_surface import qualified_prusa_single_colour_mode
        mode = qualified_prusa_single_colour_mode(project, tool)
        if mode=="split_slanted":
            raise WorkerError(
                "Prusa MMU angled painted faces still lack independent native "
                "surface and wipe-tower qualification.")
        if mode=="split_curved" and tool!=1:
            raise WorkerError(
                "Native Prusa MMU curved painting is qualified for T1 only.")
    if (compound or fuzzy) and mode != "complete_wall":
        raise WorkerError(
            "Prusa colour with typed volumes or selective fuzzy needs "
            "the genuinely qualified complete T1 exterior wall.")
    return {**({"tools":list(selected)} if dual else {"tool":tool}),
            "tower":tower, "offline_only":True,
            "compound_volume": compound,
            "colour_fuzzy": fuzzy,
            "dual_partial": (dual and dual_mode == "split_opposite"),
            "partial_wall": (not dual and mode == "split_wall"),
            "partial_top": (not dual and mode == "split_top"),
            "partial_curved": (not dual and mode == "split_curved")}


def validate_prusa_offline_xl_colour_inputs(*, project, printer, filament, process,
                                           tool=None, tools=None):
    """Independently audit native XL single- or opposing-dual-wall painting.

    This is strictly offline. Physical tool pickup and printer start are not
    authorised. The source-mesh and toolpath auditors enforce both wall/tool
    attribution and no MMU purge or wipe tower.
    """
    count, same_nozzle = _qualified_topology(printer)
    if same_nozzle or not 2 <= count <= 8:
        raise WorkerError("Prusa painted XL/INDX needs independent native heads.")
    if tools is not None:
        if (tool is not None or not isinstance(tools, list) or
                len(tools) not in (2,4) or
                any(type(t) is not int or not 1 <= t <= 7 or t >= count
                    for t in tools) or len(set(tools)) != len(tools) or
                (len(tools)==4 and count!=5)):
            raise WorkerError("Prusa painted XL needs two or four distinct qualified native wall tools.")
        selected = tuple(tools)
    elif type(tool) is int and 1 <= tool <= 7 and tool < count:
        selected = (tool,)
    else:
        raise WorkerError("Prusa painted XL needs one valid alternate native head.")
    try:
        material = validate_flat_prusa_preset(filament, kind="filament")
        settings = validate_flat_prusa_preset(process, kind="print")
    except PrusaPresetError:
        raise WorkerError("Prusa painted XL native profiles are invalid.") from None
    if any(settings.get(key,"0").strip().lower() not in ("0","","false")
           for key in ("wipe_tower","wipe_into_infill","wipe_into_objects")):
        raise WorkerError("Prusa XL painting cannot use MMU purging or a wipe tower.")
    for key in ("temperature","first_layer_temperature"):
        values=material.get(key,"").split(",")
        if len(values)!=count or any(not v.isascii() or not v.isdecimal()
                                     or not 0<=int(v)<=350 for v in values):
            raise WorkerError("Prusa XL filament temperature vector is invalid.")
    receipt=validate_prusa_material_candidate(
        project, printer_ini=printer, colour=True, independent_colour=True)
    expected=tuple(sorted((1, *(t+1 for t in selected))))
    if receipt["objects"]!=1 or receipt["tools"]!=expected or receipt["wipe_tower"]:
        raise WorkerError("Prusa XL painted model tool mapping changed: native="+repr(receipt["tools"])+" expected="+repr(expected))
    if len(selected)==4:
        from .prusa_four_wall_audit import four_painted_wall_regions
        walls=four_painted_wall_regions(project)
        if selected!=tuple(walls["tools"][side] for side in
                           ("x_min","x_max","y_min","y_max")):
            raise WorkerError("Native four-wall source tool order changed.")
    elif len(selected)==2:
        from .prusa_colour_gcode_audit import _two_painted_wall_regions
        _two_painted_wall_regions(project,selected)
    else:
        from .prusa_partial_surface import qualified_prusa_single_colour_mode
        mode = qualified_prusa_single_colour_mode(project, selected[0])
        if mode in ("split_wall","split_top","split_slanted","split_curved") and count != 5:
            raise WorkerError(
                "Prusa partial-surface painting is qualified on XL5 only.")
        if mode in ("split_slanted","split_curved") and selected[0]!=1:
            raise WorkerError(
                "Native angled/curved painted facets require genuine XL5 T1 qualification.")
    return {**({"tools":list(selected)} if len(selected)>1
               else {"tool":selected[0]}),
            "partial_wall": len(selected)==1 and mode=="split_wall",
            "partial_top": len(selected)==1 and mode=="split_top",
            "partial_slanted": len(selected)==1 and mode=="split_slanted",
            "partial_curved": len(selected)==1 and mode=="split_curved",
            "offline_only":True,"wipe_tower":False}


def validate_prusa_offline_multi_colour_inputs(*, project, printer, filament,
                                               process, tools, tower):
    """Authenticate independently signed T1/T2 painted MMU ModelParts.

    A successful multi-object 3MF import is not proof of print-ready material
    separation: this admission requires source-derived disjoint complete
    walls, exact native MMU profile/colour topology and all three directional
    material purges in actual G-code after the CLI completes.
    """
    if tools != [1,2]:
        raise WorkerError("Qualified two-object native MMU painting requires T1 and T2.")
    count,changer=_qualified_topology(printer)
    if (not changer or not 3<=count<=5 or
            not isinstance(tower,list) or len(tower)!=5 or
            any(type(n) not in (int,float) or not math.isfinite(n)
                for n in tower)):
        raise WorkerError("Prusa painted two-model native MMU topology is invalid.")
    try:
        material=validate_flat_prusa_preset(filament,kind="filament")
        settings=validate_flat_prusa_preset(process,kind="print")
    except PrusaPresetError:
        raise WorkerError("Prusa multi-model colour native profiles are invalid.") from None
    if (settings.get("wipe_tower")!="1" or
            settings.get("wipe_into_infill")!="0" or
            settings.get("wipe_into_objects")!="0"):
        raise WorkerError("Prusa multi-model paint requires isolated native purge tower.")
    for key in ("temperature","first_layer_temperature"):
        values=material.get(key,"").split(",")
        if (len(values)!=count or any(not value.isascii() or
                not value.isdecimal() or not 0<=int(value)<=350
                for value in values)):
            raise WorkerError("Prusa multi-model painted filament vector is invalid.")
    matrix=settings.get("wiping_volumes_matrix","").split(",")
    if len(matrix)!=count*count:
        raise WorkerError("Prusa multi-model paint requires complete purge matrix.")
    for index,text in enumerate(matrix):
        try:
            value=float(text)
        except ValueError:
            raise WorkerError("Prusa multi-model purge volume is invalid.") from None
        diagonal=index//count==index%count
        if (not math.isfinite(value) or not 0<=value<=1000 or
                (diagonal and value!=0) or (not diagonal and value<1)):
            raise WorkerError("Prusa multi-model purge volume is unqualified.")
    from .prusa_multi_colour import inspect_prusa_multi_colour
    signed=inspect_prusa_multi_colour(
        project,printer_ini=printer,tower=tower)
    if len(signed)!=2 or tuple(row["tool"] for row in signed)!=(1,2):
        raise WorkerError("Prusa independently painted source tool order changed.")
    return {"tools":[1,2],"tower":tower,"offline_only":True}
