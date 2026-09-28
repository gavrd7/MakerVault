import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

import requests
from django.conf import settings
from django.db import transaction

from .models import PrinterCatalogModel, PrinterManufacturer


ORCA_REPOSITORY = "OrcaSlicer/OrcaSlicer"
ORCA_PROFILES_PATH = "resources/profiles"
ORCA_DIRECTORY_URL = (
    "https://api.github.com/repos/OrcaSlicer/OrcaSlicer/contents/"
    "resources/profiles"
)
ORCA_SOURCE_ROOT = "https://github.com/OrcaSlicer/OrcaSlicer/blob"
ORCA_RAW_PREFIX = "https://raw.githubusercontent.com/OrcaSlicer/OrcaSlicer/"
ORCA_LICENSE = "AGPL-3.0"

VENDOR_ALIASES = {
    "bambulab": "Bambu Lab",
    "bambu lab": "Bambu Lab",
    "bbl": "Bambu Lab",
    "elegoo": "ELEGOO",
    "qidi": "QIDI",
    "flsun": "FLSUN",
}

# Orca contains a few slicer profiles representing a printer with an optional
# add-on fitted. MakerVault models that as one printer model + installed add-on.
ADDON_SUFFIX_RULES = [
    (re.compile(r"_CFS-C$", re.IGNORECASE), "creality_cfs"),
    (re.compile(r"\s+CFS-C$", re.IGNORECASE), "creality_cfs"),
]


class OrcaCatalogueError(RuntimeError):
    pass


def _user_agent():
    return f"MakerVault/{getattr(settings, 'MAKERVAULT_VERSION', 'dev')} (+OrcaSlicer catalogue sync)"


def _canonical_vendor(value):
    raw = re.sub(r"\s+", " ", str(value or "").strip())
    return VENDOR_ALIASES.get(raw.casefold(), raw)


def _normalise_model_name(vendor, raw_name):
    name = re.sub(r"\s+", " ", str(raw_name or "").strip())
    system = ""
    for pattern, candidate_system in ADDON_SUFFIX_RULES:
        if pattern.search(name):
            name = pattern.sub("", name).strip()
            system = candidate_system
            break

    # Orca's machine names usually include the manufacturer; MakerVault stores
    # manufacturer and model separately.
    prefixes = [vendor]
    if vendor == "Bambu Lab":
        prefixes.extend(["Bambulab", "Bambu Lab"])
    for prefix in prefixes:
        if name.casefold().startswith(prefix.casefold() + " "):
            name = name[len(prefix):].strip()
            break
    return name, system


def _default_multi_material_system(vendor, model_name):
    # Bambu's supported FFF catalogue is designed around AMS/AMS Lite style
    # systems. The exact installed hardware remains per-owned-printer.
    if vendor == "Bambu Lab":
        return "bambu_ams"
    return ""


def _extract_vendor_manifest(response, max_bytes=1024 * 1024):
    """Read vendor name + machine list without downloading huge process presets."""
    chunks = []
    total = 0
    decoder = json.JSONDecoder()
    marker = '"machine_model_list"'
    manifest_name = ""
    manifest_version = ""

    for chunk in response.iter_content(chunk_size=32768, decode_unicode=True):
        if not chunk:
            continue
        if isinstance(chunk, bytes):
            chunk = chunk.decode("utf-8", errors="replace")
        chunks.append(chunk)
        total += len(chunk.encode("utf-8", errors="ignore"))
        text = "".join(chunks)

        if not manifest_name:
            match = re.search(r'"name"\s*:\s*"([^"]+)"', text)
            if match:
                manifest_name = match.group(1).strip()
        if not manifest_version:
            match = re.search(r'"version"\s*:\s*"([^"]+)"', text)
            if match:
                manifest_version = match.group(1).strip()

        marker_at = text.find(marker)
        if marker_at >= 0:
            array_at = text.find("[", marker_at + len(marker))
            if array_at >= 0:
                try:
                    value, _ = decoder.raw_decode(text[array_at:])
                    if isinstance(value, list):
                        return manifest_name, manifest_version, value
                except json.JSONDecodeError:
                    pass
        if total >= max_bytes:
            break

    # Some top-level profile files are filament-only libraries rather than
    # printer vendors. Treat those as an empty source, not a failed vendor.
    if marker not in "".join(chunks):
        return manifest_name, manifest_version, []
    raise OrcaCatalogueError("OrcaSlicer vendor manifest did not expose a readable machine model list.")


def _fetch_vendor_manifest(entry, ref):
    raw_url = str(entry.get("download_url") or "")
    if not raw_url.startswith(ORCA_RAW_PREFIX):
        raise OrcaCatalogueError("OrcaSlicer returned an unexpected vendor manifest URL.")
    response = requests.get(
        raw_url,
        timeout=(5, 20),
        stream=True,
        headers={
            "User-Agent": _user_agent(),
            "Accept": "application/json",
            "Range": "bytes=0-1048575",
        },
    )
    try:
        response.raise_for_status()
        manifest_name, manifest_version, machines = _extract_vendor_manifest(response)
    finally:
        response.close()

    vendor_file = str(entry.get("name") or "")
    raw_vendor = vendor_file[:-5] if vendor_file.lower().endswith(".json") else vendor_file
    vendor = _canonical_vendor(manifest_name or raw_vendor)
    rows = []
    for machine in machines:
        if not isinstance(machine, dict):
            continue
        raw_name = str(machine.get("name") or "").strip()
        sub_path = str(machine.get("sub_path") or "").strip()
        if not raw_name or not sub_path:
            continue
        name, addon_system = _normalise_model_name(vendor, raw_name)
        if not name:
            continue
        rows.append({
            "vendor": vendor,
            "name": name,
            "raw_name": raw_name,
            "vendor_file": vendor_file,
            "vendor_version": manifest_version,
            "sub_path": sub_path,
            "multi_material_system": addon_system or _default_multi_material_system(vendor, name),
            "source_url": (
                f"{ORCA_SOURCE_ROOT}/{quote(ref, safe='')}/"
                f"{ORCA_PROFILES_PATH}/{quote(vendor_file, safe='')}"
            ),
        })
    return vendor, rows


def _get_or_create_manufacturer(name):
    existing = PrinterManufacturer.objects.filter(name__iexact=name).first()
    if existing:
        return existing, False
    return PrinterManufacturer.objects.create(name=name), True


def _merge_model(row, ref):
    maker, maker_created = _get_or_create_manufacturer(row["vendor"])
    item = PrinterCatalogModel.objects.filter(
        manufacturer=maker,
        name__iexact=row["name"],
    ).first()

    provenance = {
        "repository": ORCA_REPOSITORY,
        "ref": ref,
        "license": ORCA_LICENSE,
        "vendor_file": row["vendor_file"],
        "vendor_version": row.get("vendor_version", ""),
        "machine_profile": row["sub_path"],
        "upstream_name": row["raw_name"],
    }

    if item is None:
        features = {"orcaslicer": provenance}
        item = PrinterCatalogModel.objects.create(
            manufacturer=maker,
            name=row["name"],
            multi_material_system=row["multi_material_system"],
            features=features,
            source_url=row["source_url"],
        )
        return maker_created, True, False

    changed = False
    features = dict(item.features or {})
    if features.get("orcaslicer") != provenance:
        features["orcaslicer"] = provenance
        item.features = features
        changed = True

    if not item.source_url and row["source_url"]:
        item.source_url = row["source_url"]
        changed = True

    if not item.multi_material_system and row["multi_material_system"]:
        item.multi_material_system = row["multi_material_system"]
        changed = True

    if changed:
        item.save(update_fields=[
            "features",
            "source_url",
            "multi_material_system",
            "updated_at",
        ])
    return maker_created, False, changed


def sync_orcaslicer_printer_catalogue(*, ref=None, max_workers=8):
    """Augment MakerVault's printer catalogue from OrcaSlicer's model manifests.

    MakerVault never deletes local models and never replaces populated hardware
    specifications. Orca is used for breadth and provenance; MakerVault's
    curated/manual facts remain authoritative.
    """
    ref = str(ref or getattr(settings, "ORCASLICER_PRINTER_CATALOGUE_REF", "main")).strip() or "main"
    response = requests.get(
        ORCA_DIRECTORY_URL,
        params={"ref": ref},
        timeout=(5, 20),
        headers={
            "User-Agent": _user_agent(),
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        response.raise_for_status()
        listing = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise OrcaCatalogueError(f"Could not read the OrcaSlicer printer catalogue: {exc}") from exc
    finally:
        response.close()

    if not isinstance(listing, list):
        raise OrcaCatalogueError("OrcaSlicer returned an unexpected profile directory response.")

    entries = [
        entry for entry in listing
        if isinstance(entry, dict)
        and entry.get("type") == "file"
        and str(entry.get("name") or "").lower().endswith(".json")
        and str(entry.get("name") or "") not in {"blacklist.json", "Custom.json", "OrcaFilamentLibrary.json"}
    ]

    vendors_seen = 0
    models_seen = 0
    manufacturers_created = 0
    models_created = 0
    models_enriched = 0
    failed_vendors = []

    with ThreadPoolExecutor(max_workers=max(1, min(int(max_workers), 12))) as executor:
        futures = {executor.submit(_fetch_vendor_manifest, entry, ref): entry for entry in entries}
        results = []
        for future in as_completed(futures):
            entry = futures[future]
            try:
                vendor, rows = future.result()
                if rows:
                    results.append((vendor, rows))
            except (requests.RequestException, OrcaCatalogueError, ValueError) as exc:
                failed_vendors.append({
                    "file": str(entry.get("name") or ""),
                    "error": str(exc)[:300],
                })

    # Merge duplicate upstream representations (notably CFS-C profiles) before
    # touching the database.
    merged_rows = {}
    for vendor, rows in results:
        vendors_seen += 1
        for row in rows:
            key = (vendor.casefold(), row["name"].casefold())
            existing = merged_rows.get(key)
            if existing:
                if not existing["multi_material_system"] and row["multi_material_system"]:
                    existing["multi_material_system"] = row["multi_material_system"]
                continue
            merged_rows[key] = row

    models_seen = len(merged_rows)
    with transaction.atomic():
        for row in sorted(merged_rows.values(), key=lambda x: (x["vendor"].casefold(), x["name"].casefold())):
            maker_created, model_created, model_enriched = _merge_model(row, ref)
            manufacturers_created += int(maker_created)
            models_created += int(model_created)
            models_enriched += int(model_enriched)

    return {
        "status": "complete" if not failed_vendors else "partial",
        "source": ORCA_REPOSITORY,
        "ref": ref,
        "license": ORCA_LICENSE,
        "vendors_seen": vendors_seen,
        "models_seen": models_seen,
        "manufacturers_created": manufacturers_created,
        "models_created": models_created,
        "models_enriched": models_enriched,
        "failed_vendors": failed_vendors,
    }
