"""Non-mutating, version-scoped engine-native preset compatibility diagnostics.

Do not clamp, rewrite or implicitly approve manufacturer settings. These are
preflight hints for errors already rejected by the real engine.
"""
import json
import math


class SlicerNativeCompatibilityError(ValueError):
    pass


def check_native_compatibility(engine, version, kind, raw):
    """Identify the known Orca 2.4.2 retraction range mismatch up front."""
    if (engine, version, kind) != ("orcaslicer", "2.4.2", "printer"):
        return
    try:
        profile = json.loads(raw)
    except (ValueError, TypeError, UnicodeDecodeError):
        return  # Native JSON validation is performed separately.
    if not isinstance(profile, dict) or "retraction_distances_when_cut" not in profile:
        return
    supplied = profile["retraction_distances_when_cut"]
    values = supplied if isinstance(supplied, list) else [supplied]
    if not values:
        return
    for item in values:
        try:
            value = float(item) if not isinstance(item, bool) else math.nan
        except (TypeError, ValueError, OverflowError):
            return
        if math.isfinite(value) and not 10 <= value <= 18:
            raise SlicerNativeCompatibilityError(
                "OrcaSlicer 2.4.2 rejects printer setting "
                f"retraction_distances_when_cut={item} (accepted range: 10–18 mm). "
                "The upstream Creality K2 preset contains an incompatible value. "
                "Review the printer manufacturer's filament-change requirements "
                "and import a separately named, administrator-reviewed compatible "
                "profile; MakerVault will not change the setting automatically."
            )
