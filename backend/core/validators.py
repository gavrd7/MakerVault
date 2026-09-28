from pathlib import Path
from django.core.exceptions import ValidationError

# v0.1 accepts the file families we discussed while keeping arbitrary executable
# uploads download-only at the UI layer. Deep magic-byte inspection is added to the
# importer/upload service in the next milestone.
ALLOWED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".pdf", ".txt", ".md",
    ".zip", ".7z", ".tar", ".gz", ".ino", ".cpp", ".h", ".hpp", ".py", ".yaml", ".yml",
    ".json", ".toml", ".bin", ".hex", ".uf2", ".elf", ".exe", ".msi",
    ".stl", ".3mf", ".obj", ".step", ".stp", ".iges", ".igs", ".f3d", ".fcstd",
    ".sldprt", ".scad", ".dxf", ".gcode", ".bgcode", ".kicad_pcb", ".kicad_sch",
}


def validate_maker_file(value):
    name = str(getattr(value, "name", "") or "")
    storage = getattr(value, "storage", None)

    # Saved private files deliberately have opaque .blob object names. They have
    # already passed the user-upload extension validation before encryption; do
    # not reinterpret the internal storage suffix as a user-supplied file type.
    if (
        name.startswith("private/")
        and name.endswith(".blob")
        and storage is not None
        and storage.__class__.__module__ == "core.private_storage"
        and storage.__class__.__name__ == "PrivateEncryptedStorage"
    ):
        return

    suffix = Path(name).suffix.lower()
    if suffix and suffix not in ALLOWED_EXTENSIONS:
        raise ValidationError(f"File type '{suffix}' is not currently allowed.")
