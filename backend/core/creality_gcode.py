"""Experimental upload-only path for stock Creality OS on a trusted LAN.

The proprietary WebSocket monitoring API is not a validated print-start API.
Never dispatch a print command from this module. Port 80 may be absent on
firmware exposing Moonraker instead; users should configure it separately.
"""
from urllib.parse import urlparse, quote

import requests

from .printer_connectivity import normalise_creality_endpoint


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
        with asset.file.open("rb") as handle:
            response = requests.post(
                url, data=handle,
                headers={"Content-Type": "application/octet-stream", "Content-Length": str(asset.file.size)},
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
