"""Private, immutable, content-addressed slicer painting assets.

Geometry stays in its existing owned STL FileAsset. High-density painted
annotations live in a separate compressed FileAsset, referenced by UUID from
a slice draft. No user-supplied filesystem paths or unowned references.
"""
import gzip
import hashlib
import json
import uuid

from django.core.files.base import ContentFile

from .models import FileAsset
from .slicer_colour_painting import validate_colour_paint
from .slicer_support_painting import validate_support_paint
from .slicer_semantic_painting import validate_semantic_paint
from .slicer_variable_layers import validate_variable_layer_profile

PAINT_FIELDS = ("colour_paint", "support_paint", "seam_paint",
                "fuzzy_skin_paint", "variable_layer_profile")
MAX_PAINT_JSON = 48 * 1024 * 1024
MAX_PAINT_GZIP = 8 * 1024 * 1024


def validate_annotations(paint):
    if not isinstance(paint, dict) or not paint or set(paint) - set(PAINT_FIELDS):
        raise ValueError("Invalid slicing paint asset fields.")
    cleaned = {}
    for key, value in paint.items():
        if key == "colour_paint":
            cleaned[key] = validate_colour_paint(value)
        elif key == "support_paint":
            cleaned[key] = validate_support_paint(value)
        elif key in ("seam_paint", "fuzzy_skin_paint"):
            cleaned[key] = validate_semantic_paint(
                value, "seam" if key == "seam_paint" else "fuzzy")
        elif key == "variable_layer_profile":
            cleaned[key] = validate_variable_layer_profile(value)
    return cleaned


def _owned_mesh(owner, mesh_id):
    try:
        mesh_id = uuid.UUID(str(mesh_id))
    except (TypeError, ValueError, AttributeError):
        raise ValueError("Invalid source STL reference.") from None
    if not FileAsset.objects.filter(owner=owner, pk=mesh_id, category="mesh").exists():
        raise ValueError("Painting references an unavailable owned STL.")
    return str(mesh_id)


def store_paint(owner, mesh_id, paint, quota_check=None):
    mesh_id = _owned_mesh(owner, mesh_id)
    cleaned = validate_annotations(paint)
    raw = json.dumps(cleaned, ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(raw) > MAX_PAINT_JSON:
        raise ValueError("Painting exceeds the 48 MiB expanded asset limit.")
    packed = gzip.compress(raw, compresslevel=6, mtime=0)
    if len(packed) > MAX_PAINT_GZIP:
        raise ValueError("Painting exceeds the 8 MiB compressed asset limit.")
    digest = hashlib.sha256(raw).hexdigest()
    existing = FileAsset.objects.filter(
        owner=owner, category="slicer", sha256=digest,
        metadata__slicer_paint=True, metadata__source_mesh_id=mesh_id,
    ).first()
    if existing:
        return existing
    if quota_check is not None:
        quota_check(owner, len(packed))
    asset = FileAsset(
        owner=owner, category="slicer", name="Private slicer painting",
        sha256=digest,
        metadata={"slicer_paint": True, "slicer_temporary": True,
                  "source_mesh_id": mesh_id, "extension": ".json.gz",
                  "size_bytes": len(packed), "format_version": 1,
                  "paint_fields": sorted(cleaned)},
    )
    try:
        asset.file.save("slicer-paint-" + digest[:16] + ".json.gz",
                        ContentFile(packed), save=False)
        asset.full_clean()
        asset.save()
    except Exception:
        if asset.file:
            asset.file.delete(save=False)
        raise
    return asset


def load_paint(owner, asset_id, mesh_id):
    mesh_id = _owned_mesh(owner, mesh_id)
    try:
        asset_id = uuid.UUID(str(asset_id))
    except (TypeError, ValueError, AttributeError):
        raise ValueError("Invalid painting asset identifier.") from None
    asset = FileAsset.objects.filter(
        owner=owner, pk=asset_id, category="slicer",
        metadata__slicer_paint=True,
        metadata__source_mesh_id=mesh_id,
    ).first()
    if not asset or not asset.file:
        raise ValueError("Private painting asset is missing or belongs to another mesh.")
    with asset.file.open("rb") as file:
        packed = file.read(MAX_PAINT_GZIP + 1)
    if len(packed) > MAX_PAINT_GZIP:
        raise ValueError("Stored painting exceeds compressed safety limits.")
    import zlib
    try:
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        raw = decompressor.decompress(packed, MAX_PAINT_JSON + 1)
        if (len(raw) > MAX_PAINT_JSON or not decompressor.eof
                or decompressor.unconsumed_tail or decompressor.unused_data):
            raise ValueError("Stored painting exceeds expanded safety limits.")
    except zlib.error:
        raise ValueError("Stored painting is corrupt.") from None
    if hashlib.sha256(raw).hexdigest() != asset.sha256:
        raise ValueError("Stored painting checksum mismatch.")
    try:
        return validate_annotations(json.loads(raw))
    except (UnicodeError, TypeError, json.JSONDecodeError):
        raise ValueError("Stored painting JSON is invalid.") from None


def expand_painted_item(owner, item):
    """Decode an owned paint ref for validation and native execution."""
    if not isinstance(item, dict) or "paint_asset_id" not in item:
        return item
    if any(key in item for key in PAINT_FIELDS):
        raise ValueError("A paint asset reference cannot also contain inline painting.")
    # Expanded working copies contain inline masks only. Keeping the ID too
    # would make subsequent validation think the client submitted both forms.
    reference = item["paint_asset_id"]
    plain = {key: value for key, value in item.items() if key != "paint_asset_id"}
    return {**plain, **load_paint(owner, reference, item.get("asset_id"))}


def expand_painted_settings(owner, settings):
    """Copy only project plate containers; never mutate persisted job JSON."""
    if not isinstance(settings, dict):
        return settings
    copy = dict(settings)
    if isinstance(copy.get("plate_objects"), list):
        copy["plate_objects"] = [
            expand_painted_item(owner, row) for row in copy["plate_objects"]]
    if isinstance(copy.get("plates"), list):
        copy["plates"] = [
            {**plate, "objects": [
                expand_painted_item(owner, row) for row in plate.get("objects", [])]}
            if isinstance(plate, dict) else plate for plate in copy["plates"]]
    return copy


def settings_use_paint_field(owner, settings, field):
    """Read a safe server-authored feature flag without expanding large masks."""
    if field not in PAINT_FIELDS or not isinstance(settings, dict):
        return False
    rows = list(settings.get("plate_objects") or [])
    for plate in settings.get("plates") or []:
        if isinstance(plate, dict):
            rows.extend(plate.get("objects") or [])
    for row in rows:
        if not isinstance(row, dict):
            continue
        if isinstance(row.get(field), dict):
            value = row[field]
            if any(value.get(k) for k in ("regions", "faces", "bands")):
                return True
        reference = row.get("paint_asset_id")
        if reference:
            try:
                ref=uuid.UUID(str(reference))
            except (TypeError, ValueError, AttributeError):
                continue
            if FileAsset.objects.filter(
                pk=ref, owner=owner, category="slicer",
                metadata__slicer_paint=True,
                metadata__source_mesh_id=str(row.get("asset_id")),
                metadata__paint_fields__contains=[field],
            ).exists():
                return True
    return False
