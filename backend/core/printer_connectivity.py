from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

import requests
import websockets
from websockets.exceptions import WebSocketException
from django.utils import timezone

from .live_print_jobs import sync_print_job_from_snapshot
from .live_material_slots import sync_live_material_slots
from .manufacturer_printer_adapters import (
    ManufacturerAdapterError,
    normalise_anycubic_endpoint,
    normalise_bambu_endpoint,
    normalise_flashforge_endpoint,
    normalise_prusalink_endpoint,
    poll_anycubic_local,
    poll_bambu_local,
    poll_flashforge,
    poll_prusalink,
)


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
        supported=True,
        experimental=True,
        local_first=True,
        capabilities={
            **COMMON_MONITORING,
            "materials": True,
            "camera": True,
            "pause": True,
            "resume": True,
            "cancel": True,
        },
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
        supported=True,
        experimental=True,
        local_first=True,
        capabilities={
            **COMMON_MONITORING,
            "camera": True,
            "materials": True,
            "pause": True,
            "resume": True,
            "cancel": True,
        },
    ),
    "anycubic": AdapterDefinition(
        "anycubic",
        "Anycubic LAN",
        True,
        True,
        True,
        {
            **COMMON_MONITORING,
            "camera": True,
            "materials": True,
            "pause": True,
            "resume": True,
            "cancel": True,
        },
    ),
    "flashforge": AdapterDefinition(
        "flashforge",
        "FlashForge local",
        True,
        True,
        True,
        {
            **COMMON_MONITORING,
            "camera": True,
            "materials": True,
            "pause": True,
            "resume": True,
            "cancel": True,
        },
    ),
    "prusa": AdapterDefinition(
        "prusa",
        "PrusaLink",
        True,
        True,
        True,
        {**COMMON_MONITORING, "camera": True, "pause": True, "resume": True, "cancel": True},
    ),
    "elegoo": AdapterDefinition(
        "elegoo",
        "Elegoo · Moonraker",
        True,
        True,
        True,
        {**COMMON_MONITORING, "pause": True, "resume": True, "cancel": True},
    ),
    "qidi": AdapterDefinition(
        "qidi",
        "QIDI · Moonraker",
        True,
        True,
        True,
        {**COMMON_MONITORING, "camera": True, "pause": True, "resume": True, "cancel": True},
    ),
    "sovol": AdapterDefinition(
        "sovol",
        "Sovol · Moonraker",
        True,
        True,
        True,
        {**COMMON_MONITORING, "camera": True, "pause": True, "resume": True, "cancel": True},
    ),
    "snapmaker": AdapterDefinition(
        "snapmaker",
        "Snapmaker U1 · Moonraker",
        True,
        True,
        True,
        {**COMMON_MONITORING, "camera": True, "pause": True, "resume": True, "cancel": True},
    ),
    "voron": AdapterDefinition(
        "voron",
        "Voron · Moonraker",
        True,
        True,
        True,
        {**COMMON_MONITORING, "camera": True, "pause": True, "resume": True, "cancel": True, "macros": True},
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


def normalise_moonraker_endpoint(raw_url: str) -> str:
    """Normalise a Moonraker HTTP endpoint while preserving route prefixes."""
    value = str(raw_url or "").strip().rstrip("/")
    if not value:
        raise PrinterConnectionError("Enter the Moonraker printer host or URL.")
    if "://" not in value:
        parsed = urlparse("//" + value)
        scheme = "http"
    else:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"}:
            raise PrinterConnectionError("Moonraker endpoints must use HTTP or HTTPS.")
        scheme = parsed.scheme
    if not parsed.hostname:
        raise PrinterConnectionError("Moonraker endpoint must include a host.")
    if parsed.username or parsed.password:
        raise PrinterConnectionError("Do not embed credentials in the Moonraker endpoint.")

    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    # Preserve explicit reverse-proxy URLs and route prefixes. Bare hosts use
    # Moonraker's conventional 7125 port.
    explicit_url = "://" in value
    port = parsed.port if parsed.port else (None if explicit_url and parsed.path not in {"", "/"} else 7125)
    suffix = f":{port}" if port else ""
    path = (parsed.path or "").rstrip("/")
    return f"{scheme}://{host}{suffix}{path}"


def normalise_creality_endpoint(raw_url: str) -> str:
    """Return the Creality LAN WebSocket endpoint used by Creality Print.

    Existing MakerVault printers commonly store only a host/IP in
    `connection_host`, so the adapter accepts a bare host as well as HTTP/WS
    URLs and canonicalises them to the local WebSocket service on port 9999.
    """
    value = str(raw_url or "").strip().rstrip("/")
    if not value:
        raise PrinterConnectionError("Enter the Creality printer host or WebSocket URL.")

    if "://" not in value:
        parsed = urlparse("//" + value)
        scheme = "ws"
    else:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https", "ws", "wss"}:
            raise PrinterConnectionError("Creality local endpoints must use a host, HTTP(S), or WS(S) URL.")
        scheme = "wss" if parsed.scheme in {"https", "wss"} else "ws"

    if not parsed.hostname:
        raise PrinterConnectionError("Creality local endpoint must include a host.")
    if parsed.username or parsed.password:
        raise PrinterConnectionError("Do not embed credentials in the Creality printer endpoint.")

    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"

    # Creality Print's local WebSocket protocol is exposed on 9999. Preserve
    # an explicitly supplied WS/WSS port for reverse proxies/test fixtures;
    # ordinary HTTP UI ports are not the telemetry service.
    port = parsed.port if parsed.scheme in {"ws", "wss"} and parsed.port else 9999
    return f"{scheme}://{host}:{port}"


def normalise_connection_endpoint(adapter: str, raw_url: str) -> str:
    if adapter in {"moonraker", "elegoo", "qidi", "sovol", "snapmaker", "voron"}:
        return normalise_moonraker_endpoint(raw_url)
    if adapter == "creality_local":
        return normalise_creality_endpoint(raw_url)
    if adapter == "bambu_local":
        try:
            return normalise_bambu_endpoint(raw_url)
        except ManufacturerAdapterError as exc:
            raise PrinterConnectionError(str(exc)) from exc
    if adapter == "prusa":
        try:
            return normalise_prusalink_endpoint(raw_url)
        except ManufacturerAdapterError as exc:
            raise PrinterConnectionError(str(exc)) from exc
    if adapter == "flashforge":
        try:
            return normalise_flashforge_endpoint(raw_url)
        except ManufacturerAdapterError as exc:
            raise PrinterConnectionError(str(exc)) from exc
    if adapter == "anycubic":
        try:
            return normalise_anycubic_endpoint(raw_url)
        except ManufacturerAdapterError as exc:
            raise PrinterConnectionError(str(exc)) from exc
    return normalise_printer_endpoint(raw_url)


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


def _flag(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    number = _finite_number(value)
    if number is not None:
        return number != 0
    text = str(value).strip().casefold()
    if text in {"true", "yes", "on", "connected", "online"}:
        return True
    if text in {"false", "no", "off", "disconnected", "offline", ""}:
        return False
    return default


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
    print_info = print_stats.get("info") or {}
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
            "current_layer": print_info.get("current_layer"),
            "total_layers": print_info.get("total_layer"),
        },
        "temperatures": {
            "tool0": _temperature(extruder.get("temperature"), extruder.get("target")),
            "bed": _temperature(bed.get("temperature"), bed.get("target")),
        },
        "warnings": [
            str(item)
            for item in ((server.get("result") or {}).get("warnings") or [])
            if str(item).strip()
        ],
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
    if completion is not None:
        # OctoPrint's documented job response reports completion as a 0..1
        # fraction. Accept 0..100 values too for compatibility with plugins
        # and older/alternate response shims.
        completion = completion * 100 if 0 <= completion <= 1 else completion
    job = job_payload.get("job") or {}
    file_data = job.get("file") or {}
    elapsed = _seconds(progress_data.get("printTime"))
    remaining = _seconds(progress_data.get("printTimeLeft"))
    if remaining is None:
        estimated = _seconds(job.get("estimatedPrintTime"))
        if estimated is not None and elapsed is not None:
            remaining = max(0, estimated - elapsed)
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
            "elapsed_seconds": elapsed,
            "remaining_seconds": remaining,
            "current_layer": None,
            "total_layers": None,
        },
        "temperatures": {
            "tool0": _temperature(tool0.get("actual"), tool0.get("target")),
            "bed": _temperature(bed.get("actual"), bed.get("target")),
        },
        "warnings": [str(job_payload.get("error"))] if job_payload.get("error") else [],
        "source_metadata": {
            "api": str(version.get("api") or ""),
            "server": str(version.get("server") or ""),
            "text": str(version.get("text") or ""),
        },
        "captured_at": timezone.now().isoformat(),
    })
    return snapshot


def _finite_number(value):
    number = _number(value)
    if number is None or not math.isfinite(number):
        return None
    return number


def _creality_state(payload: dict, *, ignore_error=False) -> str:
    err = payload.get("err")
    errcode = _finite_number(err.get("errcode") if isinstance(err, dict) else err)
    if not ignore_error and errcode not in (None, 0):
        return "error"

    self_test = _finite_number(payload.get("withSelfTest"))
    if self_test is not None and 1 <= self_test <= 99:
        return "self-testing"

    filename = str(payload.get("printFileName") or "").strip()
    progress = _finite_number(
        payload.get("printProgress")
        if payload.get("printProgress") is not None
        else payload.get("dProgress")
    )
    raw_state = _finite_number(payload.get("state"))
    raw_state = int(raw_state) if raw_state is not None else None

    if filename:
        if progress is not None and progress >= 100:
            return "complete"
        if raw_state == 5:
            return "paused"
        if raw_state == 4:
            return "cancelled"
        if raw_state == 1:
            return "printing"
        if raw_state == 0:
            return "processing"
    return "idle"


def _normalise_creality_colour(value) -> str:
    text = str(value or "").strip().lstrip("#")
    if len(text) == 7 and text.startswith("0"):
        text = text[1:]
    if len(text) >= 8:
        text = text[:6]
    if len(text) == 6 and all(char in "0123456789abcdefABCDEF" for char in text):
        return "#" + text.lower()
    return ""


def _creality_boxs_info(payload) -> dict | None:
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("boxsInfo"), dict):
        return payload["boxsInfo"]
    params = payload.get("params")
    if isinstance(params, dict) and isinstance(params.get("boxsInfo"), dict):
        return params["boxsInfo"]
    return None


def _creality_materials(boxs_info) -> list[dict]:
    if not isinstance(boxs_info, dict):
        return []
    boxes = boxs_info.get("materialBoxs")
    if not isinstance(boxes, list):
        return []

    result = []
    for box in boxes:
        if not isinstance(box, dict):
            continue
        try:
            box_type = int(box.get("type") or 0)
            box_id = int(box.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if box_type != 0:
            continue
        materials = box.get("materials")
        if not isinstance(materials, list):
            continue
        for raw in materials:
            if not isinstance(raw, dict):
                continue
            try:
                slot_id = int(raw.get("id"))
                material_state = int(raw.get("state") or 0)
            except (TypeError, ValueError):
                continue
            if material_state <= 0:
                continue
            percent = _finite_number(raw.get("percent"))
            result.append({
                "system": "creality_cfs",
                "unit_index": max(box_id - 1, 0),
                "slot_index": slot_id,
                "vendor": str(raw.get("vendor") or ""),
                "material": str(raw.get("type") or ""),
                "product_name": str(raw.get("name") or ""),
                "color_hex": _normalise_creality_colour(raw.get("color")),
                "remaining_percent": max(0.0, min(100.0, percent)) if percent is not None else None,
                "selected": _flag(raw.get("selected")),
                "rfid_detected": material_state == 2,
                "material_code": str(raw.get("rfid") or ""),
                "min_temp_c": _finite_number(raw.get("minTemp")),
                "max_temp_c": _finite_number(raw.get("maxTemp")),
                "box_temperature_c": _finite_number(box.get("temp")),
                "box_humidity_percent": _finite_number(box.get("humidity")),
            })
    return result


def normalise_creality_snapshot(payload: dict) -> dict:
    """Convert Creality's proprietary LAN telemetry into MakerVault's contract."""
    if not isinstance(payload, dict):
        raise PrinterConnectionError("Creality printer returned an unexpected telemetry payload.")

    state = _creality_state(payload)
    activity_state = _creality_state(payload, ignore_error=True)
    progress = _finite_number(
        payload.get("printProgress")
        if payload.get("printProgress") is not None
        else payload.get("dProgress")
    )
    if progress is not None:
        progress = max(0.0, min(100.0, progress))

    filename = str(payload.get("printFileName") or "").strip().replace("\\", "/")
    filename = filename.rsplit("/", 1)[-1] if filename else ""

    err = payload.get("err") if isinstance(payload.get("err"), dict) else {}
    errcode = _finite_number(err.get("errcode"))
    warnings = []
    if errcode not in (None, 0):
        key = err.get("key")
        warnings.append(
            f"Creality error {int(errcode)}"
            + (f" (key {key})" if key not in (None, "") else "")
        )

    cfs_info = payload.get("boxsInfo")
    materials = _creality_materials(cfs_info)

    snapshot = _blank_snapshot("creality_local")
    snapshot.update({
        "online": _flag(payload.get("connect"), default=True),
        "state": state,
        "state_label": {
            "self-testing": "Self-testing",
            "processing": "Preparing",
            "complete": "Complete",
            "cancelled": "Stopped",
        }.get(state, state.replace("_", " ").title()),
        "job": {
            "file_name": filename,
            "progress": round(progress, 2) if progress is not None else None,
            "elapsed_seconds": _seconds(payload.get("printJobTime")),
            "remaining_seconds": _seconds(payload.get("printLeftTime")),
            "current_layer": int(_finite_number(payload.get("layer"))) if _finite_number(payload.get("layer")) is not None else None,
            "total_layers": int(_finite_number(payload.get("TotalLayer"))) if _finite_number(payload.get("TotalLayer")) is not None else None,
        },
        "temperatures": {
            "tool0": _temperature(payload.get("nozzleTemp"), payload.get("targetNozzleTemp")),
            "bed": _temperature(payload.get("bedTemp0"), payload.get("targetBedTemp0")),
            "chamber": _temperature(payload.get("boxTemp"), payload.get("targetBoxTemp")),
        },
        "warnings": warnings,
        "materials": materials,
        "source_metadata": {
            "hostname": str(payload.get("hostname") or ""),
            "model": str(payload.get("model") or ""),
            "model_version": str(payload.get("modelVersion") or ""),
            "raw_state": payload.get("state"),
            "activity_state": activity_state,
            "device_state": payload.get("deviceState"),
            "cfs_connected": _flag(payload.get("cfsConnect")) or bool(materials),
            "cfs_loaded_slots": len(materials),
            "webrtc_support": _flag(payload.get("webrtcSupport")),
            "video_available": _flag(payload.get("video")) or _flag(payload.get("video1")),
            "feedrate_percent": _finite_number(payload.get("curFeedratePct")),
            "flowrate_percent": _finite_number(payload.get("curFlowratePct")),
            "model_fan_percent": _finite_number(payload.get("modelFanPct")),
            "case_fan_percent": _finite_number(payload.get("caseFanPct")),
            "auxiliary_fan_percent": _finite_number(payload.get("auxiliaryFanPct")),
            "used_material_length": _finite_number(payload.get("usedMaterialLength")),
            "material_status": payload.get("materialStatus"),
            "protocol": "Creality LAN WebSocket :9999",
        },
        "captured_at": timezone.now().isoformat(),
    })
    return snapshot


def _creality_payload_data(payload) -> dict:
    if not isinstance(payload, dict):
        return {}
    params = payload.get("params")
    if isinstance(params, dict):
        result = dict(payload)
        result.pop("params", None)
        result.update(params)
        return result
    return dict(payload)


async def _fetch_creality_status(endpoint_url: str) -> dict:
    uri = normalise_creality_endpoint(endpoint_url)
    merged = {}
    try:
        async with websockets.connect(
            uri,
            ping_interval=None,
            subprotocols=["wsslicer"],
            open_timeout=5,
            close_timeout=1,
            proxy=None,
        ) as ws:
            # K-series printers normally send a complete status frame
            # immediately. ReqPrinterPara gives us a deterministic fallback and
            # is read-only.
            await ws.send(json.dumps(
                {"method": "get", "params": {"ReqPrinterPara": 1}},
                separators=(",", ":"),
            ))
            await ws.send(json.dumps(
                {"method": "get", "params": {"boxsInfo": 1}},
                separators=(",", ":"),
            ))
            deadline = asyncio.get_running_loop().time() + 7
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
                boxs_info = _creality_boxs_info(payload)
                if boxs_info is not None:
                    merged["boxsInfo"] = boxs_info

                data = _creality_payload_data(payload)
                if data:
                    # Do not flatten the nested CFS payload over the telemetry
                    # namespace; it has its own normaliser above.
                    data.pop("boxsInfo", None)
                    merged.update(data)

                enough = (
                    "state" in merged
                    and ("printProgress" in merged or "dProgress" in merged)
                    and "nozzleTemp" in merged
                    and "bedTemp0" in merged
                )
                cfs_expected = _flag(merged.get("cfsConnect"))
                if enough and (not cfs_expected or "boxsInfo" in merged):
                    return merged
    except (OSError, asyncio.TimeoutError, WebSocketException) as exc:
        raise PrinterConnectionError("MakerVault could not reach the Creality LAN WebSocket service on port 9999.") from exc

    if merged:
        return merged
    raise PrinterConnectionError("The Creality printer connected but did not return usable telemetry.")


def poll_creality_local(endpoint_url: str, config: dict | None = None) -> dict:
    del config
    try:
        payload = asyncio.run(_fetch_creality_status(endpoint_url))
    except RuntimeError as exc:
        raise PrinterConnectionError("MakerVault could not start the Creality telemetry reader.") from exc
    return normalise_creality_snapshot(payload)


POLLERS: dict[str, Callable[[str, dict | None], dict]] = {
    "moonraker": poll_moonraker,
    "elegoo": poll_moonraker,
    "qidi": poll_moonraker,
    "sovol": poll_moonraker,
    "snapmaker": poll_moonraker,
    "voron": poll_moonraker,
    "octoprint": poll_octoprint,
    "creality_local": poll_creality_local,
    "bambu_local": poll_bambu_local,
    "prusa": poll_prusalink,
    "flashforge": poll_flashforge,
    "anycubic": poll_anycubic_local,
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
    except ManufacturerAdapterError as exc:
        wrapped = PrinterConnectionError(str(exc))
        connection.status = "disconnected"
        connection.last_error = str(wrapped)
        connection.last_checked_at = timezone.now()
        connection.save(update_fields=["status", "last_error", "last_checked_at", "updated_at"])
        raise wrapped from exc
    except PrinterConnectionError as exc:
        connection.status = "disconnected"
        connection.last_error = str(exc)
        connection.last_checked_at = timezone.now()
        connection.save(update_fields=["status", "last_error", "last_checked_at", "updated_at"])
        raise

    if connection.adapter in {"elegoo", "qidi", "sovol", "snapmaker", "voron"}:
        source_metadata = dict(snapshot.get("source_metadata") or {})
        source_metadata["protocol"] = "Moonraker / Klipper"
        source_metadata["manufacturer_profile"] = connection.adapter
        snapshot = {
            **snapshot,
            "adapter": connection.adapter,
            "source_metadata": source_metadata,
        }

    job_result = sync_print_job_from_snapshot(connection, snapshot)
    material_result = sync_live_material_slots(connection, snapshot)
    snapshot = {
        **snapshot,
        "maker_vault_job": job_result,
        "maker_vault_materials": material_result,
    }

    now = timezone.now()
    connection.status = "connected"
    connection.last_error = ""
    connection.last_checked_at = now
    connection.last_seen_at = now
    capabilities = dict(definition.capabilities)
    metadata = snapshot.get("source_metadata") or {}
    if connection.adapter == "creality_local":
        capabilities["camera"] = bool(
            metadata.get("video_available") or metadata.get("webrtc_support")
        )
        capabilities["materials"] = bool(
            metadata.get("cfs_connected") or snapshot.get("materials")
        )
    elif connection.adapter == "bambu_local":
        capabilities["camera"] = bool(metadata.get("camera_available"))
        capabilities["materials"] = bool(
            metadata.get("ams_connected") or snapshot.get("materials")
        )
    elif connection.adapter == "prusa":
        capabilities["camera"] = bool(metadata.get("camera_available"))
    elif connection.adapter == "flashforge":
        capabilities["camera"] = bool(metadata.get("camera_available"))
        capabilities["materials"] = bool(
            metadata.get("material_station_connected") or snapshot.get("materials")
        )
    elif connection.adapter == "anycubic":
        capabilities["camera"] = bool(metadata.get("camera_available"))
        capabilities["materials"] = bool(
            metadata.get("ace_connected") or snapshot.get("materials")
        )
    connection.capabilities = capabilities
    connection.last_snapshot = snapshot
    connection.save(update_fields=[
        "status", "last_error", "last_checked_at", "last_seen_at",
        "capabilities", "last_snapshot", "updated_at",
    ])
    return snapshot
