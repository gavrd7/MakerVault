"""Strict Creality Print 7.3.1 native multi-STL filament arguments.

Upstream SliceCommand.cpp accepts one 1-based filament ID per input STL/OBJ.
Do not use --load-filament-ids for 3MF projects: Creality rejects that
combination. These arguments use logical tools, never physical CFS bay IDs.
No printer command or network operation is performed here.
"""
from pathlib import Path


class CrealityMaterialRouteError(ValueError):
    pass


def native_stl_material_arguments(models, filament_profiles, tool_ids):
    """Build an explicitly ordered multi-STL, multi-filament argument segment.

    All inputs must already be worker-owned scratch file paths. The caller
    must establish physical-slot-to-logical-tool bindings separately.
    """
    if not isinstance(models, (tuple, list)) or not 2 <= len(models) <= 12:
        raise CrealityMaterialRouteError("Two to twelve native STL models are required.")
    if not isinstance(filament_profiles, (tuple, list)) or not 2 <= len(filament_profiles) <= 16:
        raise CrealityMaterialRouteError("Two to sixteen native filament presets are required.")
    if not isinstance(tool_ids, (tuple, list)) or len(tool_ids) != len(models):
        raise CrealityMaterialRouteError("One logical filament ID is required per STL.")
    if any(type(tool) is not int or not 1 <= tool <= len(filament_profiles) for tool in tool_ids):
        raise CrealityMaterialRouteError("Creality filament IDs must be one-based palette indices.")
    if len(set(tool_ids)) < 2:
        raise CrealityMaterialRouteError("Multi-material slicing requires two distinct logical tools.")
    models = [Path(path) for path in models]
    filaments = [Path(path) for path in filament_profiles]
    if any(path.suffix.lower() != ".stl" for path in models):
        raise CrealityMaterialRouteError("Creality multi-material STL arguments cannot contain a 3MF.")
    if any(path.suffix.lower() != ".json" for path in filaments):
        raise CrealityMaterialRouteError("Native Creality filament presets must be JSON.")
    if any(not path.is_absolute() or not path.is_file() or path.is_symlink()
           for path in models + filaments):
        raise CrealityMaterialRouteError("Every native input must be a regular absolute scratch file.")
    # No shell is involved; semicolon separates preset filenames inside one arg.
    return [
        "--load-filaments", ";".join(map(str, filaments)),
        "--load-filament-ids", ",".join(map(str, tool_ids)),
        *map(str, models),
    ]
