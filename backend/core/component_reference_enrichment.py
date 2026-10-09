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
        if any(specs.get(key) for key in ("reference_url", "datasheet_url", "technical_source_url")):
            continue
        specs["reference_url"] = url
        specs["reference_provider"] = "Manufacturer family reference (not verified component brand)"
        specs["reference_match_type"] = "exact-part-number-family"
        component.specifications = specs
        component.save(update_fields=["specifications", "updated_at"])
        enriched += 1
    return {
        "status": "limit-reached" if more else "complete",
        "processed": len(batch),
        "enriched": enriched,
        "next_cursor": str(batch[-1].pk) if more and batch else None,
    }
