"""Model-neutral native preset constraints for exact engine versions.

Constraints describe known engine parser limits, NOT supported printer models.
They are advisory preflight diagnostics and never clamp or rewrite native data.
The real executable and administrator profile approval remain authoritative.
"""
import json
import math
from dataclasses import dataclass


class SlicerNativeCompatibilityError(ValueError):
    pass


@dataclass(frozen=True)
class NumericConstraint:
    minimum: float
    maximum: float
    unit: str = ""

# Add constraints only when verified against an exact real engine release.
# Unknown engine versions and settings are not assumed compatible: the actual
# engine acceptance fixture must decide whether to approve them.
NATIVE_NUMERIC_CONSTRAINTS = {
    ("orcaslicer", "2.4.2", "printer"): {
        "retraction_distances_when_cut": NumericConstraint(10, 18, "mm"),
    },
}


def check_native_compatibility(engine, version, kind, raw):
    """Report known native-engine validation problems for ANY printer profile.

    A warning never proves that another printer/profile combination is safe.
    """
    constraints = NATIVE_NUMERIC_CONSTRAINTS.get((engine, version, kind), {})
    if not constraints:
        return
    try:
        profile = json.loads(raw)
    except (ValueError, TypeError, UnicodeDecodeError):
        return  # Structural JSON validation happens independently.
    if not isinstance(profile, dict):
        return
    for key, rule in constraints.items():
        if key not in profile:
            continue
        supplied = profile[key]
        values = supplied if isinstance(supplied, list) else [supplied]
        for item in values:
            try:
                value = float(item) if not isinstance(item, bool) else math.nan
            except (TypeError, ValueError, OverflowError):
                continue  # Allow the real native validator to diagnose type errors.
            if math.isfinite(value) and not rule.minimum <= value <= rule.maximum:
                unit = (" " + rule.unit) if rule.unit else ""
                raise SlicerNativeCompatibilityError(
                    f"{engine} {version} rejects {kind} profile setting "
                    f"{key}={item} (accepted range: {rule.minimum:g}–{rule.maximum:g}{unit}). "
                    "This setting is incompatible with the selected slicing engine version, "
                    "regardless of printer manufacturer or model. Review a compatible "
                    "engine-native profile or create a separately named, administrator-"
                    "reviewed custom candidate. MakerVault never changes it automatically."
                )
