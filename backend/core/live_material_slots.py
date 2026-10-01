from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.utils import timezone

from .models import PrinterFilamentSlot


SUPPORTED_SYSTEMS = {value for value, _label in PrinterFilamentSlot.SYSTEMS}


def _decimal(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _system_connected(snapshot: dict, system: str) -> bool:
    metadata = snapshot.get("source_metadata") or {}
    if system == "bambu_ams":
        return bool(metadata.get("ams_connected"))
    if system == "creality_cfs":
        return bool(metadata.get("cfs_connected"))
    if system == "flashforge_station":
        return bool(metadata.get("material_station_slots_observed"))
    if system == "anycubic_ace":
        return bool(metadata.get("ace_slots_observed"))
    return bool(snapshot.get("materials"))


def sync_live_material_slots(connection, snapshot: dict) -> dict:
    """Persist provider-neutral live material slots without guessing spool identity.

    Adapters report material observations in a shared contract. This function
    updates the physical printer's slot state while preserving any spool link
    that the user previously confirmed. It never creates a Spool automatically.
    """
    materials = snapshot.get("materials")
    if not isinstance(materials, list):
        materials = []

    systems = {
        str(row.get("system") or "").strip()
        for row in materials
        if isinstance(row, dict) and str(row.get("system") or "").strip() in SUPPORTED_SYSTEMS
    }
    if connection.adapter == "bambu_local":
        systems.add("bambu_ams")
    elif connection.adapter == "creality_local":
        systems.add("creality_cfs")
    elif connection.adapter == "flashforge":
        systems.add("flashforge_station")
    elif connection.adapter == "anycubic":
        systems.add("anycubic_ace")

    if not systems:
        return {"systems": [], "loaded_slots": 0, "updated_spool_weights": 0}

    now = timezone.now()
    seen = {system: set() for system in systems}
    loaded = 0
    updated_weights = 0

    for raw in materials:
        if not isinstance(raw, dict):
            continue
        system = str(raw.get("system") or "").strip()
        if system not in systems or system not in SUPPORTED_SYSTEMS:
            continue
        try:
            unit_index = max(int(raw.get("unit_index") or 0), 0)
            slot_index = max(int(raw.get("slot_index") or 0), 0)
        except (TypeError, ValueError):
            continue

        seen[system].add((unit_index, slot_index))
        existing = PrinterFilamentSlot.objects.select_related("spool__filament").filter(
            printer=connection.printer,
            system=system,
            unit_index=unit_index,
            slot_index=slot_index,
        ).first()

        linked_spool = existing.spool if existing and existing.spool_id else None
        remaining_percent = _decimal(raw.get("remaining_percent"))
        remaining_weight = existing.remaining_weight_g if existing else None
        if linked_spool and remaining_percent is not None:
            basis = linked_spool.initial_weight_g or linked_spool.filament.nominal_weight_g
            if basis is not None:
                remaining_weight = (basis * remaining_percent / Decimal("100")).quantize(Decimal("0.01"))
                if linked_spool.remaining_weight_g != remaining_weight:
                    linked_spool.remaining_weight_g = remaining_weight
                    linked_spool.save(update_fields=["remaining_weight_g", "updated_at"])
                    updated_weights += 1

        previous = dict(existing.metadata or {}) if existing else {}
        metadata = {
            **previous,
            "source": "live_printer",
            "adapter": connection.adapter,
            "vendor": str(raw.get("vendor") or ""),
            "product_name": str(raw.get("product_name") or ""),
            "material_code": str(raw.get("material_code") or ""),
            "rfid_detected": bool(raw.get("rfid_detected")),
            "remaining_percent": float(remaining_percent) if remaining_percent is not None else None,
            "selected": bool(raw.get("selected")),
            "min_temp_c": raw.get("min_temp_c"),
            "max_temp_c": raw.get("max_temp_c"),
            "box_temperature_c": raw.get("box_temperature_c"),
            "box_humidity_percent": raw.get("box_humidity_percent"),
            "live_connection_id": str(connection.id),
        }

        PrinterFilamentSlot.objects.update_or_create(
            printer=connection.printer,
            system=system,
            unit_index=unit_index,
            slot_index=slot_index,
            defaults={
                "spool": linked_spool,
                "external_ref": f"live:{connection.adapter}:{unit_index}:{slot_index}",
                "rfid_uid": str(raw.get("rfid_uid") or "").strip().upper(),
                "material": str(raw.get("material") or "").strip()[:80],
                "color_name": str(raw.get("product_name") or "").strip()[:120],
                "color_hex": str(raw.get("color_hex") or "").strip()[:9],
                "remaining_weight_g": remaining_weight,
                "is_loaded": True,
                "last_seen_at": now,
                "metadata": metadata,
            },
        )
        loaded += 1

    for system in systems:
        if not _system_connected(snapshot, system):
            continue
        for slot in PrinterFilamentSlot.objects.filter(
            printer=connection.printer,
            system=system,
            is_loaded=True,
        ):
            if (slot.unit_index, slot.slot_index) in seen.get(system, set()):
                continue
            slot.is_loaded = False
            slot.spool = None
            slot.remaining_weight_g = None
            slot.last_seen_at = now
            metadata = dict(slot.metadata or {})
            metadata["source"] = "live_printer"
            metadata["adapter"] = connection.adapter
            metadata["selected"] = False
            metadata["remaining_percent"] = None
            slot.metadata = metadata
            slot.save(update_fields=[
                "is_loaded", "spool", "remaining_weight_g",
                "last_seen_at", "metadata", "updated_at",
            ])

    return {
        "systems": sorted(systems),
        "loaded_slots": loaded,
        "updated_spool_weights": updated_weights,
    }
