from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

import requests
from django.utils import timezone

from .live_print_jobs import sync_print_job_from_snapshot


class PrinterConnectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdapterDefinition:
    key: str
    label: str
    supported: bool
    experimental: bool
    local_first: bool
    capabilities: dict


COMMON_MONITORING = {
    "online": True,
    "printer_state": True,
    "job": True,
    "progress": True,
    "elapsed_time": True,
    "remaining_time": True,
    "temperatures": True,
    "filename": True,
    "thumbnail": False,
    "camera": False,
    "warnings": True,
    "materials": False,
    "pause": False,
    "resume": False,
    "cancel": False,
    "start_print": False,
}


ADAPTERS = {
    "moonraker": AdapterDefinition(
        key="moonraker",
        label="Moonraker / Klipper",
        supported=True,
        experimental=False,
        local_first=True,
        capabilities={
            **COMMON_MONITORING,
            "pause": True,
            "resume": True,
            "cancel": True,
            "macros": True,
        },
    ),
    "octoprint": AdapterDefinition(
        key="octoprint",
        label="OctoPrint",
        supported=True,
        experimental=False,
        local_first=True,
        capabilities={
            **COMMON_MONITORING,
            "pause": True,
            "resume": True,
            "cancel": True,
        },
    ),
    "creality_local": AdapterDefinition(
        key="creality_local",
        label="Creality local",
        supported=False,
        experimental=True,
        local_first=True,
        capabilities={**COMMON_MONITORING, "materials": True},
    ),
    "simplyprint": AdapterDefinition(
        key="simplyprint",
        label="SimplyPrint",
        supported=False,
        experimental=False,
        local_first=False,
        capabilities={**COMMON_MONITORING, "materials": True},
    ),
    "bambu_local": AdapterDefinition(
        key="bambu_local",
        label="Bambu Lab local",
        supported=False,
        experimental=True,
        local_first=True,
        capabilities={**COMMON_MONITORING, "camera": True, "materials": True},
    ),
    "anycubic": AdapterDefinition("anycubic", "Anycubic", False, True, True, dict(COMMON_MONITORING)),
    "flashforge": AdapterDefinition("flashforge", "FlashForge", False, True, True, dict(COMMON_MONITORING)),
    "prusa": AdapterDefinition("prusa", "Prusa", False, True, True, dict(COMMON_MONITORING)),
    "elegoo": AdapterDefinition("elegoo", "Elegoo", False, True, True, dict(COMMON_MONITORING)),
    "qidi": AdapterDefinition("qidi", "QIDI", False, True, True, dict(COMMON_MONITORING)),
    "sovol": AdapterDefinition("sovol", "Sovol", False, True, True, dict(COMMON_MONITORING)),
    "snapmaker": AdapterDefinition("snapmaker", "Snapmaker", False, True, True, dict(COMMON_MONITORING)),
    "voron": AdapterDefinition(
        "voron",
        "Voron metadata / community layer",
        False,
        True,
        True,
        {**COMMON_MONITORING, "printer_state": False, "job": False, "temperatures": False},
    ),
    "other": AdapterDefinition("other", "Other / custom", False, True, True, dict(COMMON_MONITORING)),
}


def adapter_catalogue() -> list[dict]:
    return [
        {
            "key": item.key,
            "label": item.label,
            "supported": item.supported,
            "experimental": item.experimental,
            "local_first": item.local_first,
            "capabilities": item.capabilities,
        }
        for item in ADAPTERS.values()
    ]


def normalise_printer_endpoint(raw_url: str) -> str:
    value = str(raw_url or "").strip().rstrip("/")
    if not value:
        raise PrinterConnectionError("Enter the printer service URL.")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise PrinterConnectionError("Printer service URLs must use HTTP or HTTPS.")
    if not parsed.hostname:
        raise PrinterConnectionError("Printer service URL must include a host.")
    if parsed.username or parsed.password:
        raise PrinterConnectionError("Do not embed credentials in the printer service URL.")
    return value


def _json(response, context: str) -> dict:
    if response.status_code >= 400:
        raise PrinterConnectionError(f"{context} returned HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise PrinterConnectionError(f"{context} returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise PrinterConnectionError(f"{context} returned an unexpected response.")
    return payload


def _get(url: str, *, headers=None, timeout=(3, 8)) -> dict:
    try:
        response = requests.get(
            url,
            headers=headers or {},
            timeout=timeout,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise PrinterConnectionError("MakerVault could not reach the printer service.") from exc
    return _json(response, "Printer service")


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _seconds(value):
    number = _number(value)
    if number is None or number < 0:
        return None
    return int(round(number))


def _temperature(actual=None, target=None):
    return {
        "actual_c": _number(actual),
        "target_c": _number(target),
    }


def _blank_snapshot(adapter: str) -> dict:
    return {
        "adapter": adapter,
        "online": False,
        "state": "unknown",
        "state_label": "Unknown",
        "job": {
            "file_name": "",
            "progress": None,
            "elapsed_seconds": None,
            "remaining_seconds": None,
            "current_layer": None,
            "total_layers": None,
        },
        "temperatures": {},
        "thumbnail_url": "",
        "camera_url": "",
        "warnings": [],
        "materials": [],
        "source_metadata": {},
        "captured_at": timezone.now().isoformat(),
    }


def poll_moonraker(endpoint_url: str, config: dict | None = None) -> dict:
    base = normalise_printer_endpoint(endpoint_url)
    headers = {
        "Accept": "application/json",
        "User-Agent": "MakerVault/0.7.3 (+Moonraker live printer adapter)",
    }
    api_key = str((config or {}).get("api_key") or "").strip()
    if api_key:
        headers["X-Api-Key"] = api_key

    server = _get(base + "/server/info", headers=headers)
    objects = _get(
        base + "/printer/objects/query?print_stats&display_status&virtual_sdcard&extruder&heater_bed",
        headers=headers,
    )
    result = objects.get("result") or {}
    status = result.get("status") or {}
    print_stats = status.get("print_stats") or {}
    display = status.get("display_status") or {}
    virtual_sd = status.get("virtual_sdcard") or {}
    extruder = status.get("extruder") or {}
    bed = status.get("heater_bed") or {}

    state = str(print_stats.get("state") or "").strip().lower() or "unknown"
    state_map = {
        "standby": "idle",
        "printing": "printing",
        "paused": "paused",
        "complete": "complete",
        "cancelled": "cancelled",
        "error": "error",
    }
    normalised_state = state_map.get(state, state)
    progress = _number(virtual_sd.get("progress"))
    if progress is None:
        progress = _number(display.get("progress"))
    if progress is not None:
        progress = max(0.0, min(100.0, progress * 100 if progress <= 1 else progress))

    elapsed = _seconds(print_stats.get("print_duration"))
    remaining = None
    if progress and elapsed is not None and progress > 0:
        remaining = max(0, int(round((elapsed / (progress / 100.0)) - elapsed)))

    snapshot = _blank_snapshot("moonraker")
    snapshot.update({
        "online": True,
        "state": normalised_state,
        "state_label": normalised_state.replace("_", " ").title(),
        "job": {
            "file_name": str(print_stats.get("filename") or ""),
            "progress": round(progress, 2) if progress is not None else None,
            "elapsed_seconds": elapsed,
            "remaining_seconds": remaining,
            "current_layer": None,
            "total_layers": None,
        },
        "temperatures": {
            "tool0": _temperature(extruder.get("temperature"), extruder.get("target")),
            "bed": _temperature(bed.get("temperature"), bed.get("target")),
        },
        "source_metadata": {
            "klippy_state": str((server.get("result") or {}).get("klippy_state") or ""),
            "moonraker_version": str((server.get("result") or {}).get("moonraker_version") or ""),
        },
        "captured_at": timezone.now().isoformat(),
    })
    return snapshot


def poll_octoprint(endpoint_url: str, config: dict | None = None) -> dict:
    base = normalise_printer_endpoint(endpoint_url)
    api_key = str((config or {}).get("api_key") or "").strip()
    headers = {
        "Accept": "application/json",
        "User-Agent": "MakerVault/0.7.3 (+OctoPrint live printer adapter)",
    }
    if api_key:
        headers["X-Api-Key"] = api_key

    version = _get(base + "/api/version", headers=headers)
    job_payload = _get(base + "/api/job", headers=headers)
    printer_payload = _get(base + "/api/printer", headers=headers)

    state_text = str((job_payload.get("state") or printer_payload.get("state", {}).get("text") or "Unknown")).strip()
    lower = state_text.casefold()
    if "print" in lower:
        state = "printing"
    elif "pause" in lower:
        state = "paused"
    elif "error" in lower or "offline" in lower:
        state = "error"
    elif "cancel" in lower:
        state = "cancelled"
    elif "complete" in lower or "finish" in lower:
        state = "complete"
    else:
        state = "idle"

    progress_data = job_payload.get("progress") or {}
    completion = _number(progress_data.get("completion"))
    job = job_payload.get("job") or {}
    file_data = job.get("file") or {}
    temps = printer_payload.get("temperature") or {}
    tool0 = temps.get("tool0") or {}
    bed = temps.get("bed") or {}

    snapshot = _blank_snapshot("octoprint")
    snapshot.update({
        "online": True,
        "state": state,
        "state_label": state_text or state.title(),
        "job": {
            "file_name": str(file_data.get("display") or file_data.get("name") or file_data.get("path") or ""),
            "progress": round(max(0.0, min(100.0, completion)), 2) if completion is not None else None,
            "elapsed_seconds": _seconds(progress_data.get("printTime")),
            "remaining_seconds": _seconds(progress_data.get("printTimeLeft")),
            "current_layer": None,
            "total_layers": None,
        },
        "temperatures": {
            "tool0": _temperature(tool0.get("actual"), tool0.get("target")),
            "bed": _temperature(bed.get("actual"), bed.get("target")),
        },
        "source_metadata": {
            "api": str(version.get("api") or ""),
            "server": str(version.get("server") or ""),
            "text": str(version.get("text") or ""),
        },
        "captured_at": timezone.now().isoformat(),
    })
    return snapshot


POLLERS: dict[str, Callable[[str, dict | None], dict]] = {
    "moonraker": poll_moonraker,
    "octoprint": poll_octoprint,
}


def poll_connection(connection) -> dict:
    definition = ADAPTERS.get(connection.adapter)
    if not definition:
        raise PrinterConnectionError("Unknown printer adapter.")
    if not definition.supported or connection.adapter not in POLLERS:
        suffix = " This adapter is awaiting community hardware validation." if definition.experimental else ""
        raise PrinterConnectionError(f"{definition.label} live polling is not implemented yet.{suffix}")
    if not connection.enabled:
        raise PrinterConnectionError("This printer connection is disabled.")

    try:
        snapshot = POLLERS[connection.adapter](connection.endpoint_url, connection.config or {})
    except PrinterConnectionError as exc:
        connection.status = "disconnected"
        connection.last_error = str(exc)
        connection.last_checked_at = timezone.now()
        connection.save(update_fields=["status", "last_error", "last_checked_at", "updated_at"])
        raise

    job_result = sync_print_job_from_snapshot(connection, snapshot)
    snapshot = {
        **snapshot,
        "maker_vault_job": job_result,
    }

    now = timezone.now()
    connection.status = "connected"
    connection.last_error = ""
    connection.last_checked_at = now
    connection.last_seen_at = now
    connection.capabilities = dict(definition.capabilities)
    connection.last_snapshot = snapshot
    connection.save(update_fields=[
        "status", "last_error", "last_checked_at", "last_seen_at",
        "capabilities", "last_snapshot", "updated_at",
    ])
    return snapshot
