"""Conservative, curated reference links for identifiable component families.

These links document a compatible part family, not the item's actual maker.
Never apply to generic parts or overwrite an existing user reference.
"""
from .models import ComponentModel

# Maintained manufacturer documentation for well-defined part identifiers.
VERIFIED_FAMILY_REFERENCES = {
    "LM358": "https://www.ti.com/product/LM358",
    "LM393": "https://www.ti.com/product/LM393",
    "NE555": "https://www.ti.com/product/NE555",
    "INA219": "https://www.ti.com/product/INA219",
    "DRV8825": "https://www.ti.com/product/DRV8825",
    "MCP23017": "https://www.microchip.com/en-us/product/mcp23017",
    "MCP2515": "https://www.microchip.com/en-us/product/mcp2515",
    "VL53L0X": "https://www.st.com/en/imaging-and-photonics-solutions/vl53l0x.html",
    "VL53L1X": "https://www.st.com/en/imaging-and-photonics-solutions/vl53l1x",
}


# Values verified against manufacturer chip-family pages. A breakout board
# may have different limits; only apply to unambiguous standalone chips.
VERIFIED_FAMILY_TECHNICAL_FIELDS = {
    "MCP23017": {"interface": "I2C", "gpio_count": 16},
    "VL53L0X": {"interface": "I2C", "maximum_range_m": 2},
    "INA219": {"interface": "I2C"},
}


def fill_verified_family_fields(component, specifications):
    part = str(component.part_number or "").strip().upper()
    fields = VERIFIED_FAMILY_TECHNICAL_FIELDS.get(part, {})
    name = str(component.name or "").lower()
    if any(term in name for term in ("breakout", "carrier", "shield", "board", "module")):
        return False
    added = []
    for key, value in fields.items():
        if specifications.get(key) in (None, "", [], {}):
            specifications[key] = value
            added.append(key)
    if added:
        sources = dict(specifications.get("technical_field_sources") or {})
        for key in added:
            sources[key] = VERIFIED_FAMILY_REFERENCES[part]
        specifications["technical_field_sources"] = sources
    return bool(added)


def enrich_component_reference_links(*, limit=80, cursor=None):
    """Advance through all components; only enrich exact listed part numbers."""
    queryset = ComponentModel.objects.order_by("pk")
    if cursor:
        queryset = queryset.filter(pk__gt=cursor)
    limit = max(1, min(int(limit), 200))
    batch = list(queryset[:limit + 1])
    more = len(batch) > limit
    batch = batch[:limit]
    enriched = 0
    for component in batch:
        number = str(component.part_number or "").strip().upper()
        url = VERIFIED_FAMILY_REFERENCES.get(number)
        if not url:
            continue
        specs = dict(component.specifications or {})
        # Existing reference, datasheet and manual image/source information
        # must always take precedence over our suggested manufacturer family.
        changed = fill_verified_family_fields(component, specs)
        if not any(specs.get(key) for key in ("reference_url", "datasheet_url", "technical_source_url")):
            specs["reference_url"] = url
            specs["reference_provider"] = "Manufacturer family reference (not verified component brand)"
            specs["reference_match_type"] = "exact-part-number-family"
            changed = True
        if changed:
            component.specifications = specs
            component.save(update_fields=["specifications", "updated_at"])
            enriched += 1
    return {
        "status": "limit-reached" if more else "complete",
        "processed": len(batch),
        "enriched": enriched,
        "next_cursor": str(batch[-1].pk) if more and batch else None,
    }
