from __future__ import annotations

import hashlib
import json
from urllib.parse import urljoin, urlparse

import requests
from django.conf import settings
from django.core.cache import cache

from .importers import _host_is_public


DEFAULT_SPOOLMANDB_URL = "https://donkie.github.io/SpoolmanDB/filaments.json"
MAX_CATALOGUE_BYTES = 64 * 1024 * 1024
CACHE_SECONDS = 6 * 60 * 60


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
        "source_name": "SpoolmanDB",
        "source_url": "https://donkie.github.io/SpoolmanDB/",
        "source_license": "MIT",
        "raw": row,
    }


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
    for item in get_spoolmandb_catalogue():
        if material_key and item["material"].casefold() != material_key:
            continue
        if manufacturer_key and manufacturer_key not in item["manufacturer"].casefold():
            continue
        haystack = " ".join([
            item["manufacturer"], item["name"], item["material"], item["color_name"],
            item["finish"], item["pattern"],
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
    for item in get_spoolmandb_catalogue():
        if item["external_id"] == target:
            return item
    raise FilamentCatalogueError("That SpoolmanDB filament could not be found.")


def spoolmandb_meta():
    rows = get_spoolmandb_catalogue()
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
