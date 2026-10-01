from __future__ import annotations

import base64
import hashlib
import json
import math
import secrets
import ssl
import string
import threading
import time
import uuid
from urllib.parse import urlencode, urlparse

import paho.mqtt.client as mqtt
import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7
from django.utils import timezone
from requests.auth import HTTPDigestAuth


class ManufacturerAdapterError(RuntimeError):
    pass


def _mqtt_identifier(value, label: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 128 or any(char in text for char in ("#", "+", "/", "\\", "\x00")):
        raise ManufacturerAdapterError(f"{label} contains characters that are not valid for a printer MQTT identity.")
    return text


def _same_network_origin(candidate_url: str, base_url: str, label: str) -> str:
    candidate = urlparse(str(candidate_url or "").strip())
    base = urlparse(base_url)
    if candidate.scheme not in {"http", "https"} or not candidate.hostname:
        raise ManufacturerAdapterError(f"Anycubic LAN handshake returned an invalid {label} URL.")
    if candidate.username or candidate.password:
        raise ManufacturerAdapterError(f"Anycubic LAN handshake returned credentials inside the {label} URL.")
    if candidate.hostname.casefold() != (base.hostname or "").casefold():
        raise ManufacturerAdapterError(
            f"Anycubic LAN handshake tried to redirect {label} to a different host; MakerVault refused it."
        )
    return candidate.geturl()


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _seconds(value):
    number = _number(value)
    if number is None or number < 0:
        return None
    return int(round(number))


def _temperature(actual=None, target=None):
    return {"actual_c": _number(actual), "target_c": _number(target)}


def _blank_snapshot(adapter):
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


def _host_url(raw_url, *, scheme, default_port=None):
    value = str(raw_url or "").strip().rstrip("/")
    if not value:
        raise ManufacturerAdapterError("Enter the printer host or service URL.")
    if "://" not in value:
        parsed = urlparse("//" + value)
    else:
        parsed = urlparse(value)
    if not parsed.hostname or parsed.username or parsed.password:
        raise ManufacturerAdapterError("Printer endpoint must contain a host and must not embed credentials.")
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = parsed.port or default_port
    suffix = f":{port}" if port else ""
    return f"{scheme}://{host}{suffix}"


def normalise_bambu_endpoint(raw_url: str) -> str:
    return _host_url(raw_url, scheme="mqtts", default_port=8883)


def normalise_anycubic_endpoint(raw_url: str) -> str:
    value = str(raw_url or "").strip().rstrip("/")
    if not value:
        raise ManufacturerAdapterError("Enter the Anycubic printer host or URL.")
    if "://" not in value:
        parsed = urlparse("//" + value)
        scheme = "http"
    else:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"}:
            raise ManufacturerAdapterError("Anycubic LAN endpoints must use HTTP or HTTPS.")
        scheme = parsed.scheme
    if not parsed.hostname or parsed.username or parsed.password:
        raise ManufacturerAdapterError("Anycubic endpoint must contain a host and must not embed credentials.")
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = parsed.port or 18910
    return f"{scheme}://{host}:{port}"


def normalise_flashforge_endpoint(raw_url: str) -> str:
    value = str(raw_url or "").strip().rstrip("/")
    if not value:
        raise ManufacturerAdapterError("Enter the FlashForge printer host or URL.")
    if "://" not in value:
        parsed = urlparse("//" + value)
        scheme = "http"
    else:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"}:
            raise ManufacturerAdapterError("FlashForge endpoints must use HTTP or HTTPS.")
        scheme = parsed.scheme
    if not parsed.hostname or parsed.username or parsed.password:
        raise ManufacturerAdapterError("FlashForge endpoint must contain a host and must not embed credentials.")
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = parsed.port or 8898
    return f"{scheme}://{host}:{port}"


def normalise_prusalink_endpoint(raw_url: str) -> str:
    value = str(raw_url or "").strip().rstrip("/")
    if not value:
        raise ManufacturerAdapterError("Enter the PrusaLink printer host or URL.")
    if "://" not in value:
        return _host_url(value, scheme="http")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ManufacturerAdapterError("PrusaLink endpoints must use HTTP or HTTPS.")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ManufacturerAdapterError("PrusaLink endpoint must contain a host and must not embed credentials.")
    return value


def _bambu_colour(value) -> str:
    text = str(value or "").strip().lstrip("#")
    if len(text) >= 8:
        text = text[:6]
    if len(text) == 6 and all(char in "0123456789abcdefABCDEF" for char in text):
        return "#" + text.lower()
    return ""


def _bambu_state(raw) -> str:
    value = str(raw or "").strip().upper()
    return {
        "IDLE": "idle",
        "RUNNING": "printing",
        "PRINTING": "printing",
        "PAUSE": "paused",
        "PAUSED": "paused",
        "FINISH": "complete",
        "FINISHED": "complete",
        "FAILED": "error",
        "ERROR": "error",
        "PREPARE": "processing",
        "PREPARING": "processing",
    }.get(value, value.lower() or "unknown")


def _bambu_materials(print_data: dict) -> list[dict]:
    ams_info = print_data.get("ams") or {}
    units = ams_info.get("ams") if isinstance(ams_info, dict) else []
    if not isinstance(units, list):
        return []

    selected_raw = _number(ams_info.get("tray_now")) if isinstance(ams_info, dict) else None
    selected = int(selected_raw) if selected_raw is not None else None
    rows = []
    for unit in units:
        if not isinstance(unit, dict):
            continue
        unit_number = _number(unit.get("id"))
        unit_index = int(unit_number) if unit_number is not None else 0
        trays = unit.get("tray")
        if not isinstance(trays, list):
            continue
        for tray in trays:
            if not isinstance(tray, dict):
                continue
            slot_number = _number(tray.get("id"))
            if slot_number is None:
                continue
            slot_index = int(slot_number)
            material = str(tray.get("tray_type") or "").strip()
            name = str(tray.get("tray_sub_brands") or tray.get("tray_id_name") or "").strip()
            tag_uid = str(tray.get("tag_uid") or "").strip()
            tray_uuid = str(tray.get("tray_uuid") or "").strip()
            if not any((material, name, tag_uid.strip("0"), tray_uuid.strip("0"))):
                continue
            remain = _number(tray.get("remain"))
            physical_index = unit_index * 4 + slot_index
            rows.append({
                "system": "bambu_ams",
                "unit_index": unit_index,
                "slot_index": slot_index,
                "vendor": "Bambu Lab" if str(tray.get("tray_info_idx") or "").strip() else "",
                "material": material,
                "product_name": name or material or "Filament",
                "color_hex": _bambu_colour(tray.get("tray_color")),
                "remaining_percent": max(0.0, min(100.0, remain)) if remain is not None else None,
                "selected": selected == physical_index,
                "rfid_detected": bool(tag_uid and tag_uid.strip("0")),
                "material_code": str(tray.get("tray_info_idx") or ""),
                "rfid_uid": tag_uid if tag_uid and tag_uid.strip("0") else "",
                "min_temp_c": _number(tray.get("nozzle_temp_min")),
                "max_temp_c": _number(tray.get("nozzle_temp_max")),
                "box_temperature_c": _number(unit.get("temp")),
                "box_humidity_percent": _number(unit.get("humidity")),
            })
    return rows


def normalise_bambu_snapshot(payload: dict, *, serial="") -> dict:
    if not isinstance(payload, dict):
        raise ManufacturerAdapterError("Bambu printer returned an unexpected telemetry payload.")
    print_data = payload.get("print") if isinstance(payload.get("print"), dict) else payload
    state = _bambu_state(print_data.get("gcode_state"))
    progress = _number(print_data.get("mc_percent"))
    if progress is not None:
        progress = max(0.0, min(100.0, progress))

    start_time = _number(print_data.get("gcode_start_time"))
    elapsed = None
    if start_time and start_time > 1_000_000_000:
        elapsed = max(0, int(time.time() - start_time))
    remaining_minutes = _number(print_data.get("mc_remaining_time"))
    remaining = int(round(remaining_minutes * 60)) if remaining_minutes is not None and remaining_minutes >= 0 else None

    materials = _bambu_materials(print_data)
    hms = print_data.get("hms")
    warnings = []
    if isinstance(hms, list):
        for item in hms:
            if not isinstance(item, dict):
                continue
            code = item.get("code") or item.get("attr") or item.get("msg")
            if code not in (None, "", 0, "0"):
                warnings.append("Bambu HMS " + str(code))

    ipcam = print_data.get("ipcam") if isinstance(print_data.get("ipcam"), dict) else {}
    snapshot = _blank_snapshot("bambu_local")
    snapshot.update({
        "online": True,
        "state": state,
        "state_label": state.replace("_", " ").title(),
        "job": {
            "file_name": str(print_data.get("subtask_name") or print_data.get("gcode_file") or ""),
            "progress": round(progress, 2) if progress is not None else None,
            "elapsed_seconds": elapsed,
            "remaining_seconds": remaining,
            "current_layer": int(_number(print_data.get("layer_num"))) if _number(print_data.get("layer_num")) is not None else None,
            "total_layers": int(_number(print_data.get("total_layer_num"))) if _number(print_data.get("total_layer_num")) is not None else None,
        },
        "temperatures": {
            "tool0": _temperature(print_data.get("nozzle_temper"), print_data.get("nozzle_target_temper")),
            "bed": _temperature(print_data.get("bed_temper"), print_data.get("bed_target_temper")),
            "chamber": _temperature(print_data.get("chamber_temper"), None),
        },
        "warnings": warnings,
        "materials": materials,
        "source_metadata": {
            "serial": serial,
            "raw_state": str(print_data.get("gcode_state") or ""),
            "speed_level": _number(print_data.get("spd_lvl")),
            "speed_percent": _number(print_data.get("spd_mag")),
            "ams_connected": bool(materials or (print_data.get("ams") or {}).get("ams")),
            "ams_units": len((print_data.get("ams") or {}).get("ams") or []),
            "camera_available": bool(ipcam),
            "protocol": "Bambu LAN MQTT/TLS :8883",
        },
        "captured_at": timezone.now().isoformat(),
    })
    return snapshot


def poll_bambu_local(endpoint_url: str, config: dict | None = None) -> dict:
    config = config or {}
    serial = str(config.get("serial") or "").strip()
    access_code = str(config.get("access_code") or "").strip()
    if not serial:
        raise ManufacturerAdapterError("Bambu local monitoring requires the printer serial number.")
    serial = _mqtt_identifier(serial, "Bambu printer serial")
    if not access_code:
        raise ManufacturerAdapterError("Bambu local monitoring requires the printer LAN access code.")

    parsed = urlparse(normalise_bambu_endpoint(endpoint_url))
    host = parsed.hostname
    port = parsed.port or 8883
    received = {}
    ready = threading.Event()
    error = {"message": ""}

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        protocol=mqtt.MQTTv311,
    )
    client.username_pw_set("bblp", access_code)
    # Bambu LAN printers present a device-local certificate rather than a
    # public-CA certificate. Authentication remains protected by TLS + the
    # LAN access code, but hostname/public-CA validation is not possible.
    client.tls_set(cert_reqs=ssl.CERT_NONE)  # nosec B504
    client.tls_insecure_set(True)

    topic_report = f"device/{serial}/report"
    topic_request = f"device/{serial}/request"

    def on_connect(client_obj, _userdata, _flags, reason_code, _properties):
        if getattr(reason_code, "is_failure", False):
            error["message"] = f"Bambu MQTT rejected the connection ({reason_code})."
            ready.set()
            return
        client_obj.subscribe(topic_report, qos=0)
        client_obj.publish(
            topic_request,
            json.dumps({
                "pushing": {
                    "sequence_id": "0",
                    "command": "pushall",
                    "version": 1,
                    "push_target": 1,
                }
            }),
            qos=0,
        )

    def on_message(_client_obj, _userdata, message):
        try:
            payload = json.loads(message.payload.decode("utf-8", "replace"))
        except (ValueError, UnicodeDecodeError):
            return
        if isinstance(payload, dict) and isinstance(payload.get("print"), dict):
            received.update(payload)
            ready.set()

    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(host, port, keepalive=15)
        client.loop_start()
        if not ready.wait(8):
            raise ManufacturerAdapterError("Bambu printer connected but did not return a status report.")
        if error["message"]:
            raise ManufacturerAdapterError(error["message"])
        if not received:
            raise ManufacturerAdapterError("Bambu printer returned no usable telemetry.")
        return normalise_bambu_snapshot(received, serial=serial)
    except (OSError, mqtt.MQTTException) as exc:
        raise ManufacturerAdapterError("MakerVault could not reach the Bambu LAN MQTT service on port 8883.") from exc
    finally:
        try:
            client.disconnect()
        except Exception:
            pass
        client.loop_stop()


def _anycubic_sign(token: str, timestamp_ms: int, nonce: str) -> str:
    first = hashlib.md5(token[:16].encode(), usedforsecurity=False).hexdigest()
    return hashlib.md5(
        (first + str(timestamp_ms) + nonce).encode(),
        usedforsecurity=False,
    ).hexdigest()


def _anycubic_decrypt_ctrl(info_b64: str, token: str, local_token: str) -> dict:
    try:
        key = token[16:32].encode()
        iv = local_token.encode()[:16].ljust(16, b"\0")
        decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        padded = decryptor.update(base64.b64decode(info_b64)) + decryptor.finalize()
        unpadder = PKCS7(128).unpadder()
        plaintext = unpadder.update(padded) + unpadder.finalize()
        payload = json.loads(plaintext.decode())
    except Exception as exc:
        raise ManufacturerAdapterError("Anycubic LAN handshake data could not be decrypted.") from exc
    if not isinstance(payload, dict):
        raise ManufacturerAdapterError("Anycubic LAN handshake returned unexpected broker data.")
    return payload


def _anycubic_handshake(endpoint_url: str) -> dict:
    base = normalise_anycubic_endpoint(endpoint_url)
    try:
        info_response = requests.get(
            base + "/info",
            headers={"Accept": "application/json", "User-Agent": "MakerVault/0.7.3 (+Anycubic LAN adapter)"},
            timeout=(3, 8),
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise ManufacturerAdapterError("MakerVault could not reach the Anycubic LAN service on port 18910.") from exc
    if info_response.status_code >= 400:
        raise ManufacturerAdapterError(f"Anycubic LAN /info returned HTTP {info_response.status_code}.")
    try:
        info = info_response.json()
    except ValueError as exc:
        raise ManufacturerAdapterError("Anycubic LAN /info returned invalid JSON.") from exc
    if not isinstance(info, dict):
        raise ManufacturerAdapterError("Anycubic LAN /info returned an unexpected response.")
    if str(info.get("ctrlType") or "").lower() == "cloud":
        raise ManufacturerAdapterError("Anycubic printer is in cloud mode. Enable LAN mode on the printer first.")

    token = str(info.get("token") or "")
    ctrl_url = str(info.get("ctrlInfoUrl") or "")
    model_id = str(info.get("modelId") or "")
    if len(token) < 32 or not ctrl_url or not model_id:
        raise ManufacturerAdapterError(
            "This Anycubic printer does not expose the signed Kobra 3/S1-generation LAN handshake."
        )

    ctrl_url = _same_network_origin(ctrl_url, base, "control")
    model_id = _mqtt_identifier(model_id, "Anycubic model ID")

    timestamp_ms = int(time.time() * 1000)
    nonce = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(6))
    did = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(32))
    query = urlencode({
        "ts": timestamp_ms,
        "nonce": nonce,
        "sign": _anycubic_sign(token, timestamp_ms, nonce),
        "did": did,
    })
    separator = "&" if "?" in ctrl_url else "?"
    try:
        ctrl_response = requests.post(
            ctrl_url + separator + query,
            headers={"Accept": "application/json", "User-Agent": "MakerVault/0.7.3 (+Anycubic LAN adapter)"},
            timeout=(3, 8),
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise ManufacturerAdapterError("MakerVault could not complete the Anycubic LAN handshake.") from exc
    if ctrl_response.status_code >= 400:
        raise ManufacturerAdapterError(f"Anycubic LAN /ctrl returned HTTP {ctrl_response.status_code}.")
    try:
        ctrl = ctrl_response.json()
    except ValueError as exc:
        raise ManufacturerAdapterError("Anycubic LAN /ctrl returned invalid JSON.") from exc
    if not isinstance(ctrl, dict) or ctrl.get("code") != 200:
        raise ManufacturerAdapterError(
            "Anycubic LAN handshake failed"
            + (f": {ctrl.get('message')}" if isinstance(ctrl, dict) and ctrl.get("message") else ".")
        )
    data = ctrl.get("data") or {}
    decrypted = _anycubic_decrypt_ctrl(
        str(data.get("info") or ""),
        token,
        str(data.get("token") or ""),
    )
    broker = urlparse(str(decrypted.get("broker") or ""))
    if broker.scheme not in {"mqtt", "mqtts"} or not broker.hostname:
        raise ManufacturerAdapterError("Anycubic LAN handshake returned an invalid MQTT broker.")
    base_host = (urlparse(base).hostname or "").casefold()
    if broker.hostname.casefold() != base_host:
        raise ManufacturerAdapterError(
            "Anycubic LAN handshake returned an MQTT broker on a different host; MakerVault refused it."
        )
    device_id = _mqtt_identifier(decrypted.get("deviceId"), "Anycubic device ID")
    return {
        "broker_host": broker.hostname,
        "broker_port": broker.port or (9883 if broker.scheme == "mqtts" else 1883),
        "username": str(decrypted.get("username") or ""),
        "password": str(decrypted.get("password") or ""),
        "device_id": device_id,
        "model_id": model_id,
        "serial": str(info.get("cn") or ""),
        "model_name": str(info.get("modelName") or ""),
        "device_type": str(info.get("deviceType") or ""),
        "broker_tls": broker.scheme == "mqtts",
    }


def _anycubic_state(raw_state, project: dict) -> str:
    raw = str(raw_state or "").strip().lower()
    project_state = str(project.get("state") or "").strip().lower()
    pause = _number(project.get("pause"))
    if pause == 1 or project_state == "paused":
        return "paused"
    if project_state in {"pausing", "resuming", "resumed", "preheating", "auto_leveling", "vibrating", "flow_calibrating"}:
        return "processing"
    if project_state == "printing":
        return "printing"
    if project_state in {"stopping", "stoped", "stopped"}:
        return "cancelled"
    if project_state in {"finished", "complete", "completed"}:
        return "complete"
    if project_state in {"error", "failed"}:
        return "error"
    if raw == "free":
        return "idle"
    if raw == "busy":
        return "processing"
    return project_state or raw or "unknown"


def _anycubic_colour(value) -> str:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return ""
    try:
        red, green, blue = (max(0, min(255, int(value[index]))) for index in range(3))
    except (TypeError, ValueError):
        return ""
    return f"#{red:02x}{green:02x}{blue:02x}"


def _anycubic_materials(box_data: dict) -> list[dict]:
    boxes = box_data.get("multi_color_box") if isinstance(box_data, dict) else []
    if not isinstance(boxes, list):
        return []
    rows = []
    for box in boxes:
        if not isinstance(box, dict):
            continue
        box_id = int(_number(box.get("id")) or 0)
        loaded_slot = _number(box.get("loaded_slot"))
        loaded_slot = int(loaded_slot) if loaded_slot is not None else None
        dry = box.get("drying_status") if isinstance(box.get("drying_status"), dict) else {}
        humidity = box.get("humidity")
        if humidity is None:
            humidity = dry.get("humidity")
        slots = box.get("slots")
        if not isinstance(slots, list):
            continue
        for slot in slots:
            if not isinstance(slot, dict):
                continue
            slot_index = _number(slot.get("index"))
            if slot_index is None:
                continue
            slot_index = int(slot_index)
            material = str(slot.get("type") or "").strip()
            if not material:
                continue
            remaining = _number(slot.get("consumables_percent"))
            rows.append({
                "system": "anycubic_ace",
                "unit_index": max(box_id, 0),
                "slot_index": max(slot_index, 0),
                "vendor": "Anycubic",
                "material": material,
                "product_name": material,
                "color_hex": _anycubic_colour(slot.get("color")),
                "remaining_percent": max(0.0, min(100.0, remaining)) if remaining is not None else None,
                "selected": loaded_slot == slot_index,
                "rfid_detected": False,
                "material_code": str(slot.get("sku") or ""),
                "rfid_uid": "",
                "min_temp_c": None,
                "max_temp_c": None,
                "box_temperature_c": _number(box.get("temp")),
                "box_humidity_percent": _number(humidity),
                "drying_active": _number(dry.get("status")) == 1,
                "drying_target_c": _number(dry.get("target_temp")),
                "drying_remaining_minutes": _number(dry.get("remain_time")),
            })
    return rows


def normalise_anycubic_snapshot(
    info_data: dict,
    box_data: dict | None = None,
    *,
    identity: dict | None = None,
    peripheral_data: dict | None = None,
) -> dict:
    if not isinstance(info_data, dict):
        raise ManufacturerAdapterError("Anycubic printer returned an unexpected info payload.")
    identity = identity or {}
    peripheral_data = peripheral_data if isinstance(peripheral_data, dict) else {}
    project = info_data.get("project")
    if not isinstance(project, dict) or not project:
        project = info_data.get("last_project") if isinstance(info_data.get("last_project"), dict) else {}
    state = _anycubic_state(info_data.get("state"), project)
    progress = _number(project.get("progress"))
    if progress is not None:
        progress = max(0.0, min(100.0, progress))
    temp = info_data.get("temp") if isinstance(info_data.get("temp"), dict) else {}
    filename = str(project.get("filename") or "").replace("\\", "/").rsplit("/", 1)[-1]
    materials = _anycubic_materials(box_data or {})
    urls = info_data.get("urls") if isinstance(info_data.get("urls"), dict) else {}
    camera_url = str(urls.get("rtspUrl") or "").strip()

    snapshot = _blank_snapshot("anycubic")
    snapshot.update({
        "online": True,
        "state": state,
        "state_label": state.replace("_", " ").title(),
        "job": {
            "file_name": filename,
            "progress": round(progress, 2) if progress is not None else None,
            "elapsed_seconds": _seconds(project.get("print_time")),
            "remaining_seconds": (
                int(round(_number(project.get("remain_time")) * 60))
                if _number(project.get("remain_time")) is not None
                else None
            ),
            "current_layer": int(_number(project.get("curr_layer"))) if _number(project.get("curr_layer")) is not None else None,
            "total_layers": int(_number(project.get("total_layers"))) if _number(project.get("total_layers")) is not None else None,
        },
        "temperatures": {
            "tool0": _temperature(temp.get("curr_nozzle_temp"), temp.get("target_nozzle_temp")),
            "bed": _temperature(temp.get("curr_hotbed_temp"), temp.get("target_hotbed_temp")),
            "chamber": _temperature(temp.get("curr_chamber_temp"), temp.get("target_chamber_temp")),
        },
        "camera_url": camera_url if camera_url.startswith(("http://", "https://", "rtsp://")) else "",
        "materials": materials,
        "source_metadata": {
            "serial": str(identity.get("serial") or ""),
            "model_id": str(identity.get("model_id") or ""),
            "device_id": str(identity.get("device_id") or ""),
            "model": str(info_data.get("model") or identity.get("model_name") or ""),
            "firmware": str(info_data.get("version") or ""),
            "raw_state": str(info_data.get("state") or ""),
            "project_state": str(project.get("state") or ""),
            "pause_code": project.get("pause"),
            "camera_available": bool(camera_url or peripheral_data.get("camera")),
            "ace_connected": bool(
                materials
                or box_data
                or peripheral_data.get("multiColorBox")
            ),
            # Empty/absent ACE getInfo responses are common while idle. Only a
            # received multiColorBox payload is authoritative enough to retire
            # previously loaded slot observations.
            "ace_slots_observed": bool(box_data),
            "ace_units": len((box_data or {}).get("multi_color_box") or []) if isinstance(box_data, dict) else 0,
            "fan_percent": _number(info_data.get("fan_speed_pct")),
            "aux_fan_percent": _number(info_data.get("aux_fan_speed_pct")),
            "print_speed_mode": _number(info_data.get("print_speed_mode")),
            "protocol": "Anycubic LAN signed HTTP + MQTT/TLS",
        },
        "captured_at": timezone.now().isoformat(),
    })
    return snapshot


def poll_anycubic_local(endpoint_url: str, config: dict | None = None) -> dict:
    del config
    identity = _anycubic_handshake(endpoint_url)
    if not all((identity["username"], identity["password"], identity["device_id"])):
        raise ManufacturerAdapterError("Anycubic LAN handshake did not return usable MQTT credentials.")

    info_data = {}
    box_data = {}
    peripheral_data = {}
    info_ready = threading.Event()
    box_ready = threading.Event()
    error = {"message": ""}
    report_prefix = f"anycubic/anycubicCloud/v1/printer/public/{identity['model_id']}/{identity['device_id']}"
    request_prefix = f"anycubic/anycubicCloud/v1/web/printer/{identity['model_id']}/{identity['device_id']}"

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"makervault-{uuid.uuid4().hex[:8]}",
        protocol=mqtt.MQTTv311,
    )
    client.username_pw_set(identity["username"], identity["password"])
    if identity["broker_tls"]:
        client.tls_set(cert_reqs=ssl.CERT_NONE)  # nosec B504
        client.tls_insecure_set(True)

    def publish_query(message_type, action="query"):
        payload = json.dumps({
            "type": message_type,
            "action": action,
            "timestamp": int(time.time() * 1000),
            "msgid": uuid.uuid4().hex,
            "data": None,
        }, separators=(",", ":"))
        result = client.publish(f"{request_prefix}/{message_type}", payload)
        if getattr(result, "rc", mqtt.MQTT_ERR_SUCCESS) != mqtt.MQTT_ERR_SUCCESS:
            error["message"] = f"Anycubic MQTT could not publish the {message_type} query."

    def on_connect(client_obj, _userdata, _flags, reason_code, _properties):
        if getattr(reason_code, "is_failure", False):
            error["message"] = f"Anycubic MQTT rejected the connection ({reason_code})."
            info_ready.set()
            return
        client_obj.subscribe(f"{report_prefix}/#", qos=0)
        publish_query("info")
        publish_query("tempature")
        publish_query("fan")
        publish_query("multiColorBox", action="getInfo")
        publish_query("peripherie")

    def on_message(_client_obj, _userdata, message):
        try:
            payload = json.loads(message.payload.decode("utf-8", "replace"))
        except (ValueError, UnicodeDecodeError):
            return
        if not isinstance(payload, dict):
            return
        message_type = str(payload.get("type") or "")
        if not message_type:
            parts = message.topic.split("/")
            message_type = parts[-2] if len(parts) >= 2 and parts[-1] == "report" else ""
        data = payload.get("data")
        if not isinstance(data, dict):
            return
        if message_type == "info":
            info_data.update(data)
            info_ready.set()
        elif message_type == "tempature":
            temp = info_data.setdefault("temp", {})
            if isinstance(temp, dict):
                temp.update({key: value for key, value in data.items() if value is not None})
        elif message_type == "fan":
            for key in ("fan_speed_pct", "aux_fan_speed_pct", "box_fan_level"):
                if data.get(key) is not None:
                    info_data[key] = data[key]
        elif message_type == "multiColorBox":
            box_data.update(data)
            box_ready.set()
        elif message_type == "peripherie":
            peripheral_data.update(data)

    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(identity["broker_host"], identity["broker_port"], keepalive=20)
        client.loop_start()
        if not info_ready.wait(8):
            raise ManufacturerAdapterError("Anycubic printer connected but did not return an info report.")
        if error["message"]:
            raise ManufacturerAdapterError(error["message"])
        # ACE getInfo is activity-dependent on some firmware. Give it a short
        # opportunity without delaying every ordinary printer status poll.
        box_ready.wait(1.5)
        if not info_data:
            raise ManufacturerAdapterError("Anycubic printer returned no usable live telemetry.")
        return normalise_anycubic_snapshot(
            info_data,
            box_data,
            identity=identity,
            peripheral_data=peripheral_data,
        )
    except (OSError, mqtt.MQTTException) as exc:
        raise ManufacturerAdapterError("MakerVault could not reach the Anycubic local MQTT broker.") from exc
    finally:
        try:
            client.disconnect()
        except Exception:
            pass
        client.loop_stop()


def _flashforge_colour(value) -> str:
    text = str(value or "").strip().lstrip("#")
    if len(text) >= 8:
        text = text[:6]
    if len(text) == 6 and all(char in "0123456789abcdefABCDEF" for char in text):
        return "#" + text.lower()
    return ""


def _flashforge_state(value) -> str:
    raw = str(value or "").strip().lower()
    return {
        "ready": "idle",
        "idle": "idle",
        "busy": "processing",
        "downloading": "processing",
        "calibrate_doing": "processing",
        "heating": "processing",
        "printing": "printing",
        "pausing": "paused",
        "pause": "paused",
        "paused": "paused",
        "cancel": "cancelled",
        "cancelled": "cancelled",
        "completed": "complete",
        "complete": "complete",
        "error": "error",
    }.get(raw, raw or "unknown")


def _flashforge_materials(detail: dict) -> list[dict]:
    station = detail.get("matlStationInfo")
    if not isinstance(station, dict):
        return []
    slots = station.get("slotInfos")
    if not isinstance(slots, list):
        return []
    current = _number(station.get("currentLoadSlot"))
    if current is None:
        current = _number(station.get("currentSlot"))
    current = int(current) if current is not None else None

    result = []
    for raw in slots:
        if not isinstance(raw, dict) or not bool(raw.get("hasFilament")):
            continue
        raw_slot = _number(raw.get("slotId"))
        if raw_slot is None:
            continue
        raw_slot = int(raw_slot)
        result.append({
            "system": "flashforge_station",
            "unit_index": 0,
            "slot_index": max(raw_slot - 1, 0),
            "vendor": "FlashForge",
            "material": str(raw.get("materialName") or ""),
            "product_name": str(raw.get("materialName") or "Filament"),
            "color_hex": _flashforge_colour(raw.get("materialColor")),
            "remaining_percent": None,
            "selected": current == raw_slot,
            "rfid_detected": False,
            "material_code": "",
            "rfid_uid": "",
            "min_temp_c": None,
            "max_temp_c": None,
            "box_temperature_c": None,
            "box_humidity_percent": None,
        })
    return result


def normalise_flashforge_snapshot(payload: dict, *, serial="") -> dict:
    if not isinstance(payload, dict):
        raise ManufacturerAdapterError("FlashForge printer returned an unexpected telemetry payload.")
    if payload.get("code") not in (None, 0, "0"):
        raise ManufacturerAdapterError(f"FlashForge returned response code {payload.get('code')}.")
    detail = payload.get("detail") if isinstance(payload.get("detail"), dict) else payload

    state = _flashforge_state(detail.get("status"))
    progress = _number(detail.get("printProgress"))
    if progress is not None:
        progress = progress * 100 if 0 <= progress <= 1 else progress
        progress = max(0.0, min(100.0, progress))

    def safe_temp(value):
        number = _number(value)
        if number is not None and number <= -50:
            return None
        return number

    station_info = detail.get("matlStationInfo") if isinstance(detail.get("matlStationInfo"), dict) else {}
    station_slots_observed = isinstance(station_info.get("slotInfos"), list)
    materials = _flashforge_materials(detail)
    error_code = str(detail.get("errorCode") or "").strip()
    warnings = [f"FlashForge error {error_code}"] if error_code and error_code not in {"0", "none", "None"} else []

    chamber_actual = safe_temp(detail.get("chamberTemp"))
    chamber_target = safe_temp(detail.get("chamberTargetTemp"))
    camera_url = str(detail.get("cameraStreamUrl") or "").strip()
    thumbnail = str(detail.get("printFileThumbUrl") or "").strip()

    snapshot = _blank_snapshot("flashforge")
    snapshot.update({
        "online": True,
        "state": state,
        "state_label": state.replace("_", " ").title(),
        "job": {
            "file_name": str(detail.get("printFileName") or ""),
            "progress": round(progress, 2) if progress is not None else None,
            "elapsed_seconds": _seconds(detail.get("printDuration")),
            "remaining_seconds": _seconds(detail.get("estimatedTime")),
            "current_layer": int(_number(detail.get("printLayer"))) if _number(detail.get("printLayer")) is not None else None,
            "total_layers": int(_number(detail.get("targetPrintLayer"))) if _number(detail.get("targetPrintLayer")) is not None else None,
        },
        "temperatures": {
            "tool0": _temperature(safe_temp(detail.get("rightTemp")), safe_temp(detail.get("rightTargetTemp"))),
            "bed": _temperature(safe_temp(detail.get("platTemp")), safe_temp(detail.get("platTargetTemp"))),
            "chamber": _temperature(chamber_actual, chamber_target),
        },
        "thumbnail_url": thumbnail if thumbnail.startswith(("http://", "https://")) else "",
        "camera_url": camera_url if camera_url.startswith(("http://", "https://", "rtsp://")) else "",
        "warnings": warnings,
        "materials": materials,
        "source_metadata": {
            "serial": serial,
            "name": str(detail.get("name") or ""),
            "model": str(detail.get("model") or ""),
            "pid": detail.get("pid"),
            "firmware": str(detail.get("firmwareVersion") or ""),
            "raw_state": str(detail.get("status") or ""),
            "material_station_connected": bool(
                detail.get("hasMatlStation") is True
                or materials
                or (
                    isinstance(detail.get("matlStationInfo"), dict)
                    and (
                        _number(detail["matlStationInfo"].get("slotCnt")) or 0
                    ) > 0
                )
            ),
            "material_station_slots_observed": station_slots_observed,
            "camera_available": bool(detail.get("camera") == 1 or camera_url),
            "lidar_available": bool(detail.get("lidar") == 1),
            "speed_percent": _number(detail.get("printSpeedAdjust")),
            "current_print_speed": _number(detail.get("currentPrintSpeed")),
            "nozzle_count": int(_number(detail.get("nozzleCnt"))) if _number(detail.get("nozzleCnt")) is not None else None,
            "protocol": "FlashForge local HTTP :8898",
        },
        "captured_at": timezone.now().isoformat(),
    })
    return snapshot


def poll_flashforge(endpoint_url: str, config: dict | None = None) -> dict:
    config = config or {}
    serial = str(config.get("serial") or "").strip()
    check_code = str(config.get("check_code") or "").strip()
    if not serial:
        raise ManufacturerAdapterError("FlashForge local monitoring requires the printer serial number.")
    if not check_code:
        raise ManufacturerAdapterError("FlashForge local monitoring requires the printer check code.")

    base = normalise_flashforge_endpoint(endpoint_url)
    try:
        response = requests.post(
            base + "/detail",
            json={"serialNumber": serial, "checkCode": check_code},
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "MakerVault/0.7.3 (+FlashForge local adapter)",
            },
            timeout=(3, 10),
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise ManufacturerAdapterError("MakerVault could not reach the FlashForge local API on port 8898.") from exc

    if response.status_code in {401, 403}:
        raise ManufacturerAdapterError("FlashForge rejected the configured serial/check code.")
    if response.status_code >= 400:
        raise ManufacturerAdapterError(f"FlashForge returned HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ManufacturerAdapterError("FlashForge returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise ManufacturerAdapterError("FlashForge returned an unexpected response.")
    if payload.get("code") not in (None, 0, "0"):
        raise ManufacturerAdapterError("FlashForge rejected the configured serial/check code.")
    return normalise_flashforge_snapshot(payload, serial=serial)


def _prusa_request(base: str, path: str, config: dict, *, allow_empty=False):
    api_key = str(config.get("api_key") or "").strip()
    username = str(config.get("username") or "").strip()
    password = str(config.get("password") or "").strip()
    headers = {
        "Accept": "application/json",
        "User-Agent": "MakerVault/0.7.3 (+PrusaLink live printer adapter)",
    }
    if api_key:
        headers["X-Api-Key"] = api_key
    auth = HTTPDigestAuth(username, password) if username or password else None
    try:
        response = requests.get(
            base + path,
            headers=headers,
            auth=auth,
            timeout=(3, 8),
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise ManufacturerAdapterError("MakerVault could not reach PrusaLink.") from exc
    if allow_empty and response.status_code == 204:
        return {}
    if response.status_code in {401, 403}:
        raise ManufacturerAdapterError("PrusaLink rejected the configured credentials.")
    if response.status_code >= 400:
        raise ManufacturerAdapterError(f"PrusaLink returned HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ManufacturerAdapterError("PrusaLink returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise ManufacturerAdapterError("PrusaLink returned an unexpected response.")
    return payload


def normalise_prusalink_snapshot(status_payload: dict, job_payload: dict | None = None, info_payload: dict | None = None) -> dict:
    status_payload = status_payload if isinstance(status_payload, dict) else {}
    job_payload = job_payload if isinstance(job_payload, dict) else {}
    info_payload = info_payload if isinstance(info_payload, dict) else {}
    printer = status_payload.get("printer") or {}
    compact_job = status_payload.get("job") or {}
    raw_state = str(job_payload.get("state") or printer.get("state") or "UNKNOWN").upper()
    state = {
        "IDLE": "idle",
        "READY": "idle",
        "BUSY": "processing",
        "PRINTING": "printing",
        "PAUSED": "paused",
        "FINISHED": "complete",
        "STOPPED": "cancelled",
        "ERROR": "error",
        "ATTENTION": "error",
    }.get(raw_state, raw_state.lower())

    file_data = job_payload.get("file") if isinstance(job_payload.get("file"), dict) else {}
    progress = _number(job_payload.get("progress"))
    if progress is None:
        progress = _number(compact_job.get("progress"))
    if progress is not None:
        progress = max(0.0, min(100.0, progress))

    status_printer = printer.get("status_printer") if isinstance(printer.get("status_printer"), dict) else {}
    warnings = []
    if status_printer and status_printer.get("ok") is False and status_printer.get("message"):
        warnings.append(str(status_printer["message"]))

    camera = status_payload.get("camera") if isinstance(status_payload.get("camera"), dict) else {}
    snapshot = _blank_snapshot("prusa")
    snapshot.update({
        "online": True,
        "state": state,
        "state_label": state.replace("_", " ").title(),
        "job": {
            "file_name": str(file_data.get("display_name") or file_data.get("name") or ""),
            "progress": round(progress, 2) if progress is not None else None,
            "elapsed_seconds": _seconds(job_payload.get("time_printing") if job_payload.get("time_printing") is not None else compact_job.get("time_printing")),
            "remaining_seconds": _seconds(job_payload.get("time_remaining") if job_payload.get("time_remaining") is not None else compact_job.get("time_remaining")),
            "current_layer": None,
            "total_layers": None,
        },
        "temperatures": {
            "tool0": _temperature(printer.get("temp_nozzle"), printer.get("target_nozzle")),
            "bed": _temperature(printer.get("temp_bed"), printer.get("target_bed")),
        },
        "warnings": warnings,
        "source_metadata": {
            "raw_state": raw_state,
            "job_id": job_payload.get("id") or compact_job.get("id"),
            "flow_percent": _number(printer.get("flow")),
            "speed_percent": _number(printer.get("speed")),
            "camera_available": bool(camera.get("id")),
            "camera_id": str(camera.get("id") or ""),
            "printer_type": str(info_payload.get("printer_type") or info_payload.get("type") or ""),
            "firmware": str(info_payload.get("firmware") or info_payload.get("firmware_version") or ""),
            "protocol": "PrusaLink local API",
        },
        "captured_at": timezone.now().isoformat(),
    })
    return snapshot


def poll_prusalink(endpoint_url: str, config: dict | None = None) -> dict:
    base = normalise_prusalink_endpoint(endpoint_url)
    config = config or {}
    status_payload = _prusa_request(base, "/api/v1/status", config)
    job_payload = _prusa_request(base, "/api/v1/job", config, allow_empty=True)
    info_payload = _prusa_request(base, "/api/v1/info", config)
    return normalise_prusalink_snapshot(status_payload, job_payload, info_payload)
