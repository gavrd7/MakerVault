"""Stock Creality OS G-code storage and explicitly confirmed print operations.

File operations and proprietary print commands are separately validated and
must be invoked only by the owner-scoped submission workflow.
"""
from urllib.parse import urlparse, quote
import asyncio
import json
import logging
import re
import websockets
from websockets.exceptions import WebSocketException

import requests

from .printer_connectivity import normalise_creality_endpoint


logger = logging.getLogger(__name__)


class CrealityGcodeError(RuntimeError):
    pass


def _http_root(connection):
    remote = urlparse(normalise_creality_endpoint(connection.endpoint_url))
    host = remote.hostname
    if not host or remote.username or remote.password:
        raise CrealityGcodeError("Creality LAN endpoint is invalid.")
    if ":" in host:
        host = "[" + host + "]"
    return "http://" + host + ":80"


def upload_only(connection, asset, remote_name):
    if not isinstance(remote_name, str) or not remote_name.lower().endswith(".gcode") or len(remote_name) > 160:
        raise CrealityGcodeError("Only safe, plain-text .gcode filenames are supported.")
    if not remote_name.replace("-", "").replace("_", "").replace(".", "").isalnum():
        raise CrealityGcodeError("Unsafe Creality upload filename.")
    url = _http_root(connection) + "/upload/" + quote(remote_name, safe="")
    try:
        with asset.file.storage.open(asset.file.name, "rb") as handle:
            response = requests.post(
                url, files={"file": (remote_name, handle, "application/octet-stream")},
                timeout=(5, 120), allow_redirects=False,
            )
    except requests.RequestException as exc:
        raise CrealityGcodeError("Creality LAN upload outcome is uncertain; inspect printer files before any retry.") from exc
    if response.status_code not in (200, 201):
        raise CrealityGcodeError(
            "Creality stock upload endpoint rejected the file (HTTP %s). No start command was issued." % response.status_code
        )
    # A successful HTTP response is evidence of acceptance, not a verified
    # printer-side file checksum. No start follows this operation.
    return remote_name

# Stock Creality OS uses an uncorrelated WebSocket protocol.
FILE_LIST_FIELDS = ("retGcodeFileInfo2", "gcodeFiles", "gcodeFile", "gcodeList", "gcodeFileList", "files", "fileList")


def _safe_printer_file(value):
    if not isinstance(value, str) or not value.lower().endswith(".gcode"):
        return None
    candidate = value.replace("\\\\", "/")
    prefixes = ("/mnt/UDISK/printer_data/gcodes/", "/usr/data/printer_data/gcodes/")
    prefix = next((root for root in prefixes if candidate.startswith(root)), None)
    if prefix:
        candidate = candidate[len(prefix):]
    elif candidate.startswith("gcodes/"):
        candidate = candidate[7:]
    elif candidate.startswith("/"):
        return None
    if not 0 < len(candidate) <= 240 or any(part in {"", ".", ".."} for part in candidate.split("/")):
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.+() -]+(?:/[A-Za-z0-9_.+() -]+)*", candidate):
        return None
    return candidate


def _parse_legacy_gcode_file_info(value):
    """Old K1 firmware returns a packed semicolon-separated fileInfo string.

    Only parse the documented /usr/data and /mnt/UDISK G-code roots; never
    turn arbitrary absolute paths or other fields into selectable print files.
    """
    if not isinstance(value, dict) or not isinstance(value.get("fileInfo"), str):
        return None
    packed = value["fileInfo"]
    if len(packed) > 2_000_000:
        return None
    rows = []
    for record in packed.split(";")[:1000]:
        if not record.strip():
            continue
        fields = record.split(":")
        if len(fields) < 3:
            continue
        root, name, size = fields[:3]
        if root.rstrip("/") not in (
            "/usr/data/printer_data/gcodes", "/mnt/UDISK/printer_data/gcodes"
        ):
            continue
        safe = _safe_printer_file(name)
        if not safe:
            continue
        try:
            byte_size = int(size)
        except (ValueError, TypeError):
            byte_size = None
        if byte_size is not None and byte_size < 0:
            byte_size = None
        rows.append({"path": safe, "size_bytes": byte_size, "modified": None, "permissions": "r"})
    return rows


def _parse_file_list(payload):
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("params"), dict):
        payload = payload["params"]
    if isinstance(payload.get("data"), dict):
        payload = payload["data"]
    if "retGcodeFileInfo" in payload:
        return _parse_legacy_gcode_file_info(payload["retGcodeFileInfo"])
    for key in FILE_LIST_FIELDS:
        value = payload.get(key)
        if isinstance(value, dict):
            value = value.get("list") or value.get("files") or value.get("items")
        if not isinstance(value, list):
            continue
        rows = []
        for item in value[:1000]:
            name = item if isinstance(item, str) else (
                item.get("fileName") or item.get("filename") or item.get("name") or item.get("path")
            ) if isinstance(item, dict) else None
            safe = _safe_printer_file(name)
            if safe:
                rows.append({"path": safe, "size_bytes": (item.get("file_size", item.get("size")) if isinstance(item, dict) else None),
                             "modified": None, "permissions": "r"})
        return rows
    return None


async def _list_files(endpoint):
    merged = None
    observed_keys = set()
    frames_received = 0
    try:
        async with websockets.connect(
            normalise_creality_endpoint(endpoint), ping_interval=None,
            subprotocols=["wsslicer"], open_timeout=5, close_timeout=1, proxy=None
        ) as ws:
            await ws.send(json.dumps({"method": "get", "params": {"reqGcodeFile": 1}}))
            deadline = asyncio.get_running_loop().time() + 8
            while asyncio.get_running_loop().time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - asyncio.get_running_loop().time()))
                except asyncio.TimeoutError:
                    break
                try:
                    data = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                if isinstance(data, dict):
                    frames_received += 1
                    observed_keys.update(str(key)[:40] for key in data if isinstance(key, str))
                    for nested in ("params", "data"):
                        if isinstance(data.get(nested), dict):
                            observed_keys.update(str(key)[:40] for key in data[nested] if isinstance(key, str))
                if isinstance(data, dict) and data.get("ModeCode") == "heart_beat":
                    await ws.send("ok")
                    continue
                rows = _parse_file_list(data)
                if rows is not None:
                    merged = rows
                    break
    except (OSError, asyncio.TimeoutError, WebSocketException) as exc:
        raise CrealityGcodeError("Creality LAN G-code file discovery failed.") from exc
    if merged is None:
        logger.warning("Creality storage list probe yielded no recognized response: frames=%d keys=%s", frames_received, sorted(observed_keys)[:40])
        raise CrealityGcodeError(
            "Creality did not return a recognised G-code file list in 8 seconds. "
            "Monitoring can still work when storage commands are unsupported by printer firmware. "
            "Diagnostic: %d JSON frames; response keys: %s." % (frames_received, ", ".join(sorted(observed_keys)[:12]) or "none")
        )
    return merged


def list_files(connection):
    try:
        return asyncio.run(_list_files(connection.endpoint_url))
    except CrealityGcodeError:
        raise
    except RuntimeError as exc:
        raise CrealityGcodeError("Creality file-browser event loop unavailable.") from exc


def _stock_data_root(connection):
    """Resolve verified native file root from the shared model capability table."""
    from .printer_storage_profiles import storage_profile
    printer = getattr(connection, "printer", None)
    model = " ".join((
        str(getattr(printer, "model", "") or ""),
        str(getattr(getattr(printer, "catalog_model", None), "name", "") or ""),
    ))
    profile = storage_profile("creality_local", model)
    if profile["strategy"] != "native_path" or profile["path"] is None:
        raise CrealityGcodeError(
            "Native print-start file location is not yet verified for this model. "
            "Use a supported printer API rather than guessing a filesystem path."
        )
    return profile["path"].removesuffix("/printer_data/gcodes/")


def _single_spool_command(remote_path, data_root):
    """Stock K1 no-CFS command, following the established Creality LAN API.

    The root is resolved from the explicitly recognised printer family. The
    self-test flag belongs to the CFS/multi-colour contract and is deliberately
    omitted from the ordinary K1 single-spool request.
    """
    if data_root not in ("/usr/data", "/mnt/UDISK"):
        raise CrealityGcodeError("Unrecognised native Creality storage root.")
    if not _safe_printer_file(remote_path) or _safe_printer_file(remote_path) != remote_path:
        raise CrealityGcodeError("Unsafe native print-start filename.")
    return {
        "method": "set",
        "params": {"opGcodeFile": "printprt:" + data_root + "/printer_data/gcodes/" + remote_path},
    }


async def _start_single_spool(endpoint, remote_path, data_root="/mnt/UDISK"):
    """Send exactly once; allow firmware to close its own WS session.

    K1 firmware can close its WebSocket immediately after receiving the start.
    An EOF or timeout while waiting for one best-effort reply must never cause
    a second dispatch or be interpreted as printer-side confirmation.
    """
    command = _single_spool_command(remote_path, data_root)
    try:
        # The stock K1 protocol is independent of the K2 CFS WebSocket flow.
        # Do not request the K2/slicer subprotocol for this one-shot command.
        async with websockets.connect(
            normalise_creality_endpoint(endpoint), ping_interval=None,
            open_timeout=5, close_timeout=1, proxy=None,
        ) as ws:
            await asyncio.wait_for(
                ws.send(json.dumps(command, separators=(",", ":"))), timeout=5
            )
            # A stock K1 may send a heartbeat or close the socket after print
            # dispatch. A bounded best-effort read prevents a close-frame burst.
            # Neither a heartbeat nor a WebSocket close confirms a print start.
            deadline = asyncio.get_running_loop().time() + 2
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except (asyncio.TimeoutError, WebSocketException, EOFError, OSError):
                    break
                try:
                    packet = json.loads(raw)
                except (TypeError, ValueError):
                    break
                if isinstance(packet, dict) and packet.get("ModeCode") == "heart_beat":
                    try:
                        await asyncio.wait_for(ws.send("ok"), timeout=max(
                            0.01, deadline - asyncio.get_running_loop().time()
                        ))
                    except (asyncio.TimeoutError, WebSocketException, EOFError, OSError):
                        break
                    continue
                break
    except (OSError, asyncio.TimeoutError, WebSocketException) as exc:
        raise CrealityGcodeError(
            "Creality single-spool print-start outcome is uncertain. Inspect the printer."
        ) from exc


def start_single_spool(connection, remote_path):
    safe = _safe_printer_file(remote_path)
    if not safe or safe != remote_path:
        raise CrealityGcodeError("Printer file path is unsafe or not recognized.")
    try:
        asyncio.run(_start_single_spool(connection.endpoint_url, safe, _stock_data_root(connection)))
    except CrealityGcodeError:
        raise
    except RuntimeError as exc:
        raise CrealityGcodeError("Creality print-start event loop unavailable.") from exc
    # Fire-and-forget protocol: sending does not prove acceptance.
    return None


async def _start_cfs_mapped(endpoint, remote_path, mapping):
    """Use the stock K2's established colorMatch -> multiColorPrint sequence.

    Sending these commands does not prove firmware acceptance. Callers must
    journal the result as unknown rather than claim a confirmed start.
    """
    gcode_path = "/mnt/UDISK/printer_data/gcodes/" + remote_path
    async with websockets.connect(
        normalise_creality_endpoint(endpoint), ping_interval=None,
        subprotocols=["wsslicer"], open_timeout=5, close_timeout=1, proxy=None
    ) as ws:
        command = {"method": "set", "params": {"colorMatch": {"path": gcode_path, "list": mapping}}}
        await asyncio.wait_for(ws.send(json.dumps(command, separators=(",", ":"))), timeout=5)
        # The documented proprietary API does not correlate acknowledgements.
        # No application-level retries are safe after this point.
        command = {"method": "set", "params": {"multiColorPrint": {
            "gcode": gcode_path, "enableSelfTest": 0,
        }}}
        await asyncio.wait_for(ws.send(json.dumps(command, separators=(",", ":"))), timeout=5)


def start_cfs_mapped(connection, remote_path, mapping):
    safe = _safe_printer_file(remote_path)
    if not safe or safe != remote_path or not isinstance(mapping, list) or not 1 <= len(mapping) <= 4:
        raise CrealityGcodeError("Invalid mapped K2 print request.")
    for item in mapping:
        if not isinstance(item, dict) or set(item) != {"id", "type", "color", "boxId", "materialId"}:
            raise CrealityGcodeError("Invalid CFS mapping entry.")
        if not re.fullmatch(r"T1[A-D]", str(item["id"])) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(item["color"])):
            raise CrealityGcodeError("Invalid sliced tool or filament colour.")
        if not isinstance(item["boxId"], int) or not 1 <= item["boxId"] <= 4 or not isinstance(item["materialId"], int) or not 0 <= item["materialId"] <= 3:
            raise CrealityGcodeError("Invalid CFS box or material slot.")
        if not re.fullmatch(r"[A-Za-z0-9+_-]{2,20}", str(item["type"])):
            raise CrealityGcodeError("Invalid CFS material type.")
    try:
        asyncio.run(_start_cfs_mapped(connection.endpoint_url, safe, mapping))
    except (OSError, asyncio.TimeoutError, WebSocketException, RuntimeError) as exc:
        raise CrealityGcodeError("K2 colour mapping/print-start outcome uncertain. Inspect the printer before attempting another job.") from exc
    return None
