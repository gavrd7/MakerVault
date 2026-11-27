"""Offline native Prusa purge matrix compiler, not printer dispatch.

Prusa's wiping_volumes_matrix is ordered by source then destination logical
tool, in cubic millimetres. Do not substitute physical nozzle count for MMU
logical slots. Exact CLI behaviour is qualified separately.
"""
import math

from .slicer_prusa_machine_topology import prusa_machine_topology
from .slicer_prusa_native_resolution import parse_prusa_profile
from .slicer_profiles import SlicerProfileError


def compile_prusa_purge_matrix(printer_ini, process_ini, matrix):
    topology = prusa_machine_topology(printer_ini)
    count = topology["logical_tool_count"]
    if count < 2 or not isinstance(matrix, (tuple,list)) or len(matrix) != count:
        raise SlicerProfileError("Prusa purge matrix must match native logical tools.")
    values = []
    for source, row in enumerate(matrix):
        if not isinstance(row, (tuple,list)) or len(row) != count:
            raise SlicerProfileError("Prusa purge matrix must be square.")
        for target, value in enumerate(row):
            if (type(value) not in (int,float) or not math.isfinite(value)
                    or not 0 <= value <= 1000
                    or (source == target and value != 0)
                    or (source != target and value < 1)):
                raise SlicerProfileError("Prusa purge matrix has an invalid transition volume.")
            values.append(format(value, ".3f").rstrip("0").rstrip("."))
    settings = parse_prusa_profile(process_ini, "process")
    settings["wiping_volumes_matrix"] = ",".join(values)
    settings["wipe_tower"] = "1"
    # Explicitly disable model flushing for this isolated tower-only experiment.
    settings["wipe_into_infill"] = "0"
    settings["wipe_into_objects"] = "0"
    output = "".join(f"{key} = {value}\n" for key,value in sorted(settings.items())).encode()
    parse_prusa_profile(output, "process")
    return output
