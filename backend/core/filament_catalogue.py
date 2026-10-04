from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path
import json
from urllib.parse import urljoin, urlparse

import requests
from django.conf import settings
from django.core.cache import cache

from .importers import _host_is_public
from .filament_technical_sources import enrich_filament_from_authoritative_sources
from .model_values import fit_model_decimal


DEFAULT_SPOOLMANDB_URL = "https://donkie.github.io/SpoolmanDB/filaments.json"
MAX_CATALOGUE_BYTES = 64 * 1024 * 1024
CACHE_SECONDS = 6 * 60 * 60
SUPPLEMENTAL_CATALOGUE_PATH = Path(__file__).resolve().parent / "data" / "filament_catalogue_supplements.json"


class FilamentCatalogueError(ValueError):
    """Raised when an external filament catalogue cannot be queried safely."""


def _normalise_hex(value):
    raw = str(value or "").strip().lstrip("#")
    if len(raw) not in {6, 8}:
        return ""
    try:
        int(raw, 16)
    except ValueError:
        return ""
    return "#" + raw.lower()


def _appearance(row, hexes):
    has_alpha = any(len(value.lstrip("#")) == 8 and int(value.lstrip("#")[6:8], 16) < 255 for value in hexes)
    if has_alpha:
        return "transparent"
    if row.get("translucent") is True:
        return "translucent"
    return "opaque"


def _temperature_range(row, range_key, single_key):
    value = row.get(range_key)
    if isinstance(value, list) and len(value) >= 2:
        return value[0], value[1]
    single = row.get(single_key)
    if single is not None:
        return single, single
    return None, None


def normalise_spoolmandb_row(row):
    if not isinstance(row, dict):
        return None
    external_id = str(row.get("id") or "").strip()
    manufacturer = str(row.get("manufacturer") or row.get("vendor") or "").strip()
    name = str(row.get("name") or "").strip()
    material = str(row.get("material") or "").strip()
    if not external_id or not name or not material:
        return None

    raw_hexes = row.get("color_hexes") if isinstance(row.get("color_hexes"), list) else []
    if not raw_hexes and row.get("color_hex"):
        raw_hexes = [row.get("color_hex")]
    color_hexes = [item for item in (_normalise_hex(value) for value in raw_hexes) if item]
    primary = color_hexes[0] if color_hexes else ""
    display_primary = primary[:7] if len(primary) == 9 else primary
    nozzle_min, nozzle_max = _temperature_range(row, "extruder_temp_range", "extruder_temp")
    bed_min, bed_max = _temperature_range(row, "bed_temp_range", "bed_temp")

    color_name = str(row.get("color_name") or "").strip()
    if not color_name:
        # Compiled SpoolmanDB names normally already contain the manufacturer's
        # colour name; retain the full product name rather than inventing one.
        color_name = ""

    return {
        "external_id": external_id,
        "manufacturer": manufacturer or "Generic",
        "name": name,
        "material": material,
        "density_g_cm3": row.get("density"),
        "diameter_mm": row.get("diameter"),
        "nominal_weight_g": row.get("weight"),
        "empty_spool_weight_g": row.get("spool_weight"),
        "spool_type": row.get("spool_type") or "",
        "is_refill": bool(row.get("is_refill")),
        "color_name": color_name,
        "color_hex": display_primary,
        "color_hexes": color_hexes,
        "transparency": _appearance(row, color_hexes),
        "multi_color_direction": row.get("multi_color_direction") or "",
        "finish": row.get("finish") or "",
        "pattern": row.get("pattern") or "",
        "glow": bool(row.get("glow")),
        "nozzle_temp_min_c": nozzle_min,
        "nozzle_temp_max_c": nozzle_max,
        "bed_temp_min_c": bed_min,
        "bed_temp_max_c": bed_max,
        "country_of_origin": str(row.get("country_of_origin") or "").strip(),
        "product_url": str(row.get("product_url") or "").strip(),
        "tds_url": str(row.get("tds_url") or "").strip(),
        "sds_url": str(row.get("sds_url") or "").strip(),
        "codes": row.get("codes") if isinstance(row.get("codes"), list) else [],
        "eans": row.get("eans") if isinstance(row.get("eans"), list) else [],
        "eans_refill": row.get("eans_refill") if isinstance(row.get("eans_refill"), list) else [],
        "aliases": [],
        "source_type": "spoolmandb",
        "source_name": "SpoolmanDB",
        "source_url": "https://donkie.github.io/SpoolmanDB/",
        "source_license": "MIT",
        "raw": row,
    }



def normalise_supplemental_row(row):
    item = normalise_spoolmandb_row(row)
    if not item:
        return None
    item["aliases"] = [str(value).strip() for value in (row.get("aliases") or []) if str(value).strip()]
    item["drying_temp_c"] = row.get("drying_temp")
    item["drying_time_hours"] = row.get("drying_time_hours")
    item["source_type"] = str(row.get("source_type") or "manufacturer").strip() or "manufacturer"
    item["source_name"] = str(row.get("source_name") or item["manufacturer"] or "Manufacturer").strip()
    item["source_url"] = str(row.get("source_url") or row.get("product_url") or "").strip()
    item["source_license"] = str(row.get("source_license") or "Manufacturer data").strip()
    return item


def get_supplemental_filament_catalogue():
    try:
        payload = json.loads(SUPPLEMENTAL_CATALOGUE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    rows = []
    for raw in payload:
        item = normalise_supplemental_row(raw)
        if item:
            rows.append(item)
    return rows


def get_filament_catalogue(force=False):
    primary = get_spoolmandb_catalogue(force=force)
    supplements = get_supplemental_filament_catalogue()
    seen = set()
    merged = []
    for row in [*primary, *supplements]:
        external_id = str(row.get("external_id") or "").strip()
        if not external_id or external_id in seen:
            continue
        seen.add(external_id)
        merged.append(row)
    return merged

def _configured_url():
    return getattr(settings, "FILAMENT_CATALOGUE_SPOOLMANDB_URL", DEFAULT_SPOOLMANDB_URL)


def _validate_catalogue_url(value):
    parsed = urlparse(value)
    if parsed.scheme != "https":
        raise FilamentCatalogueError("Filament catalogue sources must use HTTPS.")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise FilamentCatalogueError("Filament catalogue source has no host.")
    if parsed.port not in (None, 443) or parsed.username or parsed.password:
        raise FilamentCatalogueError("Filament catalogue source uses an unsupported URL.")
    if not _host_is_public(host):
        raise FilamentCatalogueError("Filament catalogue source resolved to a private or reserved address.")
    return value


def _fetch_json():
    current = _validate_catalogue_url(_configured_url())
    headers = {
        "User-Agent": "MakerVault/0.6 (+self-hosted filament catalogue)",
        "Accept": "application/json,text/plain;q=0.8",
    }
    for _ in range(5):
        _validate_catalogue_url(current)
        try:
            response = requests.get(current, headers=headers, timeout=(5, 30), allow_redirects=False, stream=True)
        except requests.RequestException as exc:
            raise FilamentCatalogueError("MakerVault could not retrieve the filament catalogue.") from exc

        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise FilamentCatalogueError("The filament catalogue returned an invalid redirect.")
            current = urljoin(current, location)
            continue

        if response.status_code != 200:
            response.close()
            raise FilamentCatalogueError(f"The filament catalogue returned HTTP {response.status_code}.")

        declared = response.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > MAX_CATALOGUE_BYTES:
            response.close()
            raise FilamentCatalogueError("The filament catalogue is larger than MakerVault's safety limit.")

        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=262144):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_CATALOGUE_BYTES:
                response.close()
                raise FilamentCatalogueError("The filament catalogue is larger than MakerVault's safety limit.")
            chunks.append(chunk)
        response.close()
        try:
            data = json.loads(b"".join(chunks).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FilamentCatalogueError("The filament catalogue returned invalid JSON.") from exc
        if not isinstance(data, list):
            raise FilamentCatalogueError("The filament catalogue returned an unexpected document.")
        return data
    raise FilamentCatalogueError("The filament catalogue redirected too many times.")


def get_spoolmandb_catalogue(force=False):
    url = _configured_url()
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    key = f"makervault:filament-catalogue:spoolmandb:{digest}:v1"
    if not force:
        try:
            cached = cache.get(key)
        except Exception:
            cached = None
        if isinstance(cached, list):
            return cached

    rows = []
    for raw in _fetch_json():
        item = normalise_spoolmandb_row(raw)
        if item:
            rows.append(item)
    try:
        cache.set(key, rows, CACHE_SECONDS)
    except Exception:
        pass
    return rows


def search_spoolmandb(*, query="", material="", manufacturer="", limit=50, offset=0):
    query_terms = [term.casefold() for term in str(query or "").split() if term.strip()]
    material_key = str(material or "").strip().casefold()
    manufacturer_key = str(manufacturer or "").strip().casefold()
    matches = []
    for item in get_filament_catalogue():
        if material_key and item["material"].casefold() != material_key:
            continue
        if manufacturer_key and manufacturer_key not in item["manufacturer"].casefold():
            continue
        haystack = " ".join([
            item["manufacturer"], item["name"], item["material"], item["color_name"],
            item["finish"], item["pattern"], " ".join(item.get("aliases") or []),
        ]).casefold()
        if query_terms and not all(term in haystack for term in query_terms):
            continue
        matches.append(item)

    matches.sort(key=lambda row: (row["manufacturer"].casefold(), row["material"].casefold(), row["name"].casefold()))
    total = len(matches)
    return {
        "rows": matches[offset:offset + limit],
        "total": total,
        "offset": offset,
        "limit": limit,
        "source": {
            "name": "SpoolmanDB",
            "url": "https://donkie.github.io/SpoolmanDB/",
            "license": "MIT",
        },
    }


def get_spoolmandb_item(external_id):
    target = str(external_id or "").strip()
    if not target:
        raise FilamentCatalogueError("Choose a filament to import.")
    for item in get_filament_catalogue():
        if item["external_id"] == target:
            return item
    raise FilamentCatalogueError("That SpoolmanDB filament could not be found.")


def spoolmandb_meta():
    rows = get_filament_catalogue()
    manufacturers = sorted(
        {item["manufacturer"] for item in rows if item.get("manufacturer")},
        key=str.casefold,
    )
    materials = sorted(
        {item["material"] for item in rows if item.get("material")},
        key=str.casefold,
    )
    return {
        "manufacturers": manufacturers,
        "materials": materials,
        "source": {
            "name": "SpoolmanDB",
            "url": "https://donkie.github.io/SpoolmanDB/",
            "license": "MIT",
        },
    }

def refresh_imported_filament_products(*, force_catalogue=False, limit=None):
    """Refresh saved SpoolmanDB-backed products without overwriting user edits.

    Only blank MakerVault fields are populated from upstream. Richer provenance
    is retained in profile_data so future catalogue/image passes can use
    manufacturer product, TDS and SDS links without turning them into user data.
    """
    from .models import FilamentProduct

    upstream = {
        row["external_id"]: row
        for row in get_spoolmandb_catalogue(force=force_catalogue)
        if row.get("external_id")
    }
    queryset = (
        FilamentProduct.objects.select_related("source")
        .filter(source__source_type="spoolmandb")
        .order_by("updated_at", "pk")
    )
    if limit is not None:
        queryset = queryset[:max(int(limit), 0)]

    checked = updated = missing = 0
    for item in queryset:
        checked += 1
        external_id = str(getattr(item.source, "external_id", "") or "").strip()
        row = upstream.get(external_id)
        if not row:
            missing += 1
            continue

        changed = []
        fill_fields = {
            "color_name": row.get("color_name"),
            "color_hex": row.get("color_hex"),
            "color_hexes": row.get("color_hexes"),
            "multi_color_direction": row.get("multi_color_direction"),
            "finish": row.get("finish"),
            "pattern": row.get("pattern"),
            "density_g_cm3": row.get("density_g_cm3"),
            "nominal_weight_g": row.get("nominal_weight_g"),
            "empty_spool_weight_g": row.get("empty_spool_weight_g"),
            "nozzle_temp_min_c": row.get("nozzle_temp_min_c"),
            "nozzle_temp_max_c": row.get("nozzle_temp_max_c"),
            "bed_temp_min_c": row.get("bed_temp_min_c"),
            "bed_temp_max_c": row.get("bed_temp_max_c"),
        }
        for field, value in fill_fields.items():
            current = getattr(item, field)
            if current in (None, "", [], {}) and value not in (None, "", [], {}):
                setattr(item, field, value)
                changed.append(field)

        if not item.glow and row.get("glow"):
            item.glow = True
            changed.append("glow")
        if item.transparency == "opaque" and row.get("transparency") in {"translucent", "transparent"}:
            item.transparency = row["transparency"]
            changed.append("transparency")

        profile = dict(item.profile_data or {})
        upstream_meta = {
            "catalogue": source_name,
            "external_id": external_id,
            "spool_type": row.get("spool_type") or "",
            "is_refill": bool(row.get("is_refill")),
            "country_of_origin": row.get("country_of_origin") or "",
            "product_url": row.get("product_url") or "",
            "tds_url": row.get("tds_url") or "",
            "sds_url": row.get("sds_url") or "",
            "codes": row.get("codes") or [],
            "eans": row.get("eans") or [],
            "eans_refill": row.get("eans_refill") or [],
        }
        if profile.get("catalogue_provenance") != upstream_meta:
            profile["catalogue_provenance"] = upstream_meta
            item.profile_data = profile
            changed.append("profile_data")

        if changed:
            item.save(update_fields=list(dict.fromkeys(changed + ["updated_at"])))
            updated += 1

        authoritative = enrich_filament_from_authoritative_sources(item, row)
        if authoritative.get("changed_fields"):
            updated += int(not changed)

        source_meta = dict(item.source.raw_metadata or {})
        if source_meta.get("record") != row.get("raw"):
            source_meta["record"] = row.get("raw") or {}
            source_meta["license"] = row.get("source_license") or source_meta.get("license", "")
            item.source.raw_metadata = source_meta
            item.source.save(update_fields=["raw_metadata", "updated_at"])

    return {
        "status": "ok",
        "checked": checked,
        "updated": updated,
        "missing_upstream": missing,
    }



def _match_tokens(value):
    import re
    stop = {"filament", "3d", "printer", "printing"}
    return {
        token for token in re.findall(r"[a-z0-9]+", str(value or "").casefold())
        if len(token) > 1 and token not in stop
    }


def _normalise_match_hex(value):
    raw = str(value or "").strip().casefold()
    if raw and not raw.startswith("#"):
        raw = "#" + raw
    return raw[:7]


def _material_match_key(value):
    raw = str(value or "").strip().casefold()
    aliases = [
        ("tpe", "tpe"), ("tpu", "tpu"), ("asa", "asa"), ("abs", "abs"),
        ("petg", "petg"), ("pla", "pla"), ("nylon", "pa"), ("pa", "pa"),
        ("polycarbonate", "pc"), ("pc", "pc"), ("hips", "hips"), ("pva", "pva"),
        ("polypropylene", "pp"), ("pp", "pp"),
    ]
    for token, canonical in aliases:
        if token in raw:
            return canonical
    return raw


def match_filament_catalogue_candidates(filament, *, limit=8):
    """Rank catalogue records against an existing MakerVault filament product."""
    maker = (
        filament.filament_manufacturer.name
        if filament.filament_manufacturer_id
        else filament.manufacturer.name if filament.manufacturer_id else ""
    )
    wanted_name = _match_tokens(filament.name)
    wanted_material = _material_match_key(filament.material)
    wanted_maker = str(maker or "").strip().casefold()
    wanted_colour_name = _match_tokens(filament.color_name)
    wanted_hex = _normalise_match_hex(filament.color_hex)

    ranked = []
    for row in get_filament_catalogue():
        score = 0
        reasons = []
        row_maker = str(row.get("manufacturer") or "").strip().casefold()
        row_material = _material_match_key(row.get("material"))
        row_name_tokens = _match_tokens(" ".join([str(row.get("name") or ""), *[str(value) for value in (row.get("aliases") or [])]]))
        row_colour_tokens = _match_tokens(row.get("color_name"))
        row_hex = _normalise_match_hex(row.get("color_hex"))

        if wanted_maker and row_maker == wanted_maker:
            score += 30
            reasons.append("manufacturer")
        elif wanted_maker and (wanted_maker in row_maker or row_maker in wanted_maker):
            score += 18
            reasons.append("manufacturer similar")

        if wanted_material and row_material == wanted_material:
            score += 28
            reasons.append("material")
        elif wanted_material and wanted_material in row_material:
            score += 12
            reasons.append("material similar")

        if wanted_name and row_name_tokens:
            overlap = wanted_name & row_name_tokens
            if overlap:
                ratio = len(overlap) / max(len(wanted_name | row_name_tokens), 1)
                score += round(34 * ratio)
                reasons.append("product name")

        if wanted_hex and row_hex:
            if wanted_hex == row_hex:
                score += 24
                reasons.append("colour")
            else:
                try:
                    a = tuple(int(wanted_hex[i:i+2], 16) for i in (1, 3, 5))
                    b = tuple(int(row_hex[i:i+2], 16) for i in (1, 3, 5))
                    distance = sum((left - right) ** 2 for left, right in zip(a, b)) ** 0.5
                    if distance <= 45:
                        score += 12
                        reasons.append("colour similar")
                except ValueError:
                    pass

        if wanted_colour_name and row_colour_tokens and wanted_colour_name & row_colour_tokens:
            score += 12
            reasons.append("colour name")

        if score <= 0:
            continue
        ranked.append({
            **row,
            "match_score": min(score, 100),
            "match_reasons": reasons,
        })

    ranked.sort(key=lambda row: (
        -int(row["match_score"]),
        row["manufacturer"].casefold(),
        row["name"].casefold(),
    ))
    return ranked[:max(1, min(int(limit or 8), 20))]


def _catalogue_match_restore_snapshot(filament):
    profile = dict(filament.profile_data or {})
    existing = profile.get("catalogue_match_restore")
    if isinstance(existing, dict):
        return existing

    prior_profile = dict(profile)
    prior_profile.pop("catalogue_match_restore", None)
    fields = [
        "color_name", "color_hex", "color_hexes", "transparency",
        "multi_color_direction", "finish", "pattern", "glow",
        "density_g_cm3", "nominal_weight_g", "empty_spool_weight_g",
        "nozzle_temp_min_c", "nozzle_temp_max_c",
        "bed_temp_min_c", "bed_temp_max_c",
        "drying_temp_c", "drying_time_hours",
    ]
    values = {}
    for field in fields:
        value = getattr(filament, field)
        values[field] = str(value) if isinstance(value, Decimal) else value
    return {
        "version": 1,
        "source_id": str(filament.source_id) if filament.source_id else "",
        "filament_manufacturer_id": str(filament.filament_manufacturer_id) if filament.filament_manufacturer_id else "",
        "manufacturer_id": str(filament.manufacturer_id) if filament.manufacturer_id else "",
        "values": values,
        "profile_data": prior_profile,
    }


def apply_catalogue_match_to_filament(filament, external_id):
    """Attach or rematch a catalogue record and fill missing enrichment fields."""
    from .models import CatalogSource, FilamentManufacturer

    row = get_spoolmandb_item(external_id)
    source_type = str(row.get("source_type") or "spoolmandb").strip() or "spoolmandb"
    source_name = str(row.get("source_name") or "SpoolmanDB").strip() or "SpoolmanDB"
    source, _ = CatalogSource.objects.update_or_create(
        source_type=source_type,
        external_id=row["external_id"],
        defaults={
            "name": f"{source_name} — {row['manufacturer']} — {row['name']}"[:200],
            "url": row["source_url"],
            "raw_metadata": {
                "license": row["source_license"],
                "catalogue_id": row["external_id"],
                "record": row["raw"],
            },
        },
    )
    maker, _ = FilamentManufacturer.objects.get_or_create(name=row["manufacturer"] or "Generic")

    profile = dict(filament.profile_data or {})
    restore_snapshot = _catalogue_match_restore_snapshot(filament)

    changed = []
    current_source_type = getattr(filament.source, "source_type", "") if filament.source_id else ""
    catalogue_source_types = {"manual", "spoolmandb", "manufacturer", "filamentprofiles", "filamentsdb"}
    if filament.source_id is None or current_source_type in catalogue_source_types:
        if filament.source_id != source.id:
            filament.source = source
            changed.append("source")
    if not filament.filament_manufacturer_id:
        filament.filament_manufacturer = maker
        filament.manufacturer = None
        changed.extend(["filament_manufacturer", "manufacturer"])

    fill_fields = {
        "color_name": row.get("color_name"),
        "color_hex": row.get("color_hex"),
        "color_hexes": row.get("color_hexes"),
        "multi_color_direction": row.get("multi_color_direction"),
        "finish": row.get("finish"),
        "pattern": row.get("pattern"),
        "density_g_cm3": row.get("density_g_cm3"),
        "nominal_weight_g": row.get("nominal_weight_g"),
        "empty_spool_weight_g": row.get("empty_spool_weight_g"),
        "nozzle_temp_min_c": row.get("nozzle_temp_min_c"),
        "nozzle_temp_max_c": row.get("nozzle_temp_max_c"),
        "bed_temp_min_c": row.get("bed_temp_min_c"),
        "bed_temp_max_c": row.get("bed_temp_max_c"),
    }
    for field, value in fill_fields.items():
        current = getattr(filament, field)
        if current in (None, "", [], {}) and value not in (None, "", [], {}):
            setattr(filament, field, fit_model_decimal(filament, field, value))
            changed.append(field)

    if not filament.glow and row.get("glow"):
        filament.glow = True
        changed.append("glow")
    if filament.transparency == "opaque" and row.get("transparency") in {"translucent", "transparent"}:
        filament.transparency = row["transparency"]
        changed.append("transparency")

    profile = dict(filament.profile_data or {})
    profile["catalogue_match_restore"] = restore_snapshot
    profile["catalogue_provenance"] = {
        "catalogue": "SpoolmanDB",
        "external_id": row["external_id"],
        "matched_manually": True,
        "matched_at": __import__("django.utils.timezone", fromlist=["now"]).now().isoformat(),
        "spool_type": row.get("spool_type") or "",
        "is_refill": bool(row.get("is_refill")),
        "country_of_origin": row.get("country_of_origin") or "",
        "product_url": row.get("product_url") or "",
        "tds_url": row.get("tds_url") or "",
        "sds_url": row.get("sds_url") or "",
        "codes": row.get("codes") or [],
        "eans": row.get("eans") or [],
        "eans_refill": row.get("eans_refill") or [],
    }
    filament.profile_data = profile
    changed.append("profile_data")

    # A catalogue match should validate only the values it is applying.
    # Older/manual MakerVault records may contain legacy values in unrelated
    # fields that the database accepted before tighter model validation existed;
    # those must not prevent linking otherwise valid catalogue data.
    changed_fields = list(dict.fromkeys(changed))
    concrete_fields = {
        field.name for field in filament._meta.concrete_fields
        if field.name not in {"id", "created_at", "updated_at"}
    }
    validation_exclude = sorted(concrete_fields - set(changed_fields))
    filament.full_clean(exclude=validation_exclude, validate_unique=False, validate_constraints=False)
    filament.save(update_fields=changed_fields + ["updated_at"])

    # After the catalogue link exists, prefer authoritative manufacturer/TDS
    # technical data over the catalogue's fallback values.
    authoritative = enrich_filament_from_authoritative_sources(filament, row)
    return {
        "row": row,
        "changed_fields": sorted(set(changed)),
        "authoritative": authoritative,
    }


def unmatch_filament_catalogue(filament):
    """Remove a catalogue match, restoring the pre-match state when available."""
    from .models import CatalogSource, FilamentManufacturer, Manufacturer

    profile = dict(filament.profile_data or {})
    snapshot = profile.get("catalogue_match_restore")
    changed = []

    if isinstance(snapshot, dict):
        values = snapshot.get("values") if isinstance(snapshot.get("values"), dict) else {}
        for field, value in values.items():
            try:
                model_field = filament._meta.get_field(field)
            except Exception:
                continue
            if getattr(model_field, "decimal_places", None) is not None and value not in (None, ""):
                value = fit_model_decimal(filament, field, value)
            setattr(filament, field, value)
            changed.append(field)

        source_id = str(snapshot.get("source_id") or "").strip()
        maker_id = str(snapshot.get("filament_manufacturer_id") or "").strip()
        legacy_maker_id = str(snapshot.get("manufacturer_id") or "").strip()
        filament.source = CatalogSource.objects.filter(pk=source_id).first() if source_id else None
        filament.filament_manufacturer = FilamentManufacturer.objects.filter(pk=maker_id).first() if maker_id else None
        filament.manufacturer = Manufacturer.objects.filter(pk=legacy_maker_id).first() if legacy_maker_id else None
        changed.extend(["source", "filament_manufacturer", "manufacturer"])

        prior_profile = snapshot.get("profile_data")
        filament.profile_data = dict(prior_profile) if isinstance(prior_profile, dict) else {}
        changed.append("profile_data")
        restored = True
    else:
        # Legacy matches have no reliable before-state. Remove only the active
        # catalogue linkage/provenance and retain descriptive values rather than
        # guessing which ones were user-entered.
        if filament.source_id and getattr(filament.source, "source_type", "") == "spoolmandb":
            filament.source = None
            changed.append("source")
        for key in [
            "catalogue_provenance", "catalogue_match_restore",
            "external_catalogue_id", "spool_type", "raw_color_hexes",
        ]:
            profile.pop(key, None)
        filament.profile_data = profile
        changed.append("profile_data")
        restored = False

    changed_fields = list(dict.fromkeys(changed))
    filament.save(update_fields=changed_fields + ["updated_at"])
    return {"restored": restored, "changed_fields": changed_fields}

