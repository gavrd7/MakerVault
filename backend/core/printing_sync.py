from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlparse

import requests
import websockets
from websockets.exceptions import WebSocketException
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import (
    ExternalPrinterLink,
    ExternalSpoolLink,
    FilamentManufacturer,
    FilamentProduct,
    Printer,
    PrinterFilamentSlot,
    PrintingIntegrationSetting,
    PrintingLocation,
    PrintJob,
    PrintMaterialUsage,
    Spool,
)
from .printing_integrations import normalise_service_url


logger = logging.getLogger(__name__)


class PrintingSyncError(RuntimeError):
    pass


class PrintingSyncConnectionError(PrintingSyncError):
    pass


def next_spool_id(owner=None) -> str:
    highest = 0
    qs = Spool.objects.all()
    if owner is not None:
        qs = qs.filter(owner=owner)
    for value in qs.filter(spool_id__startswith="SPL-").values_list("spool_id", flat=True):
        match = re.fullmatch(r"SPL-(\d+)", value or "")
        if match:
            highest = max(highest, int(match.group(1)))
    candidate = highest + 1
    while qs.filter(spool_id=f"SPL-{candidate:04d}").exists():
        candidate += 1
    return f"SPL-{candidate:04d}"


def _as_decimal(value, places=None):
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
        if places is not None:
            quantum = Decimal("1").scaleb(-int(places))
            result = result.quantize(quantum, rounding=ROUND_HALF_UP)
        return result
    except (InvalidOperation, TypeError, ValueError):
        return None


def _normalise_hex(value: str | None) -> str:
    raw = str(value or "").strip().lstrip("#")
    if len(raw) == 7 and raw.startswith("0"):
        raw = raw[1:]
    if len(raw) >= 8:
        raw = raw[:6]
    if re.fullmatch(r"[0-9a-fA-F]{6}", raw):
        return "#" + raw.lower()
    return ""


def _spoolman_api_root(endpoint_url: str) -> str:
    base = normalise_service_url(endpoint_url)
    return base if base.endswith("/api/v1") else base + "/api/v1"


def _spoolman_response_error(response) -> str:
    """Extract Spoolman's useful API error text without exposing HTML bodies."""
    detail = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            detail = str(
                payload.get("message")
                or payload.get("detail")
                or payload.get("error")
                or ""
            ).strip()
    except ValueError:
        pass
    if detail:
        return f"HTTP {response.status_code}: {detail}"
    return f"HTTP {response.status_code}"


def _spoolman_get_spools(endpoint_url: str) -> tuple[str, list[dict]]:
    root = _spoolman_api_root(endpoint_url)
    try:
        response = requests.get(
            root + "/spool",
            params={"allow_archived": "true"},
            headers={"User-Agent": "MakerVault/0.6 (Spoolman sync)"},
            timeout=(4, 20),
        )
    except requests.RequestException as exc:
        raise PrintingSyncConnectionError("MakerVault could not reach the Spoolman server.") from exc
    if response.status_code != 200:
        raise PrintingSyncError(f"Spoolman returned {_spoolman_response_error(response)} while reading spools.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise PrintingSyncError("Spoolman returned invalid JSON while reading spools.") from exc
    if not isinstance(payload, list):
        raise PrintingSyncError("Spoolman returned an unexpected spool list.")
    return root, payload


def _normalise_match_text(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _spoolman_snapshot(remote: dict) -> dict:
    filament_data = remote.get("filament") or {}
    if not isinstance(filament_data, dict):
        filament_data = {}
    vendor_data = filament_data.get("vendor") or {}
    if not isinstance(vendor_data, dict):
        vendor_data = {}

    remaining = _as_decimal(remote.get("remaining_weight"), 2)
    initial = _as_decimal(remote.get("initial_weight"), 2)
    if initial is None:
        initial = _as_decimal(filament_data.get("weight"), 2)

    return {
        "external_id": str(remote.get("id") or "").strip(),
        "filament_external_id": str(filament_data.get("id") or "").strip(),
        "vendor_external_id": str(vendor_data.get("id") or "").strip(),
        "vendor": str(vendor_data.get("name") or "").strip()[:200],
        "name": str(filament_data.get("name") or filament_data.get("material") or "Spoolman filament").strip()[:255],
        "material": str(filament_data.get("material") or "Unknown").strip()[:80],
        "color_hex": _normalise_hex(filament_data.get("color_hex")),
        "diameter_mm": _as_decimal(filament_data.get("diameter"), 2) or Decimal("1.75"),
        "density_g_cm3": _as_decimal(filament_data.get("density"), 3),
        "nominal_weight_g": _as_decimal(filament_data.get("weight"), 2),
        "empty_spool_weight_g": _as_decimal(filament_data.get("spool_weight"), 2),
        "nozzle_temp_c": filament_data.get("settings_extruder_temp") or None,
        "bed_temp_c": filament_data.get("settings_bed_temp") or None,
        "initial_weight_g": initial,
        "remaining_weight_g": remaining,
        "purchase_cost": _as_decimal(remote.get("price"), 2),
        "location": str(remote.get("location") or "").strip()[:200],
        "comment": str(remote.get("comment") or "").strip(),
        "archived": bool(remote.get("archived")),
        "status": "retired" if bool(remote.get("archived")) else (
            "empty" if remaining is not None and remaining <= 0 else "open"
        ),
    }


def _decimal_near(left, right, tolerance=Decimal("0.08")) -> bool:
    left = _as_decimal(left)
    right = _as_decimal(right)
    if left is None or right is None:
        return False
    scale = max(abs(left), abs(right), Decimal("1"))
    return abs(left - right) / scale <= tolerance


def _spoolman_filament_score(snapshot: dict, filament: FilamentProduct) -> int:
    maker = filament.filament_manufacturer or filament.manufacturer
    score = 0
    remote_material = _normalise_match_text(snapshot.get("material"))
    local_material = _normalise_match_text(filament.material)
    if remote_material and local_material == remote_material:
        score += 30

    remote_vendor = _normalise_match_text(snapshot.get("vendor"))
    local_vendor = _normalise_match_text(maker.name if maker else "")
    if remote_vendor and local_vendor == remote_vendor:
        score += 25

    remote_name = _normalise_match_text(snapshot.get("name"))
    local_name = _normalise_match_text(filament.name)
    if remote_name and local_name:
        if remote_name == local_name:
            score += 25
        elif remote_name in local_name or local_name in remote_name:
            score += 15

    remote_color = str(snapshot.get("color_hex") or "").casefold()
    local_color = str(filament.color_hex or "").casefold()
    if remote_color and local_color and remote_color == local_color:
        score += 15

    if _decimal_near(snapshot.get("diameter_mm"), filament.diameter_mm, Decimal("0.01")):
        score += 5
    return score


def _rank_spoolman_filaments(snapshot: dict) -> list[tuple[int, FilamentProduct]]:
    rows = []
    for filament in FilamentProduct.objects.select_related(
        "filament_manufacturer", "manufacturer"
    ).all():
        score = _spoolman_filament_score(snapshot, filament)
        if score >= 45:
            rows.append((score, filament))
    rows.sort(key=lambda item: (-item[0], str(item[1])))
    return rows[:8]


def _create_filament_from_spoolman(snapshot: dict) -> FilamentProduct:
    maker_name = snapshot.get("vendor") or "Generic"
    maker = FilamentManufacturer.objects.filter(name__iexact=maker_name).first()
    if maker is None:
        maker = FilamentManufacturer.objects.create(name=maker_name)
    profile = {
        "spoolman": {
            "filament_id": snapshot.get("filament_external_id", ""),
            "vendor_id": snapshot.get("vendor_external_id", ""),
        },
        "import_policy": "created_after_duplicate_check",
    }
    filament = FilamentProduct(
        filament_manufacturer=maker,
        name=snapshot.get("name") or snapshot.get("material") or "Spoolman filament",
        material=snapshot.get("material") or "Unknown",
        color_hex=snapshot.get("color_hex") or "",
        diameter_mm=snapshot.get("diameter_mm") or Decimal("1.75"),
        density_g_cm3=snapshot.get("density_g_cm3"),
        nominal_weight_g=snapshot.get("nominal_weight_g"),
        empty_spool_weight_g=snapshot.get("empty_spool_weight_g"),
        nozzle_temp_min_c=snapshot.get("nozzle_temp_c"),
        bed_temp_min_c=snapshot.get("bed_temp_c"),
        profile_data=profile,
    )
    filament.full_clean()
    filament.save()
    return filament


def _spoolman_location(name: str, owner=None):
    value = str(name or "").strip()[:200]
    if not value:
        return None
    location = PrintingLocation.objects.filter(name__iexact=value, owner=owner).first()
    if location is not None:
        return location
    return PrintingLocation.objects.create(
        owner=owner,
        name=value,
        kind="storage",
        notes="Location discovered from Spoolman. MakerVault remains authoritative for spool placement.",
    )


def _rank_spoolman_spools(snapshot: dict, owner) -> list[dict]:
    rows = []
    qs = Spool.objects.filter(owner=owner).select_related(
        "filament__filament_manufacturer",
        "filament__manufacturer",
        "storage_location",
        "assigned_printer",
    ).exclude(external_links__provider="spoolman")
    for spool in qs:
        score = _spoolman_filament_score(snapshot, spool.filament)
        if _decimal_near(snapshot.get("initial_weight_g"), spool.initial_weight_g):
            score += 8
        if _decimal_near(snapshot.get("remaining_weight_g"), spool.remaining_weight_g):
            score += 8

        remote_location = _normalise_match_text(snapshot.get("location"))
        local_location = _normalise_match_text(
            spool.assigned_printer.name if spool.assigned_printer_id
            else spool.storage_location.name if spool.storage_location_id
            else spool.location
        )
        if remote_location and local_location and remote_location == local_location:
            score += 4

        if score >= 70:
            rows.append({
                "score": score,
                "spool": spool,
            })
    rows.sort(key=lambda item: (-item["score"], item["spool"].spool_id))
    return rows[:8]


def _spoolman_review_payload(remote: dict, snapshot: dict, filament_matches, spool_matches, reason: str) -> dict:
    return {
        "provider": "spoolman",
        "external_id": snapshot.get("external_id", ""),
        "reason": reason,
        "detected_at": timezone.now().isoformat(),
        "remote": {
            "vendor": snapshot.get("vendor", ""),
            "name": snapshot.get("name", ""),
            "material": snapshot.get("material", ""),
            "color_hex": snapshot.get("color_hex", ""),
            "diameter_mm": float(snapshot["diameter_mm"]) if snapshot.get("diameter_mm") is not None else None,
            "initial_weight_g": float(snapshot["initial_weight_g"]) if snapshot.get("initial_weight_g") is not None else None,
            "remaining_weight_g": float(snapshot["remaining_weight_g"]) if snapshot.get("remaining_weight_g") is not None else None,
            "location": snapshot.get("location", ""),
            "status": snapshot.get("status", ""),
            "comment": snapshot.get("comment", ""),
        },
        "filament_candidates": [
            {
                "score": score,
                "id": str(filament.id),
                "name": str(filament),
                "material": filament.material,
                "color_hex": filament.color_hex,
            }
            for score, filament in filament_matches[:5]
        ],
        "spool_candidates": [
            {
                "score": row["score"],
                "id": str(row["spool"].id),
                "spool_id": row["spool"].spool_id,
                "filament": str(row["spool"].filament),
                "remaining_weight_g": float(row["spool"].remaining_weight_g) if row["spool"].remaining_weight_g is not None else None,
                "location": (
                    row["spool"].assigned_printer.name if row["spool"].assigned_printer_id
                    else row["spool"].storage_location.name if row["spool"].storage_location_id
                    else row["spool"].location
                ),
            }
            for row in spool_matches[:5]
        ],
        "raw": remote,
    }


def _create_spool_with_generated_id(*, owner, **kwargs) -> Spool:
    for _ in range(5):
        try:
            with transaction.atomic():
                item = Spool(owner=owner, spool_id=next_spool_id(owner), **kwargs)
                item.full_clean()
                item.save()
                return item
        except IntegrityError:
            continue
    raise PrintingSyncError("MakerVault could not allocate a unique spool ID.")


def _update_linked_spool_from_spoolman(spool: Spool, snapshot: dict):
    """Import useful telemetry without replacing MakerVault-owned identity or placement."""
    changed = []
    remaining = snapshot.get("remaining_weight_g")
    if remaining is not None and spool.remaining_weight_g != remaining:
        spool.remaining_weight_g = remaining
        changed.append("remaining_weight_g")
    if spool.initial_weight_g is None and snapshot.get("initial_weight_g") is not None:
        spool.initial_weight_g = snapshot["initial_weight_g"]
        changed.append("initial_weight_g")
    if spool.purchase_cost is None and snapshot.get("purchase_cost") is not None:
        spool.purchase_cost = snapshot["purchase_cost"]
        changed.append("purchase_cost")
    if changed:
        spool.full_clean()
        spool.save(update_fields=changed + ["updated_at"])


def _spoolman_pending_reviews(setting: PrintingIntegrationSetting) -> list[dict]:
    config = setting.config or {}
    rows = config.get("pending_reviews") or []
    return rows if isinstance(rows, list) else []


def resolve_spoolman_review(
    setting: PrintingIntegrationSetting,
    external_id: str,
    action: str,
    *,
    spool_id: str | None = None,
    filament_id: str | None = None,
) -> dict:
    if setting.provider != "spoolman":
        raise PrintingSyncError("Review resolution is not implemented for this integration yet.")

    external_id = str(external_id or "").strip()
    reviews = _spoolman_pending_reviews(setting)
    review = next((row for row in reviews if str(row.get("external_id")) == external_id), None)
    if not review:
        raise PrintingSyncError("That pending import review no longer exists.")

    config = dict(setting.config or {})
    ignored = {str(value) for value in (config.get("ignored_external_ids") or [])}
    remote = review.get("raw") or {}
    snapshot = _spoolman_snapshot(remote)
    root = _spoolman_api_root(setting.endpoint_url)
    now = timezone.now()

    if action == "ignore":
        ignored.add(external_id)
        result = {"action": "ignored", "external_id": external_id}
    elif action == "link":
        spool = Spool.objects.select_related("filament").filter(pk=spool_id, owner=setting.owner).first()
        if not spool:
            raise PrintingSyncError("Choose a MakerVault spool to link.")
        if ExternalSpoolLink.objects.filter(spool=spool, provider="spoolman").exists():
            raise PrintingSyncError("That MakerVault spool already has a Spoolman link.")
        _update_linked_spool_from_spoolman(spool, snapshot)
        link = ExternalSpoolLink.objects.create(
            spool=spool,
            provider="spoolman",
            external_id=external_id,
            external_url=f"{root.rsplit('/api/v1', 1)[0]}/spool/show/{external_id}",
            sync_direction=setting.sync_direction,
            last_synced_at=now,
            sync_metadata={"remote": remote, "linked_by_review": True},
        )
        result = {"action": "linked", "external_id": external_id, "spool_id": str(spool.id), "spool_code": spool.spool_id}
    elif action == "create":
        filament = None
        if filament_id:
            filament = FilamentProduct.objects.filter(pk=filament_id).first()
            if not filament:
                raise PrintingSyncError("Selected MakerVault filament was not found.")
        if filament is None:
            filament = _create_filament_from_spoolman(snapshot)
        location = _spoolman_location(snapshot.get("location"), setting.owner)
        spool = _create_spool_with_generated_id(
            owner=setting.owner,
            filament=filament,
            initial_weight_g=snapshot.get("initial_weight_g"),
            remaining_weight_g=snapshot.get("remaining_weight_g"),
            purchase_cost=snapshot.get("purchase_cost"),
            storage_location=location,
            status=snapshot.get("status") or "open",
            notes=snapshot.get("comment") or "",
        )
        ExternalSpoolLink.objects.create(
            spool=spool,
            provider="spoolman",
            external_id=external_id,
            external_url=f"{root.rsplit('/api/v1', 1)[0]}/spool/show/{external_id}",
            sync_direction=setting.sync_direction,
            last_synced_at=now,
            sync_metadata={"remote": remote, "created_by_review": True},
        )
        result = {"action": "created", "external_id": external_id, "spool_id": str(spool.id), "spool_code": spool.spool_id}
    else:
        raise PrintingSyncError("Unknown review action.")

    config["pending_reviews"] = [
        row for row in reviews if str(row.get("external_id")) != external_id
    ]
    config["ignored_external_ids"] = sorted(ignored)
    setting.config = config
    setting.save(update_fields=["config", "updated_at"])
    return result


def sync_spoolman(setting: PrintingIntegrationSetting) -> dict:
    root, remote_spools = _spoolman_get_spools(setting.endpoint_url)
    direction = setting.sync_direction
    do_import = direction in {"import", "bidirectional"}
    do_export = direction in {"export", "bidirectional"}

    created = 0
    linked_existing = 0
    updated = 0
    exported = 0
    skipped_unlinked = 0
    review_queued = 0
    ignored_count = 0
    locations_discovered = 0
    now = timezone.now()

    config = dict(setting.config or {})
    pending = {
        str(row.get("external_id")): row
        for row in _spoolman_pending_reviews(setting)
        if row.get("external_id") not in (None, "")
    }
    ignored = {str(value) for value in (config.get("ignored_external_ids") or [])}
    seen_remote_ids = set()

    if do_import:
        for remote in remote_spools:
            snapshot = _spoolman_snapshot(remote)
            external_id = snapshot["external_id"]
            if not external_id:
                continue
            seen_remote_ids.add(external_id)

            if external_id in ignored:
                ignored_count += 1
                pending.pop(external_id, None)
                continue

            location = None
            if snapshot.get("location"):
                before = PrintingLocation.objects.filter(name=snapshot["location"], owner=setting.owner).exists()
                location = _spoolman_location(snapshot["location"], setting.owner)
                if location and not before:
                    locations_discovered += 1

            link = ExternalSpoolLink.objects.select_related("spool").filter(
                spool__owner=setting.owner,
                provider="spoolman",
                external_id=external_id,
            ).first()

            if link:
                _update_linked_spool_from_spoolman(link.spool, snapshot)
                link.sync_direction = direction
                link.last_synced_at = now
                link.sync_metadata = {
                    "remote": remote,
                    "authority": {
                        "makervault_primary": True,
                        "remote_location": snapshot.get("location", ""),
                        "remote_status": snapshot.get("status", ""),
                    },
                }
                link.save(update_fields=["sync_direction", "last_synced_at", "sync_metadata", "updated_at"])
                pending.pop(external_id, None)
                updated += 1
                continue

            filament_matches = _rank_spoolman_filaments(snapshot)
            spool_matches = _rank_spoolman_spools(snapshot, setting.owner)

            filament_ambiguous = False
            selected_filament = None
            if filament_matches:
                top_score = filament_matches[0][0]
                second_score = filament_matches[1][0] if len(filament_matches) > 1 else 0
                if top_score >= 75 and (len(filament_matches) == 1 or top_score - second_score >= 12):
                    selected_filament = filament_matches[0][1]
                elif top_score >= 55:
                    filament_ambiguous = True

            if spool_matches or filament_ambiguous:
                reason = "possible_duplicate_spool" if spool_matches else "ambiguous_filament"
                pending[external_id] = _spoolman_review_payload(
                    remote, snapshot, filament_matches, spool_matches, reason
                )
                review_queued += 1
                continue

            if selected_filament is None:
                selected_filament = _create_filament_from_spoolman(snapshot)

            spool = _create_spool_with_generated_id(
                owner=setting.owner,
                filament=selected_filament,
                initial_weight_g=snapshot.get("initial_weight_g"),
                remaining_weight_g=snapshot.get("remaining_weight_g"),
                purchase_cost=snapshot.get("purchase_cost"),
                storage_location=location,
                status=snapshot.get("status") or "open",
                notes=snapshot.get("comment") or "",
            )
            ExternalSpoolLink.objects.create(
                spool=spool,
                provider="spoolman",
                external_id=external_id,
                external_url=f"{root.rsplit('/api/v1', 1)[0]}/spool/show/{external_id}",
                sync_direction=direction,
                last_synced_at=now,
                sync_metadata={"remote": remote, "auto_imported_after_duplicate_check": True},
            )
            pending.pop(external_id, None)
            created += 1

        pending = {
            external_id: row
            for external_id, row in pending.items()
            if external_id in seen_remote_ids
        }
        config["pending_reviews"] = list(pending.values())
        config["ignored_external_ids"] = sorted(ignored)
        setting.config = config

    if do_export:
        links = list(
            ExternalSpoolLink.objects.select_related(
                "spool__storage_location",
                "spool__assigned_printer",
            ).filter(provider="spoolman", spool__owner=setting.owner)
        )
        linked_ids = {link.spool_id for link in links}
        skipped_unlinked = Spool.objects.filter(owner=setting.owner).exclude(pk__in=linked_ids).count()
        for link in links:
            spool = link.spool
            location = ""
            if spool.assigned_printer_id:
                location = spool.assigned_printer.name
            elif spool.storage_location_id:
                location = spool.storage_location.name
            elif spool.location:
                location = spool.location
            payload = {
                "archived": spool.status == "retired",
                "location": location[:64],
            }
            if spool.remaining_weight_g is not None:
                payload["remaining_weight"] = float(spool.remaining_weight_g)
            if spool.notes:
                payload["comment"] = spool.notes[:1024]
            try:
                response = requests.patch(
                    f"{root}/spool/{link.external_id}",
                    json=payload,
                    headers={"User-Agent": "MakerVault/0.6 (Spoolman sync)"},
                    timeout=(4, 20),
                )
            except requests.RequestException as exc:
                raise PrintingSyncConnectionError(
                    f"Spoolman became unreachable while updating spool {link.external_id}."
                ) from exc
            if response.status_code not in {200, 201}:
                raise PrintingSyncError(
                    f"Spoolman returned {_spoolman_response_error(response)} "
                    f"while updating spool {link.external_id}."
                )
            link.last_synced_at = now
            link.save(update_fields=["last_synced_at", "updated_at"])
            exported += 1

    return {
        "provider": "spoolman",
        "remote_spools": len(remote_spools),
        "created": created,
        "linked_existing": linked_existing,
        "updated": updated,
        "exported": exported,
        "pending_review": len(config.get("pending_reviews") or []),
        "review_queued": review_queued,
        "ignored": ignored_count,
        "locations_discovered": locations_discovered,
        "unlinked_local_spools_skipped": skipped_unlinked,
        "authority": "makervault_primary",
    }



def _simplyprint_root(setting: PrintingIntegrationSetting) -> tuple[str, str]:
    base = normalise_service_url(setting.endpoint_url or "https://api.simplyprint.io")
    config = dict(setting.config or {})
    company_id = str(config.get("company_id") or "").strip()
    api_key = str(config.get("api_key") or "").strip()
    if not company_id.isdigit() or int(company_id) <= 0:
        raise PrintingSyncError("SimplyPrint account/company ID is not configured.")
    if not api_key:
        raise PrintingSyncError("SimplyPrint API key is not configured.")
    return f"{base}/{company_id}", api_key


def _simplyprint_request(setting, endpoint, *, method="GET", params=None, json_body=None):
    root, api_key = _simplyprint_root(setting)
    url = root + "/" + endpoint.lstrip("/")
    headers = {
        "Accept": "application/json",
        "X-API-KEY": api_key,
        "User-Agent": "MakerVault/0.6 (+SimplyPrint read-only sync)",
    }
    try:
        response = requests.request(
            method,
            url,
            params=params,
            json=json_body,
            headers=headers,
            timeout=(5, 25),
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise PrintingSyncConnectionError("MakerVault could not reach the SimplyPrint API.") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise PrintingSyncError(f"SimplyPrint returned invalid JSON from {endpoint}.") from exc
    if not isinstance(payload, dict):
        raise PrintingSyncError(f"SimplyPrint returned an unexpected response from {endpoint}.")
    if response.status_code >= 400 or payload.get("status") is False:
        message = str(payload.get("message") or "").strip()
        detail = f": {message}" if message else ""
        raise PrintingSyncError(
            f"SimplyPrint returned HTTP {response.status_code}{detail} from {endpoint}."
        )
    return payload


def _simplyprint_printers(setting) -> list[dict]:
    page = 1
    rows = []
    while page <= 100:
        payload = _simplyprint_request(
            setting,
            "printers/Get",
            method="POST",
            json_body={"page": page, "page_size": 100},
        )
        batch = payload.get("data") or []
        if isinstance(batch, dict):
            batch = [batch]
        if not isinstance(batch, list):
            raise PrintingSyncError("SimplyPrint returned an unexpected printer list.")
        rows.extend(item for item in batch if isinstance(item, dict))
        page_amount = int(payload.get("page_amount") or 1)
        if page >= page_amount or not batch:
            break
        page += 1
    return rows


def _simplyprint_filaments(setting) -> dict[str, dict]:
    payload = _simplyprint_request(setting, "filament/GetFilament")
    remote = payload.get("filament") or {}
    if isinstance(remote, list):
        return {
            str(item.get("id")): item
            for item in remote
            if isinstance(item, dict) and item.get("id") not in (None, "")
        }
    if not isinstance(remote, dict):
        return {}
    return {
        str(key): value
        for key, value in remote.items()
        if isinstance(value, dict)
    }


def _simplyprint_jobs(setting) -> list[dict]:
    config = dict(setting.config or {})
    try:
        limit = int(config.get("history_page_size") or 50)
    except (TypeError, ValueError):
        limit = 50
    limit = min(max(limit, 1), 100)
    payload = _simplyprint_request(
        setting,
        "jobs/GetPaginatedPrintJobs",
        method="POST",
        json_body={"page": 1, "page_size": limit},
    )
    rows = payload.get("data") or []
    return [item for item in rows if isinstance(item, dict)] if isinstance(rows, list) else []


def _simplyprint_remote_name(row: dict) -> str:
    printer_data = row.get("printer") or {}
    if not isinstance(printer_data, dict):
        printer_data = {}
    return str(printer_data.get("name") or f"SimplyPrint printer {row.get('id')}").strip()


def _simplyprint_remote_model(row: dict) -> str:
    printer_data = row.get("printer") or {}
    if not isinstance(printer_data, dict):
        printer_data = {}
    return str(
        printer_data.get("model")
        or printer_data.get("printerModel")
        or printer_data.get("type")
        or printer_data.get("api")
        or _simplyprint_remote_name(row)
    ).strip()[:255]


def _simplyprint_link_printer(row: dict, now, owner=None):
    external_id = str(row.get("id") or "").strip()
    if not external_id:
        return None, False, False

    link = ExternalPrinterLink.objects.select_related("printer").filter(
        printer__owner=owner,
        provider="simplyprint",
        external_id=external_id,
    ).first()
    created = False
    linked_existing = False

    if link:
        printer = link.printer
    else:
        remote_name = _simplyprint_remote_name(row)
        candidates = list(Printer.objects.filter(owner=owner, name__iexact=remote_name)[:2])
        if len(candidates) == 1 and not candidates[0].external_links.filter(provider="simplyprint").exists():
            printer = candidates[0]
            linked_existing = True
        else:
            printer = Printer.objects.create(
                owner=owner,
                name=remote_name,
                model=_simplyprint_remote_model(row),
                is_active=True,
                profile_data={"created_from": "simplyprint"},
            )
            created = True
        link = ExternalPrinterLink.objects.create(
            printer=printer,
            provider="simplyprint",
            external_id=external_id,
            external_url="",
        )

    printer_data = row.get("printer") or {}
    if not isinstance(printer_data, dict):
        printer_data = {}
    profile = dict(printer.profile_data or {})
    profile["simplyprint"] = {
        "external_id": external_id,
        "name": _simplyprint_remote_name(row),
        "state": printer_data.get("state"),
        "online": printer_data.get("online"),
        "group_id": printer_data.get("group"),
        "group_name": printer_data.get("groupName"),
        "api": printer_data.get("api"),
        "ui": printer_data.get("ui"),
        "ip": printer_data.get("ip"),
        "firmware": printer_data.get("firmware"),
        "firmware_version": printer_data.get("firmwareVersion"),
        "simplyprint_version": printer_data.get("spVersion"),
        "last_online": printer_data.get("lastOnline"),
        "temperatures": printer_data.get("temps") if isinstance(printer_data.get("temps"), dict) else {},
        "notifications": row.get("notifications") if isinstance(row.get("notifications"), list) else [],
        "last_synced_at": now.isoformat(),
    }
    printer.profile_data = profile
    printer.save(update_fields=["profile_data", "updated_at"])

    link.last_synced_at = now
    link.sync_metadata = {
        "remote_name": _simplyprint_remote_name(row),
        "state": printer_data.get("state"),
        "online": printer_data.get("online"),
        "group_name": printer_data.get("groupName"),
    }
    link.save(update_fields=["last_synced_at", "sync_metadata", "updated_at"])
    return printer, created, linked_existing


def _simplyprint_filament_record(value, inventory):
    if not isinstance(value, dict):
        return {}
    external_id = str(value.get("id") or value.get("filamentId") or "").strip()
    detailed = inventory.get(external_id, {}) if external_id else {}
    merged = {**detailed, **value}
    if external_id:
        merged["id"] = external_id
    return merged


def _simplyprint_slot_fingerprint(remote: dict) -> str:
    return "|".join([
        str(remote.get("id") or "").strip().casefold(),
        str(remote.get("uid") or "").strip().casefold(),
        str(remote.get("nfcId") or "").strip().casefold(),
        _normalise_hex(remote.get("colorHex")).casefold(),
        _normalise_match_text((remote.get("type") or {}).get("name") if isinstance(remote.get("type"), dict) else remote.get("type")),
    ])


def _sync_simplyprint_slots(printer, row, inventory, now) -> dict:
    filament_map = row.get("filament") or {}
    if isinstance(filament_map, list):
        filament_map = {str(index): value for index, value in enumerate(filament_map)}
    if not isinstance(filament_map, dict):
        filament_map = {}

    seen = set()
    loaded = 0
    exact_spool_links = 0
    for raw_index, value in filament_map.items():
        remote = _simplyprint_filament_record(value, inventory)
        if not remote:
            continue
        try:
            slot_index = int(remote.get("extruder") if remote.get("extruder") is not None else raw_index)
        except (TypeError, ValueError):
            slot_index = len(seen)
        unit_index = int(remote.get("nozzle") or 0) if str(remote.get("nozzle") or "0").isdigit() else 0
        seen.add((unit_index, slot_index))

        external_spool_id = str(remote.get("id") or "").strip()
        linked_spool = None
        if external_spool_id:
            external_link = ExternalSpoolLink.objects.select_related("spool").filter(
                spool__owner=printer.owner,
                provider="simplyprint",
                external_id=external_spool_id,
            ).first()
            if external_link:
                linked_spool = external_link.spool
                exact_spool_links += 1

        existing = PrinterFilamentSlot.objects.filter(
            printer=printer,
            system="simplyprint",
            unit_index=unit_index,
            slot_index=slot_index,
        ).first()
        fingerprint = _simplyprint_slot_fingerprint(remote)
        if not linked_spool and existing and existing.spool_id:
            existing_meta = existing.metadata or {}
            if (
                existing_meta.get("external_spool_id") == external_spool_id
                and existing_meta.get("material_fingerprint") == fingerprint
                and existing_meta.get("link_source") in {"user_linked_existing", "inventory_created_from_slot"}
            ):
                linked_spool = existing.spool

        type_data = remote.get("type") or {}
        material = type_data.get("name") if isinstance(type_data, dict) else type_data
        color_hex = _normalise_hex(remote.get("colorHex"))
        metadata = {
            "vendor": str(remote.get("brand") or "").strip(),
            "product_name": str(remote.get("productionId") or remote.get("prodId") or "").strip(),
            "external_spool_id": external_spool_id,
            "remote_uid": str(remote.get("uid") or "").strip(),
            "nfc_id": str(remote.get("nfcId") or "").strip(),
            "qr_id": str(remote.get("qrId") or "").strip(),
            "material_fingerprint": fingerprint,
            "remote_total_length_mm": remote.get("total"),
            "remote_remaining_length_mm": remote.get("left"),
            "remote_cost": remote.get("cost"),
            "source": "simplyprint",
            "physical_tag_uid_available": bool(remote.get("nfcId")),
        }
        if linked_spool and existing:
            previous = existing.metadata or {}
            if previous.get("link_source"):
                metadata["link_source"] = previous.get("link_source")
                metadata["link_confirmed_at"] = previous.get("link_confirmed_at")

        PrinterFilamentSlot.objects.update_or_create(
            printer=printer,
            system="simplyprint",
            unit_index=unit_index,
            slot_index=slot_index,
            defaults={
                "spool": linked_spool,
                "external_ref": f"simplyprint:{printer.id}:{slot_index}:{external_spool_id}",
                "rfid_uid": str(remote.get("nfcId") or "").strip().upper(),
                "material": str(material or "").strip()[:80],
                "color_name": str(remote.get("colorName") or "").strip()[:120],
                "color_hex": color_hex,
                "remaining_weight_g": None,
                "is_loaded": True,
                "last_seen_at": now,
                "metadata": metadata,
            },
        )
        loaded += 1

    for slot in PrinterFilamentSlot.objects.filter(
        printer=printer,
        system="simplyprint",
        is_loaded=True,
    ):
        if (slot.unit_index, slot.slot_index) not in seen:
            slot.is_loaded = False
            slot.spool = None
            slot.last_seen_at = now
            slot.save(update_fields=["is_loaded", "spool", "last_seen_at", "updated_at"])

    return {"loaded_slots": loaded, "exact_spool_links": exact_spool_links}


def _simplyprint_job_status(value):
    raw = str(value or "").casefold()
    return {
        "ongoing": "printing",
        "printing": "printing",
        "done": "success",
        "finished": "success",
        "success": "success",
        "failed": "failed",
        "cancelled": "cancelled",
        "canceled": "cancelled",
    }.get(raw, "planned")


def _simplyprint_actual_minutes(row):
    start = parse_datetime(str(row.get("startDate") or "")) if row.get("startDate") else None
    end = parse_datetime(str(row.get("endDate") or "")) if row.get("endDate") else None
    if start and end and end >= start:
        return max(int((end - start).total_seconds() // 60), 0)
    return None


def _sync_simplyprint_jobs(rows, printer_links) -> tuple[int, int]:
    created = updated = 0
    for remote in rows:
        external_id = str(remote.get("id") or remote.get("uid") or "").strip()
        printer_external_id = str(remote.get("printer") or "").strip()
        printer = printer_links.get(printer_external_id)
        if not external_id or not printer:
            continue

        existing = PrintJob.objects.filter(
            owner=printer.owner,
            settings__external_provider="simplyprint",
            settings__external_id=external_id,
        ).first()
        metadata = {
            "external_provider": "simplyprint",
            "external_id": external_id,
            "external_uid": str(remote.get("uid") or ""),
            "filename": str(remote.get("filename") or ""),
            "start_date": remote.get("startDate"),
            "end_date": remote.get("endDate"),
            "outside_system": bool(remote.get("outsideSystem")),
            "autoprint": bool(remote.get("autoprint")),
            "remote_rating": remote.get("rating"),
            "current_percentage": remote.get("currentPercentage"),
        }
        if existing:
            existing.status = _simplyprint_job_status(remote.get("status"))
            existing.actual_minutes = _simplyprint_actual_minutes(remote)
            existing.settings = {**(existing.settings or {}), **metadata}
            existing.save(update_fields=["status", "actual_minutes", "settings", "updated_at"])
            job = existing
            updated += 1
        else:
            job = PrintJob.objects.create(
                owner=printer.owner,
                printer=printer,
                status=_simplyprint_job_status(remote.get("status")),
                actual_minutes=_simplyprint_actual_minutes(remote),
                settings=metadata,
                notes="Imported from SimplyPrint print history.",
            )
            created += 1

        used_g = _as_decimal(remote.get("filUsageGram"), 2)
        if used_g is not None and used_g >= 0:
            usage = job.material_usages.filter(
                source_metadata__external_provider="simplyprint",
                source_metadata__external_job_id=external_id,
            ).first()
            if usage:
                usage.used_g = used_g
                usage.source_metadata = {
                    **(usage.source_metadata or {}),
                    "external_provider": "simplyprint",
                    "external_job_id": external_id,
                    "raw_filament": remote.get("filament"),
                }
                usage.save(update_fields=["used_g", "source_metadata", "updated_at"])
            else:
                PrintMaterialUsage.objects.create(
                    print_job=job,
                    used_g=used_g,
                    source_metadata={
                        "external_provider": "simplyprint",
                        "external_job_id": external_id,
                        "raw_filament": remote.get("filament"),
                    },
                    notes="SimplyPrint reported aggregate filament usage; no MakerVault spool was inferred.",
                )
    return created, updated


def sync_simplyprint(setting: PrintingIntegrationSetting) -> dict:
    if setting.sync_direction != "import":
        raise PrintingSyncError("SimplyPrint v0.6.2 integration is read-only; use External → MakerVault.")

    now = timezone.now()
    remote_printers = _simplyprint_printers(setting)
    filament_inventory = _simplyprint_filaments(setting)
    remote_jobs = _simplyprint_jobs(setting)

    printer_links = {}
    printers_created = 0
    printers_linked_existing = 0
    slots_loaded = 0
    exact_spool_links = 0

    for row in remote_printers:
        printer, created, linked_existing = _simplyprint_link_printer(row, now, setting.owner)
        if not printer:
            continue
        external_id = str(row.get("id") or "").strip()
        printer_links[external_id] = printer
        printers_created += int(created)
        printers_linked_existing += int(linked_existing)
        slot_result = _sync_simplyprint_slots(printer, row, filament_inventory, now)
        slots_loaded += slot_result["loaded_slots"]
        exact_spool_links += slot_result["exact_spool_links"]

    jobs_created, jobs_updated = _sync_simplyprint_jobs(remote_jobs, printer_links)

    config = dict(setting.config or {})
    config["last_remote_summary"] = {
        "printers": len(remote_printers),
        "filaments": len(filament_inventory),
        "jobs_read": len(remote_jobs),
        "slots_loaded": slots_loaded,
        "synced_at": now.isoformat(),
    }
    setting.config = config

    return {
        "provider": "simplyprint",
        "authority": "makervault_primary",
        "mode": "read_only_import",
        "remote_printers": len(remote_printers),
        "printers_created": printers_created,
        "printers_linked_existing": printers_linked_existing,
        "remote_filaments": len(filament_inventory),
        "loaded_slots": slots_loaded,
        "exact_spool_links": exact_spool_links,
        "jobs_read": len(remote_jobs),
        "jobs_created": jobs_created,
        "jobs_updated": jobs_updated,
    }

def _normalise_printer_host(raw: str) -> str:
    value = str(raw or "").strip()
    if not value:
        raise PrintingSyncError("Printer host/IP is missing.")
    if "://" in value:
        parsed = urlparse(value)
    else:
        parsed = urlparse("//" + value)
    host = parsed.hostname
    if not host:
        raise PrintingSyncError("Printer host/IP is invalid.")
    return host


def _find_boxs_info(payload):
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("boxsInfo"), dict):
        return payload["boxsInfo"]
    params = payload.get("params")
    if isinstance(params, dict) and isinstance(params.get("boxsInfo"), dict):
        return params["boxsInfo"]
    return None


async def _fetch_cfs_boxs_info(host: str) -> dict:
    uri = f"ws://{_normalise_printer_host(host)}:9999"
    try:
        async with websockets.connect(
            uri,
            ping_interval=None,
            subprotocols=["wsslicer"],
            open_timeout=5,
            close_timeout=1,
            proxy=None,
        ) as ws:
            await ws.send(json.dumps({"method": "get", "params": {"boxsInfo": 1}}, separators=(",", ":")))
            deadline = asyncio.get_running_loop().time() + 9
            while asyncio.get_running_loop().time() < deadline:
                timeout = max(0.1, deadline - asyncio.get_running_loop().time())
                raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode("utf-8", "ignore")
                if raw == "ok":
                    continue
                try:
                    payload = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                if isinstance(payload, dict) and payload.get("ModeCode") == "heart_beat":
                    await ws.send("ok")
                    continue
                boxs_info = _find_boxs_info(payload)
                if boxs_info is not None:
                    return boxs_info
    except (OSError, asyncio.TimeoutError, WebSocketException) as exc:
        raise PrintingSyncConnectionError(
            f"Could not read CFS data from {_normalise_printer_host(host)}:9999."
        ) from exc
    raise PrintingSyncError("The printer connected but did not return CFS box information.")


def _cfs_material_fingerprint(material: dict) -> str:
    """Stable fingerprint for the loaded filament variant, not the physical reel."""
    return "|".join([
        str(material.get("rfid") or "").strip().casefold(),
        _normalise_hex(material.get("color")).casefold(),
        str(material.get("vendor") or "").strip().casefold(),
        str(material.get("type") or "").strip().casefold(),
        str(material.get("name") or "").strip().casefold(),
    ])


def _cfs_slot_spool_compatible(existing_slot, material: dict) -> bool:
    """Reject a physical-spool association when live material facts conflict."""
    if not existing_slot or not existing_slot.spool_id:
        return False

    spool = existing_slot.spool
    filament = spool.filament
    maker = filament.filament_manufacturer or filament.manufacturer

    remote_color = _normalise_hex(material.get("color"))
    local_color = _normalise_hex(filament.color_hex)
    if remote_color and local_color and remote_color != local_color:
        return False

    remote_material = _normalise_match_text(material.get("type"))
    local_material = _normalise_match_text(filament.material)
    if remote_material and local_material and remote_material != local_material:
        return False

    remote_vendor = _normalise_match_text(material.get("vendor"))
    local_vendor = _normalise_match_text(maker.name if maker else "")
    if remote_vendor and local_vendor and remote_vendor != local_vendor:
        return False

    return True


def _confirmed_cfs_spool(existing_slot, material: dict, fingerprint: str):
    """Preserve explicit links, plus compatible pre-v0.6.0.1 legacy user links."""
    if not _cfs_slot_spool_compatible(existing_slot, material):
        return None, ""

    metadata = existing_slot.metadata or {}
    source = metadata.get("link_source") or ""
    explicit_sources = {
        "inventory_created_from_slot",
        "user_linked_existing",
        "legacy_compatible_link",
    }

    if source in explicit_sources:
        if metadata.get("material_fingerprint") and metadata.get("material_fingerprint") != fingerprint:
            return None, ""
        return existing_slot.spool, source

    # Older MakerVault builds did not record how the slot/spool link was created.
    # Keep only links whose live vendor/material/colour remain compatible and mark
    # them so future syncs no longer need this inference.
    return existing_slot.spool, "legacy_compatible_link"


def _sync_cfs_printer(printer: Printer, boxs_info: dict) -> dict:
    material_boxes = boxs_info.get("materialBoxs") or []
    if not isinstance(material_boxes, list):
        raise PrintingSyncError(f"{printer.name} returned malformed CFS material data.")

    seen = set()
    loaded = 0
    matched = 0
    updated_weights = 0
    now = timezone.now()

    for box in material_boxes:
        if not isinstance(box, dict) or int(box.get("type") or 0) != 0:
            continue
        try:
            box_id = int(box.get("id"))
        except (TypeError, ValueError):
            continue
        materials = box.get("materials") or []
        if not isinstance(materials, list):
            continue

        for raw in materials:
            if not isinstance(raw, dict):
                continue
            try:
                slot_index = int(raw.get("id"))
            except (TypeError, ValueError):
                continue
            try:
                state = int(raw.get("state") or 0)
            except (TypeError, ValueError):
                state = 0
            if state <= 0:
                continue

            unit_index = max(box_id - 1, 0)
            seen.add((unit_index, slot_index))
            fingerprint = _cfs_material_fingerprint(raw)
            existing_slot = PrinterFilamentSlot.objects.select_related(
                "spool__filament",
            ).filter(
                printer=printer,
                system="creality_cfs",
                unit_index=unit_index,
                slot_index=slot_index,
            ).first()
            local_spool, confirmed_source = _confirmed_cfs_spool(
                existing_slot, raw, fingerprint
            )

            percent = _as_decimal(raw.get("percent"))
            remaining_weight = None
            if local_spool and state == 2 and percent is not None:
                basis = local_spool.initial_weight_g or local_spool.filament.nominal_weight_g
                if basis is not None:
                    remaining_weight = (basis * percent / Decimal("100")).quantize(Decimal("0.01"))
                    if local_spool.remaining_weight_g != remaining_weight:
                        local_spool.remaining_weight_g = remaining_weight
                        local_spool.save(update_fields=["remaining_weight_g", "updated_at"])
                        updated_weights += 1

            previous_metadata = (existing_slot.metadata or {}) if existing_slot else {}
            link_source = confirmed_source if local_spool else ""
            metadata = {
                "vendor": raw.get("vendor") or "",
                "product_name": raw.get("name") or "",
                "material_code": str(raw.get("rfid") or ""),
                "rfid_detected": state == 2,
                "physical_tag_uid_available": False,
                "remaining_percent": float(percent) if state == 2 and percent is not None else None,
                "selected": bool(raw.get("selected")),
                "min_temp_c": raw.get("minTemp"),
                "max_temp_c": raw.get("maxTemp"),
                "box_id": box_id,
                "box_temperature_c": box.get("temp"),
                "box_humidity_percent": box.get("humidity"),
                "material_fingerprint": fingerprint,
            }
            if link_source:
                metadata["link_source"] = link_source
                metadata["link_confirmed_at"] = previous_metadata.get("link_confirmed_at")

            slot, _ = PrinterFilamentSlot.objects.update_or_create(
                printer=printer,
                system="creality_cfs",
                unit_index=unit_index,
                slot_index=slot_index,
                defaults={
                    "spool": local_spool,
                    "external_ref": f"cfs:{box_id}:{slot_index}",
                    "rfid_uid": "",
                    "material": str(raw.get("type") or "").strip()[:80],
                    "color_name": str(raw.get("name") or "").strip()[:120],
                    "color_hex": _normalise_hex(raw.get("color")),
                    "remaining_weight_g": remaining_weight,
                    "is_loaded": True,
                    "last_seen_at": now,
                    "metadata": metadata,
                },
            )
            loaded += 1
            if local_spool:
                matched += 1

    stale = PrinterFilamentSlot.objects.filter(
        printer=printer,
        system="creality_cfs",
        is_loaded=True,
    )
    for slot in stale:
        if (slot.unit_index, slot.slot_index) not in seen:
            slot.is_loaded = False
            slot.spool = None
            slot.last_seen_at = now
            metadata = dict(slot.metadata or {})
            metadata.pop("link_source", None)
            metadata.pop("link_confirmed_at", None)
            metadata.pop("material_fingerprint", None)
            slot.metadata = metadata
            slot.save(update_fields=["is_loaded", "spool", "last_seen_at", "metadata", "updated_at"])

    return {
        "printer_id": str(printer.id),
        "printer": printer.name,
        "loaded_slots": loaded,
        "matched_spools": matched,
        "updated_spool_weights": updated_weights,
    }


def sync_creality_cfs(setting: PrintingIntegrationSetting) -> dict:
    printers = list(
        Printer.objects.filter(
            owner=setting.owner,
            is_active=True,
            multi_material_installed=True,
            catalog_model__multi_material_system="creality_cfs",
        ).exclude(connection_host="")
    )
    if not printers:
        raise PrintingSyncError("No active printer with CFS installed and a local host/IP is configured.")

    results = []
    failures = []
    for printer in printers:
        try:
            boxs_info = asyncio.run(_fetch_cfs_boxs_info(printer.connection_host))
            results.append(_sync_cfs_printer(printer, boxs_info))
        except PrintingSyncError as exc:
            failures.append({"printer": printer.name, "error": str(exc)})

    if not results:
        message = failures[0]["error"] if failures else "No CFS printers could be synchronised."
        raise PrintingSyncConnectionError(message)

    return {
        "provider": "creality_cfs",
        "printers_synced": len(results),
        "printers_failed": len(failures),
        "printers": results,
        "failures": failures,
        "loaded_slots": sum(item["loaded_slots"] for item in results),
        "matched_spools": sum(item["matched_spools"] for item in results),
    }


def sync_printing_integration(provider: str, triggered_by: str = "manual", *, owner=None, setting_id=None) -> tuple[PrintingIntegrationSetting, dict]:
    if setting_id is None and owner is None:
        raise PrintingSyncError("An integration owner is required.")
    settings_qs = PrintingIntegrationSetting.objects.all()
    if setting_id is not None:
        settings_qs = settings_qs.filter(pk=setting_id)
    else:
        settings_qs = settings_qs.filter(provider=provider)
        if owner is not None:
            settings_qs = settings_qs.filter(owner=owner)
    setting = settings_qs.first()
    if not setting:
        raise PrintingSyncError("Integration is not configured.")
    if not setting.enabled:
        raise PrintingSyncError("Integration is disabled.")

    now = timezone.now()
    try:
        if provider == "spoolman":
            result = sync_spoolman(setting)
        elif provider == "simplyprint":
            result = sync_simplyprint(setting)
        elif provider == "creality_cfs":
            result = sync_creality_cfs(setting)
        else:
            raise PrintingSyncError("This integration does not have a sync adapter yet.")

        setting.status = "connected"
        setting.last_error = ""
        setting.last_checked_at = now
        setting.last_sync_at = now
        setting.last_sync_triggered_by = str(triggered_by or "manual")[:120]
        setting.last_sync_result = result
        if setting.auto_sync:
            setting.next_sync_at = now + timedelta(minutes=setting.sync_interval_minutes)
        else:
            setting.next_sync_at = None
        setting.save()
        return setting, result
    except PrintingSyncConnectionError as exc:
        setting.status = "disconnected"
        setting.last_error = str(exc)
        setting.last_checked_at = now
        setting.last_sync_at = now
        setting.last_sync_triggered_by = str(triggered_by or "manual")[:120]
        setting.last_sync_result = {"provider": provider, "error": str(exc)}
        if setting.auto_sync:
            setting.next_sync_at = now + timedelta(minutes=setting.sync_interval_minutes)
        setting.save()
        raise
    except PrintingSyncError as exc:
        setting.status = "error"
        setting.last_error = str(exc)
        setting.last_checked_at = now
        setting.last_sync_at = now
        setting.last_sync_triggered_by = str(triggered_by or "manual")[:120]
        setting.last_sync_result = {"provider": provider, "error": str(exc)}
        if setting.auto_sync:
            setting.next_sync_at = now + timedelta(minutes=setting.sync_interval_minutes)
        setting.save()
        raise
    except Exception as exc:
        logger.exception("Unexpected %s integration sync failure", provider)
        message = f"{provider.replace('_', ' ').title()} sync failed: {exc}"
        setting.status = "error"
        setting.last_error = message
        setting.last_checked_at = now
        setting.last_sync_at = now
        setting.last_sync_triggered_by = str(triggered_by or "manual")[:120]
        setting.last_sync_result = {
            "provider": provider,
            "error": message,
            "exception_type": type(exc).__name__,
        }
        if setting.auto_sync:
            setting.next_sync_at = now + timedelta(minutes=setting.sync_interval_minutes)
        setting.save()
        raise PrintingSyncError(message) from exc
