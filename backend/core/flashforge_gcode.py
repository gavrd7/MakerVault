"""Experimental FlashForge Adventurer 5M / 5M Pro LAN G-code API.

AD5X / Creator multi-material start commands require explicit material mapping
and are deliberately excluded. No commands are issued by listing.
"""
from pathlib import PurePosixPath

import requests

from .manufacturer_printer_adapters import normalise_flashforge_endpoint


class FlashForgeFileError(RuntimeError):
    pass


def _endpoint(connection):
    config = connection.config or {}
    serial = str(config.get("serial") or "").strip()
    code = str(config.get("check_code") or "").strip()
    if not serial or not code:
        raise FlashForgeFileError("FlashForge file API requires the configured serial and printer check code.")
    return normalise_flashforge_endpoint(connection.endpoint_url), serial, code


def _parse(response):
    if response.status_code != 200:
        raise FlashForgeFileError("FlashForge printer file API returned HTTP %s." % response.status_code)
    try:
        result = response.json()
    except ValueError as exc:
        raise FlashForgeFileError("FlashForge returned invalid file-service JSON.") from exc
    if not isinstance(result, dict) or result.get("code") not in (0, "0"):
        raise FlashForgeFileError("FlashForge rejected the file API operation.")
    return result


def _name(name):
    return (
        isinstance(name, str) and 0 < len(name) < 240
        and name.lower().endswith((".gcode", ".3mf"))
        and PurePosixPath(name).name == name
        and name not in {".", ".."}
        and "\x00" not in name and "\\" not in name
    )


def supports_simple_print(printer):
    models = [str(printer.model or ""), str(getattr(printer.catalog_model, "name", "") or "")]
    return any(
        ("5m" in model.lower() and "ad5x" not in model.lower()
         and "creator" not in model.lower() and "adventurer" in model.lower())
        for model in models
    )


def list_files(connection):
    base, serial, code = _endpoint(connection)
    try:
        response = requests.post(
            base + "/gcodeList", json={"serialNumber": serial, "checkCode": code},
            timeout=(3, 12), allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise FlashForgeFileError("FlashForge G-code file listing is unavailable.") from exc
    payload = _parse(response)
    names = payload.get("gcodeList")
    details = payload.get("gcodeListDetail")
    if isinstance(names, list):
        entries = names
    elif isinstance(details, list):
        entries = [item.get("gcodeFileName") for item in details if isinstance(item, dict)]
    else:
        raise FlashForgeFileError("FlashForge firmware returned an unrecognized G-code listing.")
    return [
        {"path": name, "size_bytes": None, "modified": None, "permissions": "rw"}
        for name in entries[:100] if _name(name)
    ]


def upload_file(connection, asset, remote_path):
    if not supports_simple_print(connection.printer):
        raise FlashForgeFileError("FlashForge upload is restricted to the Adventurer 5M/5M Pro until other models are validated.")
    if not _name(remote_path) or not remote_path.lower().endswith(".gcode"):
        raise FlashForgeFileError("FlashForge plain G-code upload requires a safe .gcode filename.")
    base, serial, code = _endpoint(connection)
    headers = {
        "serialNumber": serial, "checkCode": code, "fileSize": str(asset.file.size),
        "printNow": "false", "levelingBeforePrint": "true",
    }
    try:
        with asset.file.open("rb") as handle:
            response = requests.post(
                base + "/uploadGcode", headers=headers,
                files={"gcodeFile": (remote_path, handle, "application/octet-stream")},
                timeout=(5, 120), allow_redirects=False,
            )
    except requests.RequestException as exc:
        raise FlashForgeFileError("FlashForge upload outcome is unknown; inspect printer storage.") from exc
    _parse(response)
    return remote_path


def start_file(connection, remote_path):
    if not supports_simple_print(connection.printer):
        raise FlashForgeFileError("FlashForge start is restricted to Adventurer 5M/5M Pro; other models require material mapping support.")
    if not _name(remote_path) or not remote_path.lower().endswith(".gcode"):
        raise FlashForgeFileError("Choose a valid plain G-code file to start.")
    base, serial, code = _endpoint(connection)
    try:
        response = requests.post(
            base + "/printGcode",
            json={
                "serialNumber": serial, "checkCode": code,
                "fileName": remote_path, "levelingBeforePrint": True,
            },
            timeout=(3, 15), allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise FlashForgeFileError("FlashForge print-start outcome is unknown; inspect printer state.") from exc
    _parse(response)
    return True
