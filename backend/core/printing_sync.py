from __future__ import annotations

import asyncio
import json
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import requests
import websockets
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import (
    ExternalSpoolLink,
    FilamentManufacturer,
    FilamentProduct,
    Printer,
    PrinterFilamentSlot,
    PrintingIntegrationSetting,
    PrintingLocation,
    Spool,
)
from .printing_integrations import normalise_service_url


class PrintingSyncError(RuntimeError):
    pass


class PrintingSyncConnectionError(PrintingSyncError):
    pass


def next_spool_id() -> str:
    highest = 0
    for value in Spool.objects.filter(spool_id__startswith="SPL-").values_list("spool_id", flat=True):
        match = re.fullmatch(r"SPL-(\d+)", value or "")
        if match:
            highest = max(highest, int(match.group(1)))
    candidate = highest + 1
    while Spool.objects.filter(spool_id=f"SPL-{candidate:04d}").exists():
        candidate += 1
    return f"SPL-{candidate:04d}"


def _as_decimal(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
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


def _spoolman_get_spools(endpoint_url: str) -> tuple[str, list[dict]]:
    root = _spoolman_api_root(endpoint_url)
    try:
        response = requests.get(
            root + "/spool",
            headers={"User-Agent": "MakerVault/0.6 (Spoolman sync)"},
            timeout=(4, 20),
        )
    except requests.RequestException as exc:
        raise PrintingSyncConnectionError("MakerVault could not reach the Spoolman server.") from exc
    if response.status_code != 200:
        raise PrintingSyncError(f"Spoolman returned HTTP {response.status_code} while reading spools.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise PrintingSyncError("Spoolman returned invalid JSON while reading spools.") from exc
    if not isinstance(payload, list):
        raise PrintingSyncError("Spoolman returned an unexpected spool list.")
    return root, payload


def _spoolman_filament(remote: dict) -> FilamentProduct:
    filament_data = remote.get("filament") or {}
    if not isinstance(filament_data, dict):
        filament_data = {}
    vendor_data = filament_data.get("vendor") or {}
    if not isinstance(vendor_data, dict):
        vendor_data = {}

    remote_filament_id = str(filament_data.get("id") or "")
    maker_name = str(vendor_data.get("name") or "Generic").strip()[:200] or "Generic"
    maker, _ = FilamentManufacturer.objects.get_or_create(name=maker_name)

    existing = None
    if remote_filament_id:
        existing = FilamentProduct.objects.filter(
            profile_data__spoolman__filament_id=remote_filament_id
        ).first()

    name = str(filament_data.get("name") or filament_data.get("material") or "Spoolman filament").strip()[:255]
    material = str(filament_data.get("material") or "Unknown").strip()[:80]
    color_hex = _normalise_hex(filament_data.get("color_hex"))

    if existing is None:
        existing = FilamentProduct.objects.filter(
            filament_manufacturer=maker,
            name=name,
            material=material,
            color_hex=color_hex,
        ).first()

    profile = {
        "spoolman": {
            "filament_id": remote_filament_id,
            "vendor_id": str(vendor_data.get("id") or ""),
        }
    }

    if existing is None:
        existing = FilamentProduct(
            filament_manufacturer=maker,
            name=name,
            material=material,
            color_name=str(filament_data.get("name") or "").strip()[:120],
            color_hex=color_hex,
            diameter_mm=_as_decimal(filament_data.get("diameter")) or Decimal("1.75"),
            density_g_cm3=_as_decimal(filament_data.get("density")),
            nominal_weight_g=_as_decimal(filament_data.get("weight")),
            empty_spool_weight_g=_as_decimal(filament_data.get("spool_weight")),
            nozzle_temp_min_c=filament_data.get("settings_extruder_temp") or None,
            bed_temp_min_c=filament_data.get("settings_bed_temp") or None,
            profile_data=profile,
        )
        existing.full_clean()
        existing.save()
        return existing

    changed = False
    if not existing.filament_manufacturer_id:
        existing.filament_manufacturer = maker
        changed = True
    merged_profile = {**(existing.profile_data or {}), **profile}
    if merged_profile != existing.profile_data:
        existing.profile_data = merged_profile
        changed = True
    for field, value in {
        "density_g_cm3": _as_decimal(filament_data.get("density")),
        "nominal_weight_g": _as_decimal(filament_data.get("weight")),
        "empty_spool_weight_g": _as_decimal(filament_data.get("spool_weight")),
    }.items():
        if getattr(existing, field) is None and value is not None:
            setattr(existing, field, value)
            changed = True
    if changed:
        existing.save()
    return existing


def _spoolman_location(name: str):
    value = str(name or "").strip()[:200]
    if not value:
        return None
    location, _ = PrintingLocation.objects.get_or_create(
        name=value,
        defaults={"kind": "storage"},
    )
    return location


def _create_spool_with_generated_id(**kwargs) -> Spool:
    for _ in range(5):
        try:
            with transaction.atomic():
                item = Spool(spool_id=next_spool_id(), **kwargs)
                item.full_clean()
                item.save()
                return item
        except IntegrityError:
            continue
    raise PrintingSyncError("MakerVault could not allocate a unique spool ID.")


def sync_spoolman(setting: PrintingIntegrationSetting) -> dict:
    root, remote_spools = _spoolman_get_spools(setting.endpoint_url)
    direction = setting.sync_direction
    do_import = direction in {"import", "bidirectional"}
    do_export = direction in {"export", "bidirectional"}

    created = 0
    updated = 0
    exported = 0
    skipped_unlinked = 0
    now = timezone.now()

    if do_import:
        for remote in remote_spools:
            external_id = str(remote.get("id") or "").strip()
            if not external_id:
                continue
            filament = _spoolman_filament(remote)
            link = ExternalSpoolLink.objects.select_related("spool").filter(
                provider="spoolman",
                external_id=external_id,
            ).first()

            remaining = _as_decimal(remote.get("remaining_weight"))
            initial = _as_decimal((remote.get("filament") or {}).get("weight"))
            archived = bool(remote.get("archived"))
            status = "retired" if archived else ("empty" if remaining is not None and remaining <= 0 else "open")
            location = _spoolman_location(remote.get("location"))

            if link:
                spool = link.spool
                spool.filament = filament
                if remaining is not None:
                    spool.remaining_weight_g = remaining
                if spool.initial_weight_g is None and initial is not None:
                    spool.initial_weight_g = initial
                spool.status = status
                if location and not spool.assigned_printer_id:
                    spool.storage_location = location
                    spool.location = ""
                spool.full_clean()
                spool.save()
                updated += 1
            else:
                spool = _create_spool_with_generated_id(
                    filament=filament,
                    initial_weight_g=initial,
                    remaining_weight_g=remaining,
                    storage_location=location,
                    status=status,
                    notes=str(remote.get("comment") or "").strip(),
                )
                link = ExternalSpoolLink.objects.create(
                    spool=spool,
                    provider="spoolman",
                    external_id=external_id,
                    external_url=f"{root.rsplit('/api/v1', 1)[0]}/spool/show/{external_id}",
                    sync_direction=direction,
                    last_synced_at=now,
                    sync_metadata={"remote": remote},
                )
                created += 1

            link.sync_direction = direction
            link.last_synced_at = now
            link.sync_metadata = {"remote": remote}
            link.save(update_fields=["sync_direction", "last_synced_at", "sync_metadata", "updated_at"])

    if do_export:
        links = list(
            ExternalSpoolLink.objects.select_related(
                "spool__storage_location",
                "spool__assigned_printer",
            ).filter(provider="spoolman")
        )
        linked_ids = {link.spool_id for link in links}
        skipped_unlinked = Spool.objects.exclude(pk__in=linked_ids).count()
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
                    f"Spoolman returned HTTP {response.status_code} while updating spool {link.external_id}."
                )
            link.last_synced_at = now
            link.save(update_fields=["last_synced_at", "updated_at"])
            exported += 1

    return {
        "provider": "spoolman",
        "remote_spools": len(remote_spools),
        "created": created,
        "updated": updated,
        "exported": exported,
        "unlinked_local_spools_skipped": skipped_unlinked,
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
    except (OSError, asyncio.TimeoutError, websockets.WebSocketException) as exc:
        raise PrintingSyncConnectionError(
            f"Could not read CFS data from {_normalise_printer_host(host)}:9999."
        ) from exc
    raise PrintingSyncError("The printer connected but did not return CFS box information.")


def _match_cfs_spool(printer: Printer, material: dict):
    remote_material = str(material.get("type") or "").strip().casefold()
    remote_vendor = str(material.get("vendor") or "").strip().casefold()
    remote_name = str(material.get("name") or "").strip().casefold()
    remote_color = _normalise_hex(material.get("color")).casefold()

    best = []
    best_score = 0
    candidates = printer.assigned_spools.select_related(
        "filament__filament_manufacturer",
        "filament__manufacturer",
    ).exclude(status__in=["empty", "retired"])

    for spool in candidates:
        filament = spool.filament
        maker = filament.filament_manufacturer or filament.manufacturer
        score = 0
        if remote_material and filament.material.casefold() == remote_material:
            score += 4
        else:
            continue
        if remote_vendor and maker and maker.name.casefold() == remote_vendor:
            score += 3
        if remote_name and (
            remote_name in filament.name.casefold()
            or filament.name.casefold() in remote_name
        ):
            score += 2
        if remote_color and filament.color_hex and filament.color_hex.casefold() == remote_color:
            score += 2
        if score > best_score:
            best_score = score
            best = [spool]
        elif score == best_score:
            best.append(spool)

    if best_score >= 7 and len(best) == 1:
        return best[0]
    return None


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
            state = int(raw.get("state") or 0)
            is_loaded = state > 0
            if not is_loaded:
                continue

            unit_index = max(box_id - 1, 0)
            seen.add((unit_index, slot_index))
            local_spool = _match_cfs_spool(printer, raw)
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
                    "metadata": {
                        "vendor": raw.get("vendor") or "",
                        "product_name": raw.get("name") or "",
                        "material_code": str(raw.get("rfid") or ""),
                        "rfid_detected": state == 2,
                        "remaining_percent": float(percent) if percent is not None else None,
                        "selected": bool(raw.get("selected")),
                        "min_temp_c": raw.get("minTemp"),
                        "max_temp_c": raw.get("maxTemp"),
                        "box_id": box_id,
                        "box_temperature_c": box.get("temp"),
                        "box_humidity_percent": box.get("humidity"),
                    },
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
            slot.save(update_fields=["is_loaded", "spool", "last_seen_at", "updated_at"])

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
            is_active=True,
            catalog_model__multi_material_system="creality_cfs",
        ).exclude(connection_host="")
    )
    if not printers:
        raise PrintingSyncError("No active CFS-capable printer with a local host/IP is configured.")

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


def sync_printing_integration(provider: str, triggered_by: str = "manual") -> tuple[PrintingIntegrationSetting, dict]:
    setting = PrintingIntegrationSetting.objects.filter(provider=provider).first()
    if not setting:
        raise PrintingSyncError("Integration is not configured.")
    if not setting.enabled:
        raise PrintingSyncError("Integration is disabled.")

    now = timezone.now()
    try:
        if provider == "spoolman":
            result = sync_spoolman(setting)
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
            setting.next_sync_at = now + timezone.timedelta(minutes=setting.sync_interval_minutes)
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
            setting.next_sync_at = now + timezone.timedelta(minutes=setting.sync_interval_minutes)
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
            setting.next_sync_at = now + timezone.timedelta(minutes=setting.sync_interval_minutes)
        setting.save()
        raise
