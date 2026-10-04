from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def fit_model_decimal(instance, field_name: str, value):
    """Round an incoming numeric value to the precision declared by a model DecimalField."""
    if value in (None, ""):
        return value
    field = instance._meta.get_field(field_name)
    decimal_places = getattr(field, "decimal_places", None)
    if decimal_places is None:
        return value
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return value
    quantum = Decimal("1").scaleb(-int(decimal_places))
    return parsed.quantize(quantum, rounding=ROUND_HALF_UP)
