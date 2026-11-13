"""Strict draft-only storage for slicer facet colour painting.

These are logical preview palette references, not verified machine tool IDs.
This module never authorises slicing, firmware commands or physical printing.
"""
import re

MAX_FACES = 500_000
MAX_PAINT_SLOTS = 64


def validate_colour_paint(value):
    if not isinstance(value, dict) or set(value) != {"version", "signature", "faces", "palette"}:
        raise ValueError("Invalid colour painting metadata.")
    if type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("Unsupported colour painting version.")
    signature = value["signature"]
    if not isinstance(signature, str) or not re.fullmatch(r"[1-9][0-9]{0,5}:[0-9a-f]{1,8}", signature):
        raise ValueError("Invalid colour painting mesh fingerprint.")
    face_count = int(signature.split(":")[0])
    if face_count > MAX_FACES:
        raise ValueError("Painted mesh exceeds the face limit.")
    palette = value["palette"]
    if not isinstance(palette, list) or not 1 <= len(palette) <= MAX_PAINT_SLOTS:
        raise ValueError("Invalid colour painting palette.")
    cleaned_palette = []
    for entry in palette:
        if not isinstance(entry, dict):
            raise ValueError("Invalid paint palette entry.")
        required = {"color", "label"}
        optional = {"printer_id", "slot_id", "slot_index"}
        if not required.issubset(entry) or set(entry) - required - optional:
            raise ValueError("Invalid paint palette entry.")
        color, label = entry["color"], entry["label"]
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("Invalid paint palette colour.")
        if (not isinstance(label, str) or not 1 <= len(label) <= 160 or
                any(ord(ch) < 32 or ord(ch) == 127 for ch in label)):
            raise ValueError("Invalid paint palette label.")
        clean = {"color": color.lower(), "label": label}
        if any(key in entry for key in optional):
            if not all(key in entry for key in optional):
                raise ValueError("Incomplete advisory filament-slot reference.")
            printer_id, slot_id, slot_index = (entry[key] for key in ("printer_id", "slot_id", "slot_index"))
            if (not isinstance(printer_id, str) or
                    not re.fullmatch(r"[0-9a-fA-F-]{36}", printer_id) or
                    not isinstance(slot_id, str) or not 1 <= len(slot_id) <= 128 or
                    any(ord(ch) < 33 or ord(ch) > 126 for ch in slot_id) or
                    type(slot_index) is not int or not 0 <= slot_index <= 63):
                raise ValueError("Invalid advisory filament-slot reference.")
            clean.update({"printer_id": printer_id, "slot_id": slot_id, "slot_index": slot_index})
        cleaned_palette.append(clean)
    faces = value["faces"]
    if not isinstance(faces, dict) or len(faces) > face_count:
        raise ValueError("Invalid painted face list.")
    cleaned_faces = {}
    for face, slot in faces.items():
        if (not isinstance(face, str) or not re.fullmatch(r"0|[1-9][0-9]*", face) or
                len(face) > 6 or int(face) >= face_count or
                type(slot) is not int or not 0 <= slot < len(palette)):
            raise ValueError("Painted faces reference an invalid triangle or palette slot.")
        cleaned_faces[face] = slot
    return {"version": 1, "signature": signature,
            "palette": cleaned_palette, "faces": cleaned_faces}
