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
    receipt=validate_prusa_material_candidate(
        project,printer_ini=printer,colour=True,tower=tower)
    if receipt["objects"]!=1 or receipt["tools"]!=tuple(sorted((1, *(v+1 for v in selected)))):
        raise WorkerError("Prusa offline painted native tool selection changed.")
    if dual:
        from .prusa_colour_gcode_audit import _two_painted_wall_regions
        _two_painted_wall_regions(project,selected)
    else:
        from .prusa_colour_gcode_audit import _wall_regions
        _wall_regions(project,tool)
    return {**({"tools":list(selected)} if dual else {"tool":tool}),
            "tower":tower, "offline_only":True}


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
        if (tool is not None or not isinstance(tools, list) or len(tools) != 2
                or any(type(t) is not int or not 1 <= t <= 4 or t >= count
                       for t in tools) or len(set(tools)) != 2):
            raise WorkerError("Prusa painted XL needs two distinct native wall tools.")
        selected = tuple(tools)
    elif type(tool) is int and 1 <= tool <= 4 and tool < count:
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
        raise WorkerError("Prusa XL painted model tool mapping changed.")
    if len(selected)==2:
        from .prusa_colour_gcode_audit import _two_painted_wall_regions
        _two_painted_wall_regions(project,selected)
    else:
        from .prusa_colour_gcode_audit import _wall_regions
        _wall_regions(project,selected[0])
    return {**({"tools":list(selected)} if len(selected)==2
               else {"tool":selected[0]}),
            "offline_only":True,"wipe_tower":False}
