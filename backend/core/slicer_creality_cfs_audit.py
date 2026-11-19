"""Read-only evidence for a saved Creality slice's selected physical CFS bays.

A slicer tool is NOT a nozzle and is NOT a CFS material ID. The mapping below
only checks that the selected database slot still corresponds to a real,
freshly observed CFS bay. It does not authorise print submission.
"""
import re


class CrealityCfsAuditError(ValueError):
    pass


_COLOUR = re.compile(r"#[0-9a-fA-F]{6}\Z")


def creality_cfs_audit_objects(objects, *, printer_id):
    """Expand one two-colour painted object to two *logical* filament records.

    Creality uses T0 for the object's assigned base filament, and T1 for
    paint-bound facets. This transformation is for read-only slot validation;
    it never creates extra printable models or substitutes colour for a bay ID.
    """
    if not isinstance(objects, list):
        raise CrealityCfsAuditError("Saved Creality plate is invalid.")
    if len(objects) == 2:
        if any(not isinstance(obj, dict) or
               (obj.get("colour_paint") or {}).get("regions") or
               (obj.get("colour_paint") or {}).get("faces") for obj in objects):
            raise CrealityCfsAuditError("Two-model CFS audit cannot include painted facets.")
        return objects
    if len(objects) != 1 or not isinstance(objects[0], dict):
        raise CrealityCfsAuditError("Expected two models or one two-filament painted model.")
    obj = objects[0]
    base = obj.get("material_slot")
    paint = obj.get("colour_paint") or {}
    if not isinstance(base, dict) or not isinstance(paint, dict):
        raise CrealityCfsAuditError("Painted model needs an assigned base CFS slot.")
    from .slicer_colour_painting import validate_colour_paint
    try:
        data = validate_colour_paint(paint)
    except ValueError as exc:
        raise CrealityCfsAuditError("Saved colour-painted regions are invalid.") from exc
    if data.get("version") != 2 or not data["regions"]:
        raise CrealityCfsAuditError("Creality painted CFS audit requires native surface regions.")
    swatches = [data["palette"][index] for index in
                {region["slot"] for region in data["regions"]}]
    secondary = [swatch for swatch in swatches
                 if swatch.get("slot_id") != base.get("slot_id")]
    unique = {swatch.get("slot_id") for swatch in secondary}
    if len(unique) != 1 or None in unique:
        raise CrealityCfsAuditError(
            "Painted Creality test requires exactly one additional assigned CFS slot.")
    if any(str(swatch.get("printer_id")) != str(printer_id) for swatch in swatches):
        raise CrealityCfsAuditError("Painted swatch belongs to a different printer.")
    selected = secondary[0]
    if any(swatch.get("color", "").upper() != selected["color"].upper()
           or swatch.get("slot_index") != selected.get("slot_index")
           for swatch in secondary):
        raise CrealityCfsAuditError("Painted swatches disagree about the selected CFS bay.")
    return [obj, {
        "material_slot": {
            "printer_id": selected["printer_id"],
            "slot_id": selected["slot_id"],
            "slot_index": selected["slot_index"],
        },
        "color": selected["color"],
    }]


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


def audit_creality_gcode_for_cfs(job, mapping_report, raw):
    """Tie a completed offline Creality G-code file to the selected live bays.

    This cross-checks the actual generated toolpath and filament headers. It
    never authorises transport or firmware operation, even on success.
    """
    import hashlib
    from .gcode_analysis import analyse_text
    from .slicer_material_gcode_audit import (
        audit_native_tool_usage, MaterialGcodeAuditError,
    )

    asset = getattr(job, "output_asset", None)
    if (getattr(job, "engine", None) != "crealityprint"
            or getattr(job, "status", None) != "completed"
            or asset is None
            or str((asset.metadata or {}).get("slice_job_id")) != str(job.pk)
            or str((asset.metadata or {}).get("printer_id")) != str(job.printer_id)
            or (asset.metadata or {}).get("multi_material_test") is not True
            or (asset.metadata or {}).get("printer_submission_verified") is not False):
        raise CrealityCfsAuditError("No matching completed, unapproved Creality test G-code.")
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 64 * 1024 * 1024:
        raise CrealityCfsAuditError("G-code is empty or exceeds the supported audit size.")
    if not getattr(asset, "sha256", None) or hashlib.sha256(raw).hexdigest() != asset.sha256:
        raise CrealityCfsAuditError("Saved G-code SHA-256 does not match the completed slice.")
    try:
        gcode = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CrealityCfsAuditError("Creality G-code must be plain UTF-8 text.") from exc
    try:
        tools = audit_native_tool_usage(gcode, expected_tools={0, 1})
    except MaterialGcodeAuditError as exc:
        raise CrealityCfsAuditError("G-code tool/extrusion audit failed: " + str(exc)) from exc
    # Reject unexpected depositing tools, even if both expected ones appear.
    if set(tools["extruding_moves"]) != {0, 1}:
        raise CrealityCfsAuditError("G-code extrudes on unexpected logical tools.")
    report = analyse_text(gcode, truncated=False)
    filaments = report.get("filaments") or {}
    declared = filaments.get("requirements") or []
    by_tool = {row.get("tool_index"): row for row in declared if isinstance(row, dict)}
    slots = mapping_report.get("mapping") or []
    if (len(slots) != 2 or {row["tool_index"] for row in slots} != {0, 1}
            or any(tool not in by_tool for tool in (0, 1))):
        raise CrealityCfsAuditError("Saved tools and G-code filament declarations disagree.")
    for row in slots:
        requirement = by_tool[row["tool_index"]]
        colour = requirement.get("color_hex")
        native_material = str(requirement.get("material") or "").upper()
        live_material = str(row.get("material") or "").strip().upper()
        if not colour or colour.upper() != row["colour"]:
            raise CrealityCfsAuditError("G-code filament colour differs from the verified CFS bay.")
        # Creality CFS usually reports the polymer family (PLA), while the
        # native slicer may declare the subtype PLA-Silk. Never equate PETG/PLA.
        if not native_material or not live_material or not (
            native_material == live_material
            or native_material.startswith(live_material + "-")
            or native_material.startswith(live_material + "+")
        ):
            raise CrealityCfsAuditError("G-code filament family differs from the verified CFS material.")
    return {
        **mapping_report,
        "verified_gcode_sha256": asset.sha256,
        "verified_gcode_tools": sorted(tools["extruding_moves"]),
        "gcode_material_preflight_passed": True,
        "printer_submission_verified": False,
        "note": "G-code and live CFS slot identities agree; firmware routing and print start remain unverified.",
    }
