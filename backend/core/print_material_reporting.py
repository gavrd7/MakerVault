"""Read-only, sourced material totals; never deduct physical spool inventory."""
import re
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath

from .models import FileAsset

READ_BYTES = 1024 * 1024
PARSER_VERSION = 1


def weight(value):
    if isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return float(result) if result.is_finite() and 0 <= result <= 100000 else None


def parse_gcode_weight(text):
    """Explicit gram metadata only: Orca/Prusa/Bambu and total-weight headers."""
    values = {}
    for line in text.splitlines():
        if len(line) > 4096:
            continue
        match = re.fullmatch(r"\s*;\s*(filament used \[g\]|total filament (?:used|weight) \[g\]|filament mass_g)\s*[=:]\s*(.*?)\s*", line, re.I)
        if not match:
            continue
        key = match[1].lower()
        tokens = re.split(r"[,;]\s*", match[2])
        parsed = [weight(token.strip()) for token in tokens]
        if not parsed or any(item is None for item in parsed):
            return None
        if key in values and values[key] != parsed:
            return None
        values[key] = parsed
    if not values:
        return None
    total_keys = [key for key in values if key != "filament used [g]"]
    selected = values[total_keys[0]] if total_keys else values["filament used [g]"]
    total = weight(sum(Decimal(str(item)) for item in selected))
    if total is None or any(weight(sum(Decimal(str(v)) for v in values[key])) != total for key in total_keys):
        return None
    return {"used_g": total, "estimated": True, "source": "uploaded_gcode", "per_tool_g": values.get("filament used [g]", [])}


def gcode_report(asset):
    original = str((asset.metadata or {}).get("original_name") or asset.name)
    if not original.lower().endswith(".gcode"):
        return None
    cached = (asset.metadata or {}).get("gcode_material") or {}
    if cached.get("parser_version") == PARSER_VERSION and cached.get("sha256") == asset.sha256:
        return cached.get("report")
    try:
        with asset.file.open("rb") as handle:
            first = handle.read(READ_BYTES)
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(READ_BYTES, size - READ_BYTES))
            last = handle.read(READ_BYTES) if size > READ_BYTES else b""
        report = parse_gcode_weight((first + b"\n" + last).decode("utf-8", errors="replace"))
    except (OSError, ValueError, NotImplementedError):
        return None
    if report:
        report = {**report, "file_id": str(asset.id), "filename": original, "sha256": asset.sha256}
    metadata = dict(asset.metadata or {})
    metadata["gcode_material"] = {"parser_version": PARSER_VERSION, "sha256": asset.sha256, "report": report}
    FileAsset.objects.filter(pk=asset.pk).update(metadata=metadata)
    asset.metadata = metadata
    return report


def matching_gcode(owner, filename):
    name = PurePosixPath(str(filename).replace("\\", "/")).name
    if not name.lower().endswith(".gcode"):
        return None
    rows = list(FileAsset.objects.filter(owner=owner, superseded_by__isnull=True, metadata__original_name__iexact=name)[:3])
    if not rows or len(rows) > 1:
        return None  # Filenames are not content identities: require an unambiguous match.
    return gcode_report(rows[0])


def report_from_snapshot(job, snapshot):
    data = snapshot.get("job") or {}
    # Normalised measured/reported weights take precedence over a slicer estimate.
    amount = weight(data.get("filament_used_g"))
    if amount is not None:
        return {"used_g": amount, "estimated": bool(data.get("filament_usage_estimated", False)), "source": "printer_report", "adapter": snapshot.get("adapter", ""), "basis": data.get("filament_usage_basis", "reported_weight")} 
    amount = weight(data.get("filament_estimated_g"))
    if amount is not None and job.status == "success":
        return {"used_g": amount, "estimated": True, "source": "printer_gcode_metadata", "adapter": snapshot.get("adapter", "")}
    return None


def capture_material(job, snapshot=None, asset=None):
    settings = dict(job.settings or {})
    incoming_name = ((snapshot or {}).get("job") or {}).get("file_name")
    known_name = (settings.get("live_monitor") or {}).get("filename")
    if incoming_name and known_name and incoming_name != known_name:
        return
    current = settings.get("automatic_material_usage") or {}
    report = report_from_snapshot(job, snapshot or {})
    if not report and job.status == "success":
        if current and current.get("source") in {"uploaded_gcode", "printer_report"}:
            return
        if current and not current.get("estimated", True):
            return
        filename = ((settings.get("live_monitor") or {}).get("filename") or "")
        report = gcode_report(asset) if asset else matching_gcode(job.owner, filename)
    if not report:
        return
    if report == current:
        return
    if current and not current.get("estimated", True) and report.get("estimated", True):
        return
    if current.get("source") == "printer_report" and report.get("source") != "printer_report":
        return
    settings["automatic_material_usage"] = report
    job.settings = settings
    job.save(update_fields=["settings", "updated_at"])


def material_summary(job, usages=None):
    usages = list(job.material_usages.all()) if usages is None else usages
    if usages:
        return {"used_g": float(sum((item.used_g for item in usages), Decimal(0))), "waste_g": float(sum((item.waste_g for item in usages), Decimal(0))), "source": "recorded", "estimated": False}
    report = (job.settings or {}).get("automatic_material_usage") or {}
    amount = weight(report.get("used_g"))
    if amount is None or (report.get("estimated", True) and report.get("basis") != "extrusion_length" and job.status != "success"):
        return {"used_g": None, "waste_g": None, "source": "", "estimated": False}
    return {**report, "used_g": amount, "waste_g": None}
