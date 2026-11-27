"""Prusa-only draft schema for virtual native tools, independent of hardware.

Saving an incomplete selection is permitted. Worker admission is a separate,
strict owner-scoped validation; no physical slot or printer identity is inferred.
"""
import math
import uuid

from .slicer_profiles import SlicerProfileError


def validate_prusa_native_tools(raw):
    required={"version", "mode", "tool_count", "filament_profile_ids",
              "model_tools", "purge_matrix"}
    if not isinstance(raw, dict) or not required.issubset(raw) or (
            set(raw)-required-{"colour_tools"}):
        raise SlicerProfileError("Invalid Prusa native tool configuration.")
    count = raw["tool_count"]
    if type(raw["version"]) is not int or raw["version"] != 1 or type(count) is not int or not 2 <= count <= (8 if raw["mode"] == "indx" else 5) or (
            raw["mode"] not in ("mmu", "xl", "indx")):
        raise SlicerProfileError("Unsupported Prusa native tool configuration.")
    filaments = raw["filament_profile_ids"]
    if not isinstance(filaments, list) or len(filaments) != count:
        raise SlicerProfileError("Prusa needs one filament selection per native tool.")
    profile_ids = []
    for value in filaments:
        if value == "":
            profile_ids.append("")
        elif isinstance(value, str):
            try:
                profile_ids.append(str(uuid.UUID(value)))
            except ValueError:
                raise SlicerProfileError("Invalid Prusa filament profile selection.") from None
        else:
            raise SlicerProfileError("Invalid Prusa filament profile selection.")
    rows = raw["model_tools"]
    if not isinstance(rows, list) or len(rows) > 200:
        raise SlicerProfileError("Invalid Prusa per-model tool assignments.")
    selected = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"instance_id", "tool"}:
            raise SlicerProfileError("Invalid Prusa model tool assignment.")
        try:
            model_id = str(uuid.UUID(str(row["instance_id"])))
        except (ValueError, TypeError, AttributeError):
            raise SlicerProfileError("Invalid Prusa model identity.") from None
        tool = row["tool"]
        if model_id in seen or type(tool) is not int or not 1 <= tool <= count:
            raise SlicerProfileError("Invalid or duplicate Prusa model tool assignment.")
        seen.add(model_id)
        selected.append({"instance_id":model_id,"tool":tool})
    colour_rows=raw.get("colour_tools",[])
    if not isinstance(colour_rows,list) or len(colour_rows)>min(count-1,4):
        raise SlicerProfileError("Invalid Prusa colour tool assignments.")
    colour_tools=[]
    paint_slots=set()
    for row in colour_rows:
        if not isinstance(row,dict) or set(row)!={"slot","tool"}:
            raise SlicerProfileError("Invalid Prusa painted colour assignment.")
        slot,tool=row["slot"],row["tool"]
        if (type(slot) is not int or not 0<=slot<16 or slot in paint_slots or
                type(tool) is not int or not 2<=tool<=min(count,5)):
            raise SlicerProfileError("Prusa 2.9.7 painted facets use native T1–T4 states; other heads remain available for model tools.")
        paint_slots.add(slot)
        colour_tools.append({"slot":slot,"tool":tool})
    matrix = raw["purge_matrix"]
    if raw["mode"] in ("xl", "indx"):
        if matrix is not None:
            raise SlicerProfileError("Independent heads do not use an MMU purge matrix.")
    else:
        if not isinstance(matrix, list) or len(matrix) != count:
            raise SlicerProfileError("Prusa MMU needs a complete directional matrix.")
        checked = []
        for i, row in enumerate(matrix):
            if not isinstance(row, list) or len(row) != count:
                raise SlicerProfileError("Prusa MMU purge matrix must be square.")
            values = []
            for j, value in enumerate(row):
                if i == j:
                    if type(value) not in (int,float) or value != 0:
                        raise SlicerProfileError("MMU same-tool purge must be zero.")
                    values.append(0)
                    continue
                if value is None:
                    values.append(None)
                elif type(value) not in (int,float) or not math.isfinite(value) or not 1 <= value <= 1000:
                    raise SlicerProfileError("Prusa MMU purge volume must be 1–1000 mm³.")
                else:
                    values.append(round(float(value),3))
            checked.append(values)
        matrix = checked
    return {
        "version":1,"mode":raw["mode"],"tool_count":count,
        "filament_profile_ids":profile_ids,
        "model_tools":selected,"purge_matrix":matrix,
        **({"colour_tools":colour_tools} if "colour_tools" in raw else {}),
    }
