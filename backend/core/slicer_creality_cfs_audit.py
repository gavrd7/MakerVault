"""Read-only evidence for a saved Creality slice's selected physical CFS bays.

A slicer tool is NOT a nozzle and is NOT a CFS material ID. The mapping below
only checks that the selected database slot still corresponds to a real,
freshly observed CFS bay. It does not authorise print submission.
"""
import re


class CrealityCfsAuditError(ValueError):
    pass


_COLOUR = re.compile(r"#[0-9a-fA-F]{6}\Z")


def audit_creality_cfs_assignments(objects, slot_records, cfs_context, *, printer_id):
    """Verify saved logical-tool order against live CFS bay coordinates.

    slot_records must be the owned printer's PrinterFilamentSlot rows resolved
    by primary key, NOT a colour/name-based lookup. Creality's 1-based box ID
    and 0-based material ID come exclusively from fresh native telemetry.
    """
    if not isinstance(objects, list) or len(objects) != 2:
        raise CrealityCfsAuditError("This audit requires exactly two Creality models.")
    if not isinstance(cfs_context, dict) or cfs_context.get("verified") is not True or cfs_context.get("connected") is not True:
        raise CrealityCfsAuditError("Fresh native K2 CFS telemetry is required.")
    rows = {}
    for row in slot_records:
        ident = str(getattr(row, "pk", ""))
        if ident in rows:
            raise CrealityCfsAuditError("Duplicate physical slot record.")
        if (str(getattr(row, "printer_id", "")) != str(printer_id)
                or getattr(row, "system", None) != "creality_cfs"
                or getattr(row, "is_loaded", None) is not True):
            raise CrealityCfsAuditError("Selected slot is not a loaded CFS bay on this printer.")
        rows[ident] = row
    telemetry = {}
    for slot in cfs_context.get("slots", []):
        if not isinstance(slot, dict):
            continue
        key = (slot.get("box_id"), slot.get("slot_id"))
        if key in telemetry:
            raise CrealityCfsAuditError("Duplicate CFS bay in native telemetry.")
        telemetry[key] = slot
    mapping = []
    seen_slots = set()
    seen_bays = set()
    for item in objects:
        if not isinstance(item, dict) or not isinstance(item.get("material_slot"), dict):
            raise CrealityCfsAuditError("Every model must select a physical CFS slot.")
        selected = item["material_slot"]
        if str(selected.get("printer_id")) != str(printer_id):
            raise CrealityCfsAuditError("Model assignment belongs to another printer.")
        ident = selected.get("slot_id")
        if not isinstance(ident, str) or ident not in rows:
            raise CrealityCfsAuditError("Selected physical CFS slot could not be resolved.")
        row = rows[ident]
        if type(selected.get("slot_index")) is not int or selected["slot_index"] != row.slot_index:
            raise CrealityCfsAuditError("Saved physical CFS slot index has changed.")
        if ident in seen_slots:
            raise CrealityCfsAuditError("Two-material audit needs two distinct CFS slots.")
        seen_slots.add(ident)
        key = (row.unit_index + 1, row.slot_index)
        if key in seen_bays:
            raise CrealityCfsAuditError("Two model assignments resolve to the same CFS bay.")
        seen_bays.add(key)
        live = telemetry.get(key)
        if live is None:
            raise CrealityCfsAuditError("Selected CFS bay is absent from fresh native telemetry.")
        colour = item.get("color")
        current = live.get("color_hex")
        if (not isinstance(colour, str) or not _COLOUR.fullmatch(colour)
                or not isinstance(current, str) or not _COLOUR.fullmatch(current)
                or colour.upper() != current.upper()):
            raise CrealityCfsAuditError("Selected CFS bay colour differs from the sliced model.")
        if not str(live.get("material") or "").strip():
            raise CrealityCfsAuditError("Selected CFS material type is unknown.")
        index = len(mapping)
        mapping.append({
            "tool_index": index,
            "slot_label": live["label"],
            "box_id": key[0],
            "material_id": key[1],
            "material": str(live["material"]),
            "colour": current.upper(),
        })
    return {
        "verified_live_slot_identity": True,
        "printer_submission_verified": False,
        "mapping": mapping,
        "note": "Read-only slot identity check; firmware changeover and print start remain unverified.",
    }
