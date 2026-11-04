"""Opt-in Moonraker G-code browsing and one-shot upload/print submission.

No raw G-code execution via MakerVault. Each printer operation has a durable
receipt before I/O and is never automatically retried after an uncertain send.
Other printer adapters must implement and validate their own transfer protocol.
"""
import re
import uuid
from datetime import timedelta
from pathlib import PurePosixPath
from urllib.parse import quote
from requests.auth import HTTPDigestAuth

import requests
from django.db import transaction
from django.utils import timezone

from .gcode_analysis import compare_printer_metadata, inspect_asset
from .models import FileAsset, Printer, PrinterConnection, PrinterGcodeSubmission
from .printer_connectivity import normalise_moonraker_endpoint, normalise_printer_endpoint
from .manufacturer_printer_adapters import normalise_prusalink_endpoint

MAX_UPLOAD_BYTES = 64 * 1024 * 1024
MOONRAKER_ADAPTERS = {"moonraker", "elegoo", "qidi", "sovol", "snapmaker", "voron"}
FILE_ADAPTERS = MOONRAKER_ADAPTERS | {"octoprint", "prusa"}


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


def list_printer_gcodes(connection):
    if connection.adapter == "octoprint":
        return _octoprint_files(connection)
    if connection.adapter == "prusa":
        return _prusalink_files(connection)
    rows = _get_json(connection, "/server/files/list", {"root": "gcodes"})
    if not isinstance(rows, list):
        raise GcodeSubmissionError("Printer file list has an unexpected format.", 502)
    result = []
    for item in rows[:5000]:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        if not isinstance(path, str) or not path.lower().endswith(".gcode") or not _valid_path(path):
            continue
        result.append({
            "path": path,
            "size_bytes": item.get("size") if isinstance(item.get("size"), int) else None,
            "modified": item.get("modified"),
            "permissions": item.get("permissions") or "",
        })
    return result


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
        and value.lower().endswith(".gcode")
        and "\x00" not in value
        and "\\" not in value
        and not value.startswith("/")
        and all(part not in {"", ".", ".."} for part in value.split("/"))
    )


def _metadata(connection, path):
    if connection.adapter in {"octoprint", "prusa"}:
        return {}  # Printer storage filenames alone are not verified slicer profiles.
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


def availability(connection):
    return {
        "supported": connection.adapter in FILE_ADAPTERS,
        "online": bool(_online(connection)),
        "can_upload": bool(connection.adapter in FILE_ADAPTERS and _online(connection) and connection.controls_enabled),
        "can_start": bool(
            connection.adapter in FILE_ADAPTERS and _online(connection)
            and connection.controls_enabled
            and (connection.last_snapshot or {}).get("state") == "idle"
            and not (connection.last_snapshot or {}).get("source_metadata", {}).get("power_loss_recovery")
        ),
        "enabled": connection.controls_enabled,
    }


def _require_action_ready(connection, action):
    state = availability(connection)
    if not state["supported"]:
        raise GcodeSubmissionError("This printer adapter does not support G-code submission yet.")
    if not state["online"] or not state["enabled"]:
        raise GcodeSubmissionError("Enable printer controls and refresh an online connection before submitting a file.")
    if action == "print" and not state["can_start"]:
        raise GcodeSubmissionError("Printer must be freshly verified idle before starting a job.")


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
        remote_path = "mv_" + request_id.hex[:12] + "_" + re.sub(
            r"[^A-Za-z0-9_.-]", "_", PurePosixPath(str((asset.metadata or {}).get("original_name") or "job.gcode")).name
        )[:140]
        if not remote_path.lower().endswith(".gcode"):
            remote_path += ".gcode"

    # A repeated request ID is a status lookup, NEVER a second dispatch.
    with transaction.atomic():
        Printer.objects.select_for_update().get(pk=connection.printer_id)
        old = PrinterGcodeSubmission.objects.filter(pk=request_id).first()
        if old:
            if old.connection_id != connection.pk or old.requested_by_id != user.pk or old.action != action or old.source != source or old.remote_path != remote_path or old.file_asset_id != (asset.pk if asset else None):
                raise GcodeSubmissionError("Submission ID was already used for a different operation.")
            return _receipt(old)
        connection.refresh_from_db()
        _require_action_ready(connection, action)
        recent = PrinterGcodeSubmission.objects.filter(connection__printer_id=connection.printer_id)
        if recent.filter(status__in=["pending", "unknown"], created_at__gte=timezone.now() - timedelta(minutes=10)).exists():
            raise GcodeSubmissionError("An earlier submission has an unresolved outcome. Verify printer state before another request.")
        row = PrinterGcodeSubmission.objects.create(
            id=request_id, connection=connection, requested_by=user, file_asset=asset,
            source=source, action=action, original_path=remote_path if source == "printer" else "",
            remote_path=remote_path, file_sha256=(asset.sha256 if asset else ""),
        )

    try:
        # All commands occur after the receipt is committed. Never auto-retry an
        # upload or print command with unknown delivery status.
        _require_action_ready(connection, action)
        if source == "printer":
            if remote_path not in {f["path"] for f in list_printer_gcodes(connection)}:
                raise GcodeSubmissionError("Printer file no longer exists. Refresh the printer file list.")
            meta = _metadata(connection, remote_path)
            report = {"printer_hints": [meta["printer_model"]] if meta.get("printer_model") else []}
        else:
            analysis = inspect_asset(asset)["analysis"]
            report = analysis
        verdict = compare_printer_metadata(report, connection.printer)
        if verdict["status"] == "mismatch":
            raise GcodeSubmissionError(verdict["reason"])
        if source == "makervault" and (report.get("partial") or any("firmware/control commands" in str(w) for w in report.get("warnings", []))):
            raise GcodeSubmissionError("File is too large for complete analysis or contains flagged firmware-control commands. Printer submission blocked.")
        if verdict["blocking"] and payload.get("acknowledge_unknown") is not True:
            raise GcodeSubmissionError("Printer compatibility is unknown. Review the file and explicitly acknowledge the risk.", 409)

        # Re-poll immediately before irreversible I/O; this prevents stale
        # monitoring data from authorizing a print while already busy.
        from .printer_connectivity import poll_connection
        try:
            poll_connection(connection)
        except Exception as exc:
            raise GcodeSubmissionError("Unable to verify fresh printer status before transfer. No command dispatched.", 409) from exc
        connection.refresh_from_db()
        _require_action_ready(connection, action)
        base, headers = _printer_endpoint(connection)
        if source == "makervault":
            try:
                with asset.file.open("rb") as handle:
                    response = requests.post(
                        base + ("/api/files/local" if connection.adapter == "octoprint" else "/server/files/upload"),
                        data=({"select": "false", "print": "false"} if connection.adapter == "octoprint" else {"root": "gcodes", "print": "false", "checksum": asset.sha256}),
                        files={"file": (remote_path, handle, "application/octet-stream")},
                        headers=headers, timeout=(5, 120), allow_redirects=False,
                    )
            except requests.RequestException as exc:
                raise GcodeSubmissionError("Upload outcome is uncertain. Inspect printer storage before trying again.", 502) from exc
            result = _octoprint_upload_receipt(response) if connection.adapter == "octoprint" else _json_response(response)
            uploaded_path = ((result.get("files") or {}).get("local") or {}).get("path") if connection.adapter == "octoprint" else (result.get("item") or {}).get("path")
            if not isinstance(result, dict) or uploaded_path != remote_path or result.get("print_started") or result.get("print_queued") or result.get("effectivePrint"):
                raise GcodeSubmissionError("Printer did not confirm upload-only completion. Verify printer state.", 502)
        if action == "print":
            # Verify state a second time after file transfer, particularly when
            # the upload took long enough for printer state to change.
            try:
                poll_connection(connection)
            except Exception as exc:
                raise GcodeSubmissionError("Unable to confirm printer is still idle after file upload. Do not start.", 409) from exc
            connection.refresh_from_db()
            _require_action_ready(connection, "print")
            try:
                if connection.adapter == "octoprint":
                    response = requests.post(
                        base + "/api/files/local/" + quote(remote_path, safe="/"),
                        json={"command": "select", "print": True}, headers=headers,
                        timeout=(3, 15), allow_redirects=False,
                    )
                else:
                    response = requests.post(
                        base + "/printer/print/start",
                        params={"filename": remote_path}, headers=headers,
                        timeout=(3, 15), allow_redirects=False,
                    )
            except requests.RequestException as exc:
                raise GcodeSubmissionError("Start-print outcome is uncertain. Inspect printer before trying again.", 502) from exc
            if (response.status_code != 204 if connection.adapter == "octoprint" else _json_response(response) != "ok"):
                raise GcodeSubmissionError("Printer did not confirm starting the print. Verify its live state.", 502)
        row.status = "started" if action == "print" else "uploaded"
        row.message = "Print start accepted by printer." if action == "print" else "Uploaded to printer without starting."
    except GcodeSubmissionError as exc:
        row.status = "unknown" if exc.status == 502 else "rejected"
        row.message = str(exc)
    except (OSError, ValueError, requests.RequestException) as exc:
        row.status = "unknown"
        row.message = "Submission outcome uncertain. Verify the printer before retrying."
    row.save(update_fields=["status", "message", "updated_at"])
    return _receipt(row)
