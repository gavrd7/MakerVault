"""Experimental, read-only Bambu LAN FTPS browser.

The local FTPS server uses a device certificate, so an explicit SHA-256 leaf
certificate fingerprint is required before logging in. Never use TOFU,
automatically trust a new certificate or issue STOR/DELE/print commands here.
"""
from __future__ import annotations

import hashlib
import re
import socket
import ssl
from ftplib import FTP, FTP_TLS, all_errors
from urllib.parse import urlparse

from .manufacturer_printer_adapters import normalise_bambu_endpoint


class BambuStorageError(RuntimeError):
    pass


FINGERPRINT = re.compile(r"^[0-9a-fA-F]{64}$")
BAMBU_PRINT_FILES = (".gcode", ".gcode.3mf", ".3mf")
MAX_RESULTS = 1000


class ImplicitFTP_TLS(FTP_TLS):
    """FTP_TLS variant for Bambu's implicit TLS control port 990."""

    def connect(self, host="", port=0, timeout=-999, source_address=None):
        if host:
            self.host = host
        self.port = port or 990
        if timeout != -999:
            self.timeout = timeout
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout, source_address=source_address)
        self.af = self.sock.family
        self.sock = self.context.wrap_socket(self.sock, server_hostname=self.host)
        self.file = self.sock.makefile("r", encoding=self.encoding)
        self.welcome = self.getresp()
        return self.welcome


def _fingerprint(cert: bytes) -> str:
    return hashlib.sha256(cert).hexdigest().lower()


def _fingerprint_or_fail(raw: str) -> str:
    cleaned = str(raw or "").replace(":", "").strip().lower()
    if not FINGERPRINT.fullmatch(cleaned):
        raise BambuStorageError(
            "Bambu printer storage requires the SHA-256 certificate fingerprint, "
            "obtained independently from a trusted device or LAN administration channel."
        )
    return cleaned


def _parse_listing(line: str):
    """Parse only conservative UNIX LIST output; no untrusted path traversal."""
    parts = line.split(None, 8)
    if len(parts) != 9 or not parts[0] or parts[0][0] not in "-d":
        return None
    filename = parts[8]
    if not filename or filename in {".", ".."} or "/" in filename or "\\" in filename or "\x00" in filename:
        return None
    return {"name": filename, "directory": parts[0][0] == "d",
            "size_bytes": int(parts[4]) if parts[4].isdigit() else None}


def _check_peer(ftp: ImplicitFTP_TLS, expected: str):
    cert = ftp.sock.getpeercert(binary_form=True)
    if not cert or _fingerprint(cert) != expected:
        raise BambuStorageError("Bambu FTPS certificate fingerprint mismatch. No credentials were sent.")


def list_bambu_storage(connection):
    config = connection.config or {}
    expected = _fingerprint_or_fail(config.get("bambu_ftps_cert_sha256"))
    access_code = str(config.get("access_code") or "").strip()
    if not access_code:
        raise BambuStorageError("Bambu LAN access code is not configured.")
    hostname = urlparse(normalise_bambu_endpoint(connection.endpoint_url)).hostname
    if not hostname:
        raise BambuStorageError("Bambu printer hostname is missing.")

    # Certificate verification is explicitly pinned before credentials are sent.
    # This non-CA certificate is not trusted simply because it is on the LAN.
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ftp = ImplicitFTP_TLS(context=ctx, timeout=8)
    rows = []
    try:
        ftp.connect(hostname, 990, timeout=8)
        _check_peer(ftp, expected)
        FTP.login(ftp, user="bblp", passwd=access_code)
        ftp.prot_p()

        def scan(prefix):
            listings = []
            ftp.retrlines("LIST " + prefix if prefix else "LIST", listings.append)
            for line in listings[:MAX_RESULTS]:
                entry = _parse_listing(line)
                if not entry or entry["directory"]:
                    continue
                name = entry["name"]
                path = prefix.rstrip("/") + "/" + name if prefix else name
                if name.lower().endswith(BAMBU_PRINT_FILES):
                    rows.append({"path": path, "size_bytes": entry["size_bytes"], "modified": None, "permissions": "r"})
                if len(rows) >= MAX_RESULTS:
                    return

        # Some printer firmware stores print-ready archives under cache/.
        scan("")
        if len(rows) < MAX_RESULTS:
            try:
                scan("cache")
            except all_errors:
                pass  # Cache directory is not available on every device.
    except BambuStorageError:
        raise
    except (OSError, ssl.SSLError, *all_errors) as exc:
        raise BambuStorageError(
            "Bambu FTPS browsing failed or this firmware requires an incompatible TLS session. "
            "No printing command was issued."
        ) from exc
    finally:
        try:
            ftp.close()
        except (OSError, AttributeError):
            pass
    return rows[:MAX_RESULTS]
