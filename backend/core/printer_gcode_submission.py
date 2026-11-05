"""Opt-in Moonraker G-code browsing and one-shot upload/print submission.

No raw G-code execution via MakerVault. Each printer operation has a durable
receipt before I/O and is never automatically retried after an uncertain send.
Other printer adapters must implement and validate their own transfer protocol.
"""
import re
import logging
import uuid
from datetime import timedelta
from pathlib import PurePosixPath
from urllib.parse import quote
from requests.auth import HTTPDigestAuth

import requests
from django.db import transaction
from django.utils import timezone

from .gcode_analysis import MAX_SCAN_BYTES, analyse_text, compare_printer_metadata, inspect_asset
from .models import FileAsset, Printer, PrinterConnection, PrinterGcodeSubmission
from .printer_connectivity import normalise_moonraker_endpoint, normalise_printer_endpoint
from .manufacturer_printer_adapters import normalise_prusalink_endpoint
from .flashforge_gcode import FlashForgeFileError
from .creality_gcode import CrealityGcodeError

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 64 * 1024 * 1024
MOONRAKER_ADAPTERS = {"moonraker", "elegoo", "qidi", "sovol", "snapmaker", "voron"}
FILE_ADAPTERS = MOONRAKER_ADAPTERS | {"octoprint", "prusa"}
BROWSE_ADAPTERS = FILE_ADAPTERS | {"bambu_local", "flashforge", "creality_local"}
UPLOAD_ADAPTERS = FILE_ADAPTERS | {"flashforge", "creality_local"}
START_ADAPTERS = FILE_ADAPTERS | {"flashforge"}


class GcodeSubmissionError(RuntimeError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def _moonraker(connection):
    if connection.adapter not in MOONRAKER_ADAPTERS:
        raise GcodeSubmissionError(
            "The selected adapter does not expose a verified Moonraker file API.", 409
        )
    base = normalise_moonraker_endpoint(connection.endpoint_url)
    headers = {"Accept": "application/json"}
    key = str((connection.config or {}).get("api_key") or "").strip()
    if key:
        headers["X-Api-Key"] = key
    return base, headers


def _json_response(response):
    if not 200 <= response.status_code < 300:
        raise GcodeSubmissionError(
            f"Printer file service returned HTTP {response.status_code}; no command was accepted.", 502
        )
    try:
        result = response.json()
    except ValueError as exc:
        raise GcodeSubmissionError("Printer returned an invalid JSON response.", 502) from exc
    return result.get("result", result) if isinstance(result, dict) else result


def _get_json(connection, path, params=None):
    base, headers = _moonraker(connection)
    try:
        response = requests.get(base + path, params=params, headers=headers, timeout=(3, 12), allow_redirects=False)
    except requests.RequestException as exc:
        raise GcodeSubmissionError("Printer file listing is unavailable. Check the connection.", 502) from exc
    return _json_response(response)


def _moonraker_gcode_files(connection):
    """Query a compatible Moonraker API; no filesystem assumptions."""
    rows = _get_json(connection, "/server/files/list", {"root": "gcodes"})
    if not isinstance(rows, list):
        raise GcodeSubmissionError("Printer file list has an unexpected format.", 502)
    result = []
    for item in rows[:5000]:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        if not isinstance(path, str) or not path.lower().endswith((".gcode", ".gco")) or not _valid_path(path):
            continue
        result.append({
            "path": path,
            "size_bytes": item.get("size") if type(item.get("size")) is int and item["size"] >= 0 else None,
            "modified": item.get("modified"),
            "permissions": item.get("permissions") or "",
        })
    return result


def _creality_native_gcode_files(connection):
    from .creality_gcode import CrealityGcodeError, list_files
    try:
        return list_files(connection)
    except CrealityGcodeError as exc:
        raise GcodeSubmissionError(str(exc), 409) from exc


def _bambu_gcode_files(connection):
    from .bambu_storage import BambuStorageError, list_bambu_storage
    try:
        return list_bambu_storage(connection)
    except BambuStorageError as exc:
        raise GcodeSubmissionError(str(exc), 409) from exc


def _flashforge_gcode_files(connection):
    from .flashforge_gcode import FlashForgeFileError, list_files
    try:
        return list_files(connection)
    except FlashForgeFileError as exc:
        raise GcodeSubmissionError(str(exc), 502) from exc


def _listing_handler(adapter):
    """Return the explicit, implemented file API for this connection type.

    Several manufacturer-branded adapters expose Moonraker's API; this is a
    capability mapping, not a guess based on a printer name or IP address.
    """
    if adapter in MOONRAKER_ADAPTERS:
        return _moonraker_gcode_files
    return {
        "creality_local": _creality_native_gcode_files,
        "bambu_local": _bambu_gcode_files,
        "flashforge": _flashforge_gcode_files,
        "octoprint": _octoprint_files,
        "prusa": _prusalink_files,
    }.get(adapter)


def _listing_candidates(connection):
    """Enumerate verified file interfaces for this *same* physical printer.

    A manually configured generic connection is optional. Its failure must
    not suppress a working manufacturer-native file browser. Never try an
    endpoint belonging to another printer or invent an HTTP path.
    """
    handler = _listing_handler(connection.adapter)
    if handler is None:
        raise GcodeSubmissionError("This printer connection has no supported file listing protocol.", 409)
    candidates = []
    if connection.adapter == "creality_local" and getattr(connection, "printer_id", None):
        alternatives = PrinterConnection.objects.filter(
            printer_id=connection.printer_id, adapter="moonraker", enabled=True,
        ).order_by("-last_seen_at")
        for alternative in alternatives:
            if _online(alternative):
                candidates.append((alternative, _moonraker_gcode_files))
    candidates.append((connection, handler))
    return candidates


def list_printer_gcodes(connection):
    """Standard provider-neutral file list with adapter-specific discovery.

    Fail over only on a protocol failure, not on a legitimate empty list.
    All candidates are explicitly configured connections for this printer.
    Read-only calls never upload, start prints or modify printer storage.
    """
    errors = []
    for candidate, browse in _listing_candidates(connection):
        try:
            return browse(candidate)
        except GcodeSubmissionError as exc:
            errors.append(str(exc))
            logger.warning("Printer file listing via %s failed; trying next configured interface", candidate.adapter)
    if errors:
        # Avoid exposing credentials or private URLs from remote errors.
        raise GcodeSubmissionError(
            "No configured printer file-listing interface succeeded. "
            + " | ".join(errors[:2]), 502
        )
    raise GcodeSubmissionError("No available printer file-listing interface.", 409)


def _printer_endpoint(connection):
    if connection.adapter == "octoprint":
        base = normalise_printer_endpoint(connection.endpoint_url)
        headers = {"Accept": "application/json"}
        key = str((connection.config or {}).get("api_key") or "").strip()
        if key:
            headers["X-Api-Key"] = key
        return base, headers
    if connection.adapter == "prusa":
        base = normalise_prusalink_endpoint(connection.endpoint_url)
        headers = {"Accept": "application/json"}
        key = str((connection.config or {}).get("api_key") or "").strip()
        if key:
            headers["X-Api-Key"] = key
        return base, headers
    return _moonraker(connection)


def _prusa_auth(connection):
    if connection.adapter != "prusa":
        return None
    config = connection.config or {}
    username = str(config.get("username") or "")
    password = str(config.get("password") or "")
    return HTTPDigestAuth(username, password) if username or password else None


def _prusalink_capability_probe(connection, *, upload):
    """Read PrusaLink's advertised API capabilities; never assume an old API."""
    base, headers = _printer_endpoint(connection)
    auth = _prusa_auth(connection)
    try:
        version = requests.get(
            base + "/api/version", headers=headers, auth=auth,
            timeout=(3, 10), allow_redirects=False,
        )
        storage = requests.get(
            base + "/api/v1/storage", headers=headers, auth=auth,
            timeout=(3, 10), allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise GcodeSubmissionError("Cannot check PrusaLink firmware storage capabilities.", 502) from exc
    if version.status_code != 200 or storage.status_code != 200:
        raise GcodeSubmissionError("PrusaLink version or storage capability query failed; transfer disabled.")
    try:
        v = version.json()
        st = storage.json()
    except ValueError as exc:
        raise GcodeSubmissionError("PrusaLink returned invalid capability metadata.", 502) from exc
    supported_storage = any(
        isinstance(entry, dict) and entry.get("type") == "LOCAL"
        and entry.get("available") is True
        and (not upload or entry.get("read_only") is False)
        for entry in (st.get("storage_list") or [])
    ) if isinstance(st, dict) else False
    if not supported_storage:
        raise GcodeSubmissionError("PrusaLink has no compatible available local storage.")
    if upload and (not isinstance(v, dict) or
                   (v.get("capabilities") or {}).get("upload-by-put") is not True):
        raise GcodeSubmissionError("This PrusaLink firmware does not advertise safe PUT uploads.")
    return True


def _prusalink_files(connection):
    """Experimental: modern PrusaLink v1 API; no undocumented fallback."""
    base, headers = _printer_endpoint(connection)
    try:
        response = requests.get(
            base + "/api/v1/files/local/", headers=headers, auth=_prusa_auth(connection),
            timeout=(3, 12), allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise GcodeSubmissionError("PrusaLink file directory is unavailable.", 502) from exc
    if response.status_code != 200:
        raise GcodeSubmissionError(
            "This PrusaLink firmware did not provide a compatible local file listing (HTTP %s)." % response.status_code, 502
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise GcodeSubmissionError("PrusaLink returned invalid directory metadata.", 502) from exc
    children = data.get("children") if isinstance(data, dict) else None
    if not isinstance(children, list):
        raise GcodeSubmissionError("PrusaLink file listing format is not yet supported for this model.", 502)
    results = []
    def walk(nodes, prefix=""):
        for item in nodes:
            if len(results) >= 5000:
                break
            if not isinstance(item, dict):
                continue
            filename = item.get("display_name") or item.get("name")
            if not isinstance(filename, str) or "/" in filename or "\\" in filename:
                continue
            path = prefix + filename
            if item.get("type") == "FOLDER":
                walk(item.get("children") or [], path + "/")
            elif _valid_path(path):
                results.append({
                    "path": path, "size_bytes": item.get("size"),
                    "modified": item.get("m_timestamp"), "permissions": "r" if item.get("read_only") else "rw",
                })
    walk(children)
    return results


def _octoprint_files(connection):
    base, headers = _printer_endpoint(connection)
    try:
        response = requests.get(base + "/api/files/local", params={"recursive": "true"}, headers=headers, timeout=(3, 15), allow_redirects=False)
    except requests.RequestException as exc:
        raise GcodeSubmissionError("OctoPrint file listing unavailable.", 502) from exc
    if response.status_code != 200:
        raise GcodeSubmissionError(f"OctoPrint refused file listing (HTTP {response.status_code}).", 502)
    try:
        payload = response.json()
    except ValueError as exc:
        raise GcodeSubmissionError("OctoPrint returned invalid file list data.", 502) from exc
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, list):
        raise GcodeSubmissionError("OctoPrint file response is not recognised.", 502)
    result = []
    def walk(items, prefix=""):
        for item in items:
            if len(result) >= 5000:
                break
            if not isinstance(item, dict):
                continue
            path = item.get("path") or (prefix + str(item.get("name") or ""))
            if item.get("type") == "folder":
                walk(item.get("children") or [], str(path).rstrip("/") + "/")
            elif isinstance(path, str) and _valid_path(path):
                result.append({"path": path, "size_bytes": item.get("size"), "modified": item.get("date"), "permissions": "rw"})
    walk(files)
    return result


def _octoprint_upload_receipt(response):
    if response.status_code != 201:
        raise GcodeSubmissionError(f"OctoPrint did not accept upload (HTTP {response.status_code}).", 502)
    try:
        result = response.json()
    except ValueError as exc:
        raise GcodeSubmissionError("OctoPrint returned invalid upload data.", 502) from exc
    return result if isinstance(result, dict) else {}


def _valid_path(value):
    return (
        isinstance(value, str)
        and 0 < len(value) <= 500
        and value.lower().endswith((".gcode", ".gco"))
        and "\x00" not in value
        and "\\" not in value
        and not value.startswith("/")
        and all(part not in {"", ".", ".."} for part in value.split("/"))
    )


def _verify_moonraker_upload(connection, remote_path, expected_size):
    """Confirm G-code appears in printer storage at the expected byte count."""
    match = next((item for item in list_printer_gcodes(connection) if item["path"] == remote_path), None)
    if not match:
        raise GcodeSubmissionError(
            "Moonraker accepted upload but the file is absent from printer storage. "
            "Inspect the printer before retrying.", 502)
    if match.get("size_bytes") is None or int(match["size_bytes"]) != int(expected_size):
        raise GcodeSubmissionError(
            "Uploaded G-code cannot be verified: printer file size missing or mismatched. "
            "The print must not be started.", 502)
    return match


def _verify_creality_upload(connection, remote_path, expected_size):
    """Verify native HTTP-upload presence through an enabled Moonraker source
    on the SAME printer. This never uploads or starts via the alternate source.
    """
    moonraker_sources = PrinterConnection.objects.filter(
        printer_id=connection.printer_id, adapter="moonraker", enabled=True,
    ).order_by("-last_seen_at")
    for source in moonraker_sources:
        if _online(source):
            return _verify_moonraker_upload(source, remote_path, expected_size)
    raise GcodeSubmissionError(
        "Native Creality HTTP upload was attempted, but no fresh Moonraker storage "
        "connection is available to verify the file. Inspect printer storage before retrying.", 502
    )


def inspect_printer_file(connection, remote_path):
    """Optional, bounded, read-only G-code inspection over an existing Moonraker API.

    Does not require Moonraker for the native Creality adapter generally. No
    other printer protocols are assumed capable of returning file contents.
    """
    if not _valid_path(remote_path):
        raise GcodeSubmissionError("Invalid printer file path.", 400)
    source = (_same_printer_moonraker(connection) if connection.adapter == "creality_local"
              else connection if connection.adapter in MOONRAKER_ADAPTERS else None)
    if source is None or not _online(source):
        raise GcodeSubmissionError("Read-only file inspection is not available through this printer connection.", 409)
    match = next((item for item in list_printer_gcodes(source) if item["path"] == remote_path), None)
    if not match:
        raise GcodeSubmissionError("The selected file is no longer available on the printer.", 404)
    size = match.get("size_bytes")
    if type(size) is not int or size < 0 or size > MAX_SCAN_BYTES:
        raise GcodeSubmissionError("This printer file cannot be fully inspected within the 32 MiB analysis limit.", 409)
    base, headers = _moonraker(source)
    try:
        with requests.get(
            base + "/server/files/gcodes/" + quote(remote_path, safe="/"),
            headers=headers, timeout=(3, 25), stream=True, allow_redirects=False,
        ) as response:
            if response.status_code != 200:
                raise GcodeSubmissionError("Printer did not return the requested G-code for inspection.", 502)
            data = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                data.extend(chunk)
                if len(data) > MAX_SCAN_BYTES or len(data) > size:
                    raise GcodeSubmissionError("Printer file exceeded its declared size or analysis limit.", 409)
    except requests.RequestException as exc:
        raise GcodeSubmissionError("The printer G-code could not be read for inspection.", 502) from exc
    if len(data) != size or b"\\x00" in data[:262144]:
        raise GcodeSubmissionError("Printer G-code is incomplete or not plain text.", 409)
    return analyse_text(data.decode("utf-8", errors="replace"))


def _metadata(connection, path):
    if connection.adapter in {"octoprint", "prusa", "flashforge"}:
        return {}  # Printer storage filenames alone are not verified slicer profiles.
    if connection.adapter == "creality_local":
        connection = _same_printer_moonraker(connection)
        if connection is None:
            return {}
    try:
        result = _get_json(connection, "/server/files/metadata", {"filename": path})
        return result if isinstance(result, dict) else {}
    except GcodeSubmissionError:
        # Metadata may not have been generated by the printer; a user must then
        # acknowledge unknown compatibility. Never call this a confirmed match.
        return {}


def _online(connection):
    snap = connection.last_snapshot or {}
    return (
        connection.enabled and connection.status == "connected"
        and connection.last_seen_at
        and connection.last_seen_at >= timezone.now() - timedelta(seconds=60)
        and snap.get("online") is True
    )


def creality_cfs_context(connection):
    """Share the same owner's fresh native Creality CFS snapshot with every transport.

    A Moonraker source must not bypass CFS safety simply because Moonraker does
    not report the filament changer. Unknown or stale native state fails closed
    for CFS-equipped K2 printers, without restricting upload-only operations.
    """
    printer = getattr(connection, "printer", None)
    model_name = str(getattr(printer, "model", "") or "")
    manufacturer = str(getattr(printer, "manufacturer", "") or "")
    catalog = getattr(printer, "catalog_model", None)
    if catalog:
        model_name += " " + str(getattr(catalog, "name", "") or "")
    if not ("creality" in manufacturer.lower() or connection.adapter == "creality_local" or "k2" in model_name.lower()):
        return {"applicable": False, "connected": False, "verified": False, "slots": []}
    if not any(word in model_name.lower() for word in ("k2", "k1")):
        return {"applicable": False, "connected": False, "verified": False, "slots": []}
    sources = ([connection] if connection.adapter == "creality_local" else
               list(PrinterConnection.objects.filter(
                   printer_id=connection.printer_id, adapter="creality_local", enabled=True
               ).order_by("-last_seen_at")))
    if not sources:
        return {"applicable": True, "connected": None, "verified": False, "slots": [],
                "reason": "No native Creality source is configured to verify CFS state."}
    source = sources[0]
    snap = source.last_snapshot or {}
    metadata = snap.get("source_metadata") or {}
    fresh = bool(source.status == "connected" and source.last_seen_at and
                 source.last_seen_at >= timezone.now() - timedelta(seconds=60)
                 and snap.get("online") is True)
    connected = metadata.get("cfs_connected") if fresh and isinstance(metadata.get("cfs_connected"), bool) else None
    raw = snap.get("materials") or []
    slots = []
    if connected is True:
        for material in raw:
            if not isinstance(material, dict) or material.get("system") != "creality_cfs":
                continue
            try:
                box = int(material["unit_index"]) + 1
                slot = int(material["slot_index"])
            except (ValueError, TypeError, KeyError):
                continue
            if not 1 <= box <= 4 or not 0 <= slot <= 3:
                continue
            slots.append({
                "box_id": box, "slot_id": slot,
                "label": f"{box}{'ABCD'[slot]}",
                "material": str(material.get("material") or "")[:80],
                "product_name": str(material.get("product_name") or "")[:120],
                "vendor": str(material.get("vendor") or "")[:80],
                "color_hex": str(material.get("color_hex") or "")[:24],
                "selected": material.get("selected") is True,
            })
    return {
        "applicable": True, "connected": connected, "verified": fresh,
        "slots": slots,
        "reason": ("CFS state is not fresh or is unavailable." if not fresh else
                   "CFS filament mapping is not yet validated for remote print-start." if connected else
                   "No CFS detected in fresh native telemetry."),
    }


def _is_k2(connection):
    printer = getattr(connection, "printer", None)
    model = " ".join((str(getattr(printer, "model", "") or ""),
                      str(getattr(getattr(printer, "catalog_model", None), "name", "") or "")))
    return bool(re.search(r"\bK2(?:\b|$)", model.upper()))


def _mapped_cfs_entries(connection, requirements, requested):
    """Build validated tool-to-slot mappings from current native CFS telemetry."""
    context = creality_cfs_context(connection)
    if not _is_k2(connection):
        raise GcodeSubmissionError("Native CFS slot mapping currently supports K2 models only.", 409)
    if not context["verified"] or context["connected"] is not True:
        raise GcodeSubmissionError("Fresh CFS slot information is required before mapping.", 409)
    if not isinstance(requirements, list) or not 1 <= len(requirements) <= 4:
        raise GcodeSubmissionError("G-code must declare one to four material types for CFS mapping.", 409)
    if not isinstance(requested, list) or len(requested) != len(requirements):
        raise GcodeSubmissionError("Select a CFS slot for each sliced filament.", 400)
    selections = {}
    for item in requested:
        if not isinstance(item, dict) or type(item.get("tool_index")) is not int or not isinstance(item.get("slot_label"), str):
            raise GcodeSubmissionError("Invalid CFS mapping.", 400)
        index = item["tool_index"]
        valid_tools = {int(req["tool_index"]) for req in requirements if isinstance(req, dict) and type(req.get("tool_index")) is int}
        if index in selections or index not in valid_tools:
            raise GcodeSubmissionError("Duplicate or invalid slicer tool index.", 400)
        selections[index] = item["slot_label"]
    slots = {slot["label"]: slot for slot in context["slots"]}
    mapping = []
    for requirement in requirements:
        index = int(requirement["tool_index"])
        selected = slots.get(selections.get(index))
        material = str(requirement.get("material") or "").strip().upper()
        if not selected or not material:
            raise GcodeSubmissionError("Sliced material and chosen CFS slot must both be known.", 409)
        actual = str(selected.get("material") or "").strip().upper()
        if material != actual:
            raise GcodeSubmissionError("Material mismatch for slot " + selected["label"] + " (G-code: " + material + ", CFS: " + actual + ").", 409)
        colour = str(selected.get("color_hex") or "")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", colour):
            raise GcodeSubmissionError("Selected CFS slot colour is unreadable.", 409)
        if not 0 <= index <= 3:
            raise GcodeSubmissionError("This K2 mapping supports slicer tools 0–3 only.", 409)
        mapping.append({"id": "T1" + "ABCD"[index], "type": actual, "color": colour,
                        "boxId": selected["box_id"], "materialId": selected["slot_id"]})
    return mapping


def _printer_transfer_name(original_name, request_id):
    """Preserve the original name first, suffix with a stable job identity."""
    original = PurePosixPath(str(original_name or "job.gcode")).name
    stem = re.sub(r"[^A-Za-z0-9_.-]", "_", re.sub(r"(?i)\.gcode$", "", original))
    stem = stem.strip("._")[:120] or "job"
    return f"{stem}-mv-{request_id.hex[:12]}.gcode"


def _ready_for_start(snapshot):
    # Moonraker/Creality may retain a terminal print_stats state after
    # completion/cancellation until the next job. Never admit active states.
    state = str((snapshot or {}).get("state") or "").lower()
    return state in {"idle", "complete", "cancelled"}


def _same_printer_moonraker(connection, *, require_controls=False):
    printer_id = getattr(connection, "printer_id", None)
    if printer_id is None:
        return None
    sources = PrinterConnection.objects.filter(
        printer_id=printer_id, adapter="moonraker", enabled=True,
    ).order_by("-last_seen_at")
    for source in sources:
        if _online(source) and (not require_controls or source.controls_enabled):
            return source
    return None


def availability(connection):
    adapter = connection.adapter
    # Native transports are opt-in at the final submission confirmation, not
    # via experiment switches. Other control adapters retain their existing
    # connection-level permission setting.
    authorised = bool(connection.enabled and (
        connection.controls_enabled or adapter in {"creality_local", "prusa", "flashforge"}
    ))
    from .flashforge_gcode import supports_simple_print
    simple_flashforge = adapter == "flashforge" and bool(getattr(connection, "printer", None)) and supports_simple_print(connection.printer)
    upload_supported = adapter in FILE_ADAPTERS or adapter == "creality_local" or simple_flashforge
    start_supported = adapter in FILE_ADAPTERS or simple_flashforge or adapter == "creality_local"
    online = bool(_online(connection))
    cfs = creality_cfs_context(connection)
    cfs_blocks_start = bool(cfs["applicable"] and (cfs["connected"] is not False or not cfs["verified"]))
    # Moonraker can run the original, slicer-embedded CFS mapping without
    # changing any slots. It cannot apply a MakerVault-selected override.
    mapped_mapping_candidate = bool(
        _is_k2(connection) and adapter in {"moonraker", "creality_local"} and online and authorised
        and cfs["applicable"] and cfs["verified"] and cfs["connected"] is True
        and cfs["slots"] and _ready_for_start(connection.last_snapshot)
        and not (connection.last_snapshot or {}).get("source_metadata", {}).get("power_loss_recovery")
    )
    moonraker_for_sliced = (connection if adapter == "moonraker" else
                             _same_printer_moonraker(connection, require_controls=True)
                             if adapter == "creality_local" and cfs["applicable"] and cfs["connected"] is True else None)
    # Capability and instantaneous readiness are separate: the UI should
    # not make a supported original-mapping option disappear while printing.
    supports_original_mapping = bool(
        adapter == "moonraker" or (
            adapter == "creality_local" and
            getattr(connection, "printer_id", None) is not None and
            PrinterConnection.objects.filter(
                printer_id=connection.printer_id, adapter="moonraker",
                enabled=True, controls_enabled=True,
            ).exists()
        )
    )
    supports_original_mapping = bool(
        supports_original_mapping and cfs["applicable"] and cfs["connected"] is True
    )
    sliced_mapping_candidate = bool(
        moonraker_for_sliced is not None and online and authorised
        and cfs["applicable"] and cfs["verified"] and cfs["connected"] is True
        and cfs["slots"] and _ready_for_start(connection.last_snapshot)
        and _ready_for_start(moonraker_for_sliced.last_snapshot)
        and not (connection.last_snapshot or {}).get("source_metadata", {}).get("power_loss_recovery")
    )
    return {
        "can_browse": adapter in BROWSE_ADAPTERS,
        "browse_requires_pin": adapter == "bambu_local" and not bool((connection.config or {}).get("bambu_ftps_cert_sha256")),
        "experimental": adapter in (BROWSE_ADAPTERS | UPLOAD_ADAPTERS),
        "supported": upload_supported or start_supported,
        "online": online,
        "can_upload": bool(upload_supported and online and authorised),
        "can_start": bool(
            start_supported and online and authorised and not cfs_blocks_start
            
            and (adapter != "creality_local" or not (connection.last_snapshot or {}).get("source_metadata", {}).get("cfs_connected"))
            and _ready_for_start(connection.last_snapshot)
            and not (connection.last_snapshot or {}).get("source_metadata", {}).get("power_loss_recovery")
        ),
        "enabled": authorised,
        "cfs": cfs,
        "supports_original_mapping": supports_original_mapping,
        "can_start_sliced_mapping": sliced_mapping_candidate,
        "can_start_mapped_cfs": mapped_mapping_candidate,
        "can_submit_from_printer": adapter in BROWSE_ADAPTERS and start_supported,
        "requires_opt_in": False,
        "requires_start_opt_in": False,
    }


def _require_action_ready(connection, action, *, use_sliced_cfs=False, use_mapped_cfs=False):
    state = availability(connection)
    if not state["supported"]:
        raise GcodeSubmissionError("This printer adapter does not support G-code submission yet.")
    if not state["online"] or not state["enabled"]:
        raise GcodeSubmissionError("Explicitly enable printer G-code submission and refresh an online connection first.")
    if use_mapped_cfs and not state["can_start_mapped_cfs"]:
        raise GcodeSubmissionError("Mapped K2 printing requires current CFS telemetry and an idle printer.", 409)
    if use_sliced_cfs and not state["can_start_sliced_mapping"]:
        raise GcodeSubmissionError("Original sliced CFS mapping is available only for a fresh, idle Creality K2 through Moonraker.", 409)
    if action == "upload" and not state["can_upload"]:
        raise GcodeSubmissionError("G-code upload is not supported for this printer.")
    if action == "print" and not (state["can_start"] or (use_sliced_cfs and state["can_start_sliced_mapping"]) or (use_mapped_cfs and state["can_start_mapped_cfs"])):
        raise GcodeSubmissionError("Printer must be freshly verified idle with a supported CFS print mode before starting a job.")


def _receipt(row):
    return {
        "request_id": str(row.pk), "status": row.status,
        "action": row.action, "source": row.source,
        "remote_path": row.remote_path, "message": row.message,
    }


def submit(connection, user, payload):
    if not isinstance(payload, dict):
        raise GcodeSubmissionError("Submission must be a JSON object.", 400)
    if payload.get("confirmed") is not True:
        raise GcodeSubmissionError("Confirm the selected printer, file and upload/print action.", 400)
    source, action = payload.get("source"), payload.get("action")
    use_sliced_cfs = payload.get("cfs_mode") == "use_sliced"
    use_mapped_cfs = payload.get("cfs_mode") == "mapped"
    if use_mapped_cfs and action != "print":
        raise GcodeSubmissionError("Mapped CFS starts require an explicit print action.", 400)
    if payload.get("cfs_mode") not in (None, "", "use_sliced", "mapped"):
        raise GcodeSubmissionError("Unsupported CFS print mode.", 400)
    if use_sliced_cfs and (action != "print" or payload.get("cfs_acknowledged") is not True):
        raise GcodeSubmissionError("Explicitly confirm the K2's loaded filaments and the slicer's existing CFS mapping.", 400)
    if use_sliced_cfs and payload.get("cfs_slot_overrides"):
        raise GcodeSubmissionError("CFS slot overrides are not supported by this print path.", 400)
    if source not in {"printer", "makervault"} or action not in {"upload", "print"}:
        raise GcodeSubmissionError("Choose printer or MakerVault G-code and upload or print.", 400)
    if source == "printer" and action != "print":
        raise GcodeSubmissionError("An existing printer file is already uploaded.", 400)
    try:
        request_id = uuid.UUID(str(payload.get("request_id") or ""))
    except (TypeError, ValueError, AttributeError) as exc:
        raise GcodeSubmissionError("A unique submission ID is required.", 400) from exc

    asset = None
    remote_path = str(payload.get("printer_path") or "").strip() if source == "printer" else ""
    if source == "printer" and not _valid_path(remote_path):
        raise GcodeSubmissionError("Select a valid printer G-code file.", 400)
    if source == "makervault":
        try:
            aid = uuid.UUID(str(payload.get("file_asset_id") or ""))
        except (TypeError, ValueError, AttributeError) as exc:
            raise GcodeSubmissionError("Select a valid MakerVault G-code file.", 400) from exc
        asset = FileAsset.objects.filter(owner=user, pk=aid, superseded_by__isnull=True).first()
        if not asset or (asset.metadata or {}).get("extension") != ".gcode":
            raise GcodeSubmissionError("Select an owned, current plain-text G-code file.", 404)
        if asset.file.size > MAX_UPLOAD_BYTES:
            raise GcodeSubmissionError("This release supports printer transfers up to 64 MiB. Large files require the streaming transport.", 413)
        # Keep the original filename recognisable; suffix avoids overwrites.
        remote_path = _printer_transfer_name((asset.metadata or {}).get("original_name"), request_id)

    # A repeated request ID is a status lookup, NEVER a second dispatch.
    with transaction.atomic():
        Printer.objects.select_for_update().get(pk=connection.printer_id)
        old = PrinterGcodeSubmission.objects.filter(pk=request_id).first()
        if old:
            if old.connection_id != connection.pk or old.requested_by_id != user.pk or old.action != action or old.source != source or old.remote_path != remote_path or old.file_asset_id != (asset.pk if asset else None):
                raise GcodeSubmissionError("Submission ID was already used for a different operation.")
            return _receipt(old)
        connection.refresh_from_db()
        _require_action_ready(connection, action, use_sliced_cfs=use_sliced_cfs, use_mapped_cfs=use_mapped_cfs)
        recent = PrinterGcodeSubmission.objects.filter(connection__printer_id=connection.printer_id)
        if recent.filter(status__in=["pending", "unknown"], created_at__gte=timezone.now() - timedelta(minutes=10)).exists():
            raise GcodeSubmissionError("An earlier submission has an unresolved outcome. Verify printer state before another request.")
        row = PrinterGcodeSubmission.objects.create(
            id=request_id, connection=connection, requested_by=user, file_asset=asset,
            source=source, action=action, original_path=remote_path if source == "printer" else "",
            remote_path=remote_path, file_sha256=(asset.sha256 if asset else ""),
        )

    mapping_entries = None
    stage = "Preparing submission"
    dispatch_attempted = False

    def progress(message):
        nonlocal stage
        stage = message
        row.message = message
        row.save(update_fields=["message", "updated_at"])

    try:
        progress("Checking file metadata and printer compatibility.")
        # All commands occur after the receipt is committed. Never auto-retry an
        # upload or print command with unknown delivery status.
        _require_action_ready(connection, action, use_sliced_cfs=use_sliced_cfs, use_mapped_cfs=use_mapped_cfs)
        if source == "printer":
            if connection.adapter == "creality_local" and not (use_sliced_cfs or use_mapped_cfs) and (connection.last_snapshot or {}).get("source_metadata", {}).get("cfs_connected"):
                raise GcodeSubmissionError("Creality CFS is connected: single-spool start is blocked pending material mapping.")
            if remote_path not in {f["path"] for f in list_printer_gcodes(connection)}:
                raise GcodeSubmissionError("Printer file no longer exists. Refresh the printer file list.")
            meta = _metadata(connection, remote_path)
            report = (inspect_printer_file(connection, remote_path) if use_mapped_cfs else
                      {"printer_hints": [meta["printer_model"]] if meta.get("printer_model") else []})
        else:
            analysis = inspect_asset(asset)["analysis"]
            report = analysis
        if use_mapped_cfs and not (report.get("filaments") or {}).get("usage_confident"):
            raise GcodeSubmissionError("Cannot reliably identify which filaments are actually printed. Use the original slicer mapping or upload only.", 409)
        if use_mapped_cfs:
            mapping_entries = _mapped_cfs_entries(connection, (report.get("filaments") or {}).get("used_requirements"), payload.get("cfs_mapping"))
        verdict = compare_printer_metadata(report, connection.printer)
        if verdict["status"] == "mismatch":
            raise GcodeSubmissionError(verdict["reason"])
        if connection.adapter == "creality_local" and action == "print" and not use_mapped_cfs and not use_sliced_cfs:
            if (connection.last_snapshot or {}).get("source_metadata", {}).get("cfs_connected"):
                raise GcodeSubmissionError("CFS is connected. Native start requires validated material-slot mapping.")
            if remote_path not in {item["path"] for item in list_printer_gcodes(connection)} and source == "printer":
                raise GcodeSubmissionError("Selected Creality file is no longer present.")
        if source == "makervault" and (report.get("partial") or any("firmware/control commands" in str(w) for w in report.get("warnings", []))):
            raise GcodeSubmissionError("File is too large for complete analysis or contains flagged firmware-control commands. Printer submission blocked.")
        if verdict["blocking"] and payload.get("acknowledge_unknown") is not True:
            raise GcodeSubmissionError("Printer compatibility is unknown. Review the file and explicitly acknowledge the risk.", 409)

        progress("Rechecking live printer state before transfer.")
        # Re-poll immediately before irreversible I/O; this prevents stale
        # monitoring data from authorizing a print while already busy.
        from .printer_connectivity import poll_connection
        try:
            poll_connection(connection)
        except Exception as exc:
            raise GcodeSubmissionError("Unable to verify fresh printer status before transfer. No command dispatched.", 409) from exc
        connection.refresh_from_db()
        _require_action_ready(connection, action, use_sliced_cfs=use_sliced_cfs, use_mapped_cfs=use_mapped_cfs)
        if use_mapped_cfs:
            mapping_entries = _mapped_cfs_entries(connection, (report.get("filaments") or {}).get("used_requirements"), payload.get("cfs_mapping"))
        base, headers = (None, None) if connection.adapter in {"flashforge", "creality_local"} else _printer_endpoint(connection)
        if connection.adapter == "prusa":
            _prusalink_capability_probe(connection, upload=(source == "makervault"))
        if source == "makervault":
            progress("Transferring G-code to printer; byte progress is not available.")
            try:
                with asset.file.storage.open(asset.file.name, "rb") as handle:
                    if connection.adapter == "flashforge":
                        dispatch_attempted = True
                        from .flashforge_gcode import upload_file
                        upload_file(connection, asset, remote_path)
                        response = None
                    elif connection.adapter == "creality_local":
                        dispatch_attempted = True
                        from .creality_gcode import upload_only
                        upload_only(connection, asset, remote_path)
                        response = None
                    elif connection.adapter == "prusa":
                        dispatch_attempted = True
                        response = requests.put(
                            base + "/api/v1/files/local/" + quote(remote_path, safe="/"),
                            data=handle,
                            headers={**headers, "Content-Type": "application/octet-stream", "Content-Length": str(asset.file.size), "Print-After-Upload": "?0", "Overwrite": "?0"},
                            auth=_prusa_auth(connection), timeout=(5, 120), allow_redirects=False,
                        )
                    else:
                        dispatch_attempted = True
                        response = requests.post(
                            base + ("/api/files/local" if connection.adapter == "octoprint" else "/server/files/upload"),
                            data=({"select": "false", "print": "false"} if connection.adapter == "octoprint" else {"root": "gcodes", "print": "false", "checksum": asset.sha256}),
                            files={"file": (remote_path, handle, "application/octet-stream")},
                            headers=headers, timeout=(5, 120), allow_redirects=False,
                        )
            except requests.RequestException as exc:
                raise GcodeSubmissionError("Upload outcome is uncertain. Inspect printer storage before trying again.", 502) from exc
            if connection.adapter in {"flashforge", "creality_local"}:
                result = {"item": {"path": remote_path}}
            elif connection.adapter == "prusa":
                if response.status_code != 201:
                    raise GcodeSubmissionError("PrusaLink rejected upload (HTTP %s). Check printer storage." % response.status_code, 502)
                if remote_path not in {file["path"] for file in list_printer_gcodes(connection)}:
                    raise GcodeSubmissionError("PrusaLink did not report the uploaded file. Refresh storage before printing.", 502)
                result = {"item": {"path": remote_path}}
            else:
                result = _octoprint_upload_receipt(response) if connection.adapter == "octoprint" else _json_response(response)
            uploaded_path = ((result.get("files") or {}).get("local") or {}).get("path") if connection.adapter == "octoprint" else (result.get("item") or {}).get("path")
            if not isinstance(result, dict) or uploaded_path != remote_path or result.get("print_started") or result.get("print_queued") or result.get("effectivePrint"):
                raise GcodeSubmissionError("Printer did not confirm upload-only completion. Verify printer state.", 502)
            if connection.adapter in MOONRAKER_ADAPTERS:
                progress("Checking uploaded filename and file size against printer storage.")
                _verify_moonraker_upload(connection, remote_path, asset.file.size)
            elif connection.adapter == "creality_local":
                progress("Native Creality HTTP accepted the transfer. Checking printer storage.")
                _verify_creality_upload(connection, remote_path, asset.file.size)
        if action == "print":
            progress("Upload checked. Confirming printer idle before print-start.")
            # Verify state a second time after file transfer, particularly when
            # the upload took long enough for printer state to change.
            try:
                poll_connection(connection)
            except Exception as exc:
                raise GcodeSubmissionError("Unable to confirm printer is still idle after file upload. Do not start.", 409) from exc
            connection.refresh_from_db()
            _require_action_ready(connection, "print", use_sliced_cfs=use_sliced_cfs, use_mapped_cfs=use_mapped_cfs)
            mapped_native_connection = None
            if use_mapped_cfs:
                mapped_native_connection = connection if connection.adapter == "creality_local" else PrinterConnection.objects.filter(
                    printer_id=connection.printer_id, adapter="creality_local", enabled=True,
                ).order_by("-last_seen_at").first()
                if mapped_native_connection is None:
                    raise GcodeSubmissionError("Native Creality connection is required to check live CFS slots.", 409)
                try:
                    poll_connection(mapped_native_connection)
                except Exception as exc:
                    raise GcodeSubmissionError("Unable to refresh live CFS slots before mapping. No start sent.", 409) from exc
                mapped_native_connection.refresh_from_db()
                if connection.adapter == "creality_local":
                    connection.refresh_from_db()
                mapping_entries = _mapped_cfs_entries(connection, (report.get("filaments") or {}).get("used_requirements"), payload.get("cfs_mapping"))
            progress("Sending the explicitly confirmed print-start command.")
            dispatch_attempted = True
            try:
                if use_mapped_cfs:
                    from .creality_gcode import start_cfs_mapped
                    if not _online(mapped_native_connection):
                        raise GcodeSubmissionError("Native Creality status was lost before mapping.", 409)
                    start_cfs_mapped(mapped_native_connection, remote_path, mapping_entries)
                    response = None
                elif use_sliced_cfs and connection.adapter == "creality_local":
                    moonraker = _same_printer_moonraker(connection, require_controls=True)
                    if moonraker is None or not _ready_for_start(moonraker.last_snapshot):
                        raise GcodeSubmissionError("Same-printer Moonraker control must be fresh and idle before original-mapping start.", 409)
                    from .printer_connectivity import poll_connection
                    poll_connection(moonraker)
                    moonraker.refresh_from_db()
                    if not _online(moonraker) or not _ready_for_start(moonraker.last_snapshot):
                        raise GcodeSubmissionError("Moonraker printer is no longer idle; no print-start sent.", 409)
                    moon_base, moon_headers = _printer_endpoint(moonraker)
                    response = requests.post(
                        moon_base + "/printer/print/start",
                        params={"filename": remote_path}, headers=moon_headers,
                        timeout=(3, 15), allow_redirects=False,
                    )
                elif connection.adapter == "creality_local":
                    from .creality_gcode import start_single_spool
                    # Reconfirm the exact file exists on printer before a fire-and-forget start.
                    if remote_path not in {item["path"] for item in list_printer_gcodes(connection)}:
                        raise GcodeSubmissionError("Creality did not confirm the expected printer file; no start sent.")
                    start_single_spool(connection, remote_path)
                    response = None
                elif connection.adapter == "flashforge":
                    from .flashforge_gcode import start_file
                    start_file(connection, remote_path)
                    response = None
                elif connection.adapter == "octoprint":
                    response = requests.post(
                        base + "/api/files/local/" + quote(remote_path, safe="/"),
                        json={"command": "select", "print": True}, headers=headers,
                        timeout=(3, 15), allow_redirects=False,
                    )
                elif connection.adapter == "prusa":
                    response = requests.post(
                        base + "/api/v1/files/local/" + quote(remote_path, safe="/"),
                        headers=headers, auth=_prusa_auth(connection), timeout=(3, 15), allow_redirects=False,
                    )
                else:
                    response = requests.post(
                        base + "/printer/print/start",
                        params={"filename": remote_path}, headers=headers,
                        timeout=(3, 15), allow_redirects=False,
                    )
            except requests.RequestException as exc:
                raise GcodeSubmissionError("Start-print outcome is uncertain. Inspect printer before trying again.", 502) from exc
            if (False if use_mapped_cfs or connection.adapter == "flashforge" or (connection.adapter == "creality_local" and not use_sliced_cfs) else response.status_code != 204 if connection.adapter in {"octoprint", "prusa"} else _json_response(response) != "ok"):
                raise GcodeSubmissionError("Printer did not confirm starting the print. Verify its live state.", 502)
        row.status = "unknown" if action == "print" and (use_mapped_cfs or (connection.adapter == "creality_local" and not use_sliced_cfs)) else "started" if action == "print" else "uploaded"
        row.message = ("K2 CFS mapping and print-start commands dispatched, but not acknowledged. Verify the selected filament and printer state." if use_mapped_cfs and action == "print" else "Creality start command sent, but this protocol provides no acknowledgement. Verify the live printer before any follow-up." if action == "print" and connection.adapter == "creality_local" and not use_sliced_cfs else
                       "Print-start accepted with original slicer mapping; MakerVault did not change any CFS slots. Verify filament at printer." if action == "print" and use_sliced_cfs else
                       "Print start accepted by printer." if action == "print" else "Uploaded to printer without starting.")
    except (FlashForgeFileError, CrealityGcodeError) as exc:
        row.status = "unknown"
        row.message = "Printer response was not fully verified. Inspect printer storage and live state before trying again."
    except GcodeSubmissionError as exc:
        logger.warning("G-code submission %s stage=%s status=%s error=%s", row.pk, stage, exc.status, exc)
        row.status = "unknown" if dispatch_attempted and exc.status == 502 else "rejected"
        row.message = str(exc)
    except (OSError, ValueError, TypeError, KeyError, requests.RequestException) as exc:
        logger.exception("Unexpected printer submission error, request %s, stage=%s, adapter=%s", row.pk, stage, connection.adapter)
        row.status = "unknown" if dispatch_attempted else "rejected"
        row.message = "Transfer/verification failed during " + stage + " (" + type(exc).__name__ + "). Inspect server logs and printer files before retrying."
    row.save(update_fields=["status", "message", "updated_at"])
    return _receipt(row)
