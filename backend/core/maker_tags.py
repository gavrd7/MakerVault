from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import ValidationError

from .models import (
    PrintedPart,
    InventoryItem,
    MakerTag,
    Printer,
    PrintingLocation,
    Project,
    Spool,
)


@dataclass(frozen=True)
class TagTargetDefinition:
    key: str
    label: str
    model: type


TAG_TECHNOLOGIES = [
    ("", "Auto / unspecified"),
    ("ndef", "NDEF / phone-tappable NFC"),
    ("iso14443", "NFC / ISO 14443 UID"),
    ("iso15693", "NFC-V / ISO 15693 UID"),
    ("mifare", "MIFARE / DESFire reader identity"),
    ("lf_rfid", "LF RFID (125/134 kHz)"),
    ("uhf_epc", "UHF / EPC Gen2 / RAIN RFID"),
    ("usb_hid", "USB / HID reader output"),
    ("other", "Other reader/tag technology"),
]


TARGETS = {
    "printed_part": TagTargetDefinition("printed_part", "Printed part", PrintedPart),
    "inventory": TagTargetDefinition("inventory", "Inventory item", InventoryItem),
    "spool": TagTargetDefinition("spool", "Spool", Spool),
    "printer": TagTargetDefinition("printer", "Printer", Printer),
    "project": TagTargetDefinition("project", "Project", Project),
    "location": TagTargetDefinition("location", "Storage / printing location", PrintingLocation),
}


def resolve_tag_target(owner, target_type: str, target_id):
    definition = TARGETS.get(str(target_type or "").strip().lower())
    if not definition:
        raise ValidationError({"target_type": "Choose a supported MakerVault tag target."})
    if not target_id:
        raise ValidationError({"target_id": "Choose a record to tag."})
    obj = definition.model.objects.filter(owner=owner, pk=target_id).first()
    if not obj:
        raise ValidationError({"target_id": "The selected tag target was not found."})
    return obj


def target_display(target_type: str, obj) -> dict:
    if target_type == "inventory":
        return {
            "id": str(obj.id),
            "label": obj.display_name,
            "subtitle": f"{obj.inventory_id} · {obj.get_status_display()}",
        }
    if target_type == "spool":
        return {
            "id": str(obj.id),
            "label": obj.spool_id,
            "subtitle": str(obj.filament),
        }
    if target_type == "printer":
        return {
            "id": str(obj.id),
            "label": obj.name,
            "subtitle": obj.model or "Printer",
        }
    if target_type == "project":
        return {
            "id": str(obj.id),
            "label": obj.name,
            "subtitle": obj.get_status_display(),
        }
    if target_type == "location":
        return {
            "id": str(obj.id),
            "label": obj.name,
            "subtitle": obj.get_kind_display(),
        }
    return {"id": str(obj.pk), "label": str(obj), "subtitle": ""}


def serialise_tag_target(owner, target_type: str, target_id) -> dict | None:
    try:
        obj = resolve_tag_target(owner, target_type, target_id)
    except ValidationError:
        return None
    return {
        "type": target_type,
        "type_label": TARGETS[target_type].label,
        **target_display(target_type, obj),
    }


def tag_target_options(owner) -> list[dict]:
    groups = []
    for target_type, definition in TARGETS.items():
        rows = definition.model.objects.filter(owner=owner)
        if target_type == "inventory":
            rows = rows.select_related("board__manufacturer", "component").order_by("inventory_id")
        elif target_type == "spool":
            rows = rows.select_related("filament__filament_manufacturer", "filament__manufacturer").order_by("spool_id")
        else:
            rows = rows.order_by("name")
        groups.append({
            "type": target_type,
            "label": definition.label,
            "rows": [target_display(target_type, row) for row in rows[:5000]],
        })
    return groups


def serialise_tag(tag: MakerTag, *, include_events: bool = False) -> dict:
    payload = {
        "id": str(tag.id),
        "public_token": str(tag.public_token),
        "kind": tag.kind,
        "kind_label": tag.get_kind_display(),
        "code": tag.code,
        "label": tag.label,
        "status": tag.status,
        "status_label": tag.get_status_display(),
        "target_type": tag.target_type,
        "target_id": str(tag.target_id),
        "target": serialise_tag_target(tag.owner, tag.target_type, tag.target_id),
        "notes": tag.notes,
        "metadata": tag.metadata or {},
        "technology": str((tag.metadata or {}).get("technology") or ""),
        "technology_label": dict(TAG_TECHNOLOGIES).get(
            str((tag.metadata or {}).get("technology") or ""),
            str((tag.metadata or {}).get("technology") or "Auto / unspecified"),
        ),
        "retired_at": tag.retired_at.isoformat() if tag.retired_at else None,
        "created_at": tag.created_at.isoformat(),
        "updated_at": tag.updated_at.isoformat(),
        "scan_path": f"/?tag={tag.public_token}",
    }
    if include_events:
        payload["events"] = [
            {
                "id": str(event.id),
                "event_type": event.event_type,
                "event_label": event.get_event_type_display(),
                "summary": event.summary,
                "details": event.details or {},
                "changed_by": event.changed_by.get_username() if event.changed_by else "",
                "created_at": event.created_at.isoformat(),
            }
            for event in tag.events.select_related("changed_by").all()[:100]
        ]
    return payload

