"""Read-only, size-bounded Creality material database mirror via SSH/SCP.

Only SCP source mode (scp -f) is used; no printer writes or catalogue imports.
The remote path is a hard-coded constant, never supplied by a request.
"""
import base64
import hashlib
import json
import socket
import re
from urllib.parse import urlparse

import paramiko
from django.utils import timezone

from .printer_connectivity import normalise_creality_endpoint
from .models import PrinterMaterialDatabaseSnapshot

MAX_DATABASE_BYTES = 5 * 1024 * 1024
MATERIAL_DATABASE_PATHS = {
    "k1": "/usr/data/creality/userdata/box/material_database.json",
    "other": "/mnt/UDISK/creality/userdata/box/material_database.json",
}


class MaterialDatabaseError(Exception):
    pass


class _PinnedHostKey(paramiko.MissingHostKeyPolicy):
    def __init__(self, fingerprint):
        self.fingerprint = fingerprint

    def missing_host_key(self, client, hostname, key):
        digest = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
        if "SHA256:" + digest != self.fingerprint:
            raise MaterialDatabaseError("Printer SSH host key does not match the verified fingerprint.")
        client.get_host_keys().add(hostname, key.get_name(), key)


def _ed25519_only_options():
    # OpenWrt Dropbear exposes both RSA and ED25519. Without this,
    # Paramiko can negotiate RSA even when the user pinned ED25519.
    return {"keys": [
        "ssh-rsa", "rsa-sha2-256", "rsa-sha2-512",
        "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521",
        "ssh-dss", "ssh-ed448",
    ]}


def discover_creality_host_key(connection):
    """Inspect a printer's ED25519 host key without authentication or persistence.

    The unverified fingerprint MUST be confirmed by the user before saving it.
    """
    if connection.adapter != "creality_local" or not connection.enabled:
        raise MaterialDatabaseError("Only enabled Creality connections can inspect SSH host keys.")
    host = urlparse(normalise_creality_endpoint(connection.endpoint_url)).hostname
    if not host:
        raise MaterialDatabaseError("The Creality connection has no valid printer host.")
    transport = None
    try:
        sock = socket.create_connection((host, 22), timeout=6)
        transport = paramiko.Transport(sock, disabled_algorithms=_ed25519_only_options())
        transport.banner_timeout = 6
        transport.start_client(timeout=6)
        key = transport.get_remote_server_key()
        if key.get_name() != "ssh-ed25519":
            raise MaterialDatabaseError("The printer did not offer an ED25519 host key.")
        digest = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
        return {"algorithm": "ssh-ed25519", "fingerprint": "SHA256:" + digest}
    except (paramiko.SSHException, socket.error, OSError, EOFError) as exc:
        raise MaterialDatabaseError("Could not retrieve the printer's ED25519 SSH host key.") from exc
    finally:
        if transport is not None:
            transport.close()


def _recv_exact(channel, count):
    """Receive only the requested number of bytes; reject short/truncated transfers."""
    chunks = []
    remaining = count
    while remaining:
        data = channel.recv(min(65536, remaining))
        if not data:
            raise MaterialDatabaseError("Printer SCP transfer ended before the declared file size.")
        chunks.append(data)
        remaining -= len(data)
    return b"".join(chunks)


def _read_scp_header(channel):
    header = bytearray()
    for _ in range(512):
        byte = _recv_exact(channel, 1)
        if byte == bytes([10]):
            break
        header.extend(byte)
    else:
        raise MaterialDatabaseError("Printer SCP response header is too long.")
    if not header:
        raise MaterialDatabaseError("Printer SCP returned an empty response.")
    if header[0] in (1, 2):
        # Never surface the remote stderr/error text, which is untrusted.
        raise MaterialDatabaseError("Printer SCP could not open the material database file.")
    parts = bytes(header).split(b" ", 2)
    if len(parts) != 3 or parts[0] != b"C0644" and not (
        len(parts[0]) == 5 and parts[0].startswith(b"C") and all(
            digit in b"01234567" for digit in parts[0][1:]
        )
    ):
        raise MaterialDatabaseError("Printer SCP returned an invalid file header.")
    if not parts[1].isdigit():
        raise MaterialDatabaseError("Printer SCP returned an invalid file length.")
    size = int(parts[1])
    if size > MAX_DATABASE_BYTES:
        raise MaterialDatabaseError("Printer material database exceeds the 5 MB read limit.")
    if size == 0:
        raise MaterialDatabaseError("Printer material database is empty.")
    if parts[2] != b"material_database.json":
        raise MaterialDatabaseError("Printer SCP returned an unexpected filename.")
    return size


def _scp_read_database(client, remote_path):
    channel = client.get_transport().open_session(timeout=10)
    try:
        channel.settimeout(15)
        channel.exec_command("scp -f " + remote_path)  # nosec B601 - allowlisted constant path; SCP source-only
        channel.sendall(bytes([0]))  # SCP protocol initial acknowledgement
        size = _read_scp_header(channel)
        channel.sendall(bytes([0]))  # acknowledge file header
        payload = _recv_exact(channel, size)
        if _recv_exact(channel, 1) != bytes([0]):
            raise MaterialDatabaseError("Printer SCP reported an incomplete file transfer.")
        channel.sendall(bytes([0]))  # final acknowledgement
        return payload
    finally:
        channel.close()


def pull_creality_material_database(connection):
    if connection.adapter != "creality_local" or not connection.enabled:
        raise MaterialDatabaseError("Only enabled Creality local connections can import this database.")
    cfg = dict(connection.config or {})
    user = str(cfg.get("material_ssh_user") or "").strip()
    password = str(cfg.get("material_ssh_password") or "")
    fingerprint = str(cfg.get("material_ssh_fingerprint") or "").strip()
    if not user or not password or not fingerprint.startswith("SHA256:"):
        raise MaterialDatabaseError("Configure SSH username, password and the printer host-key SHA256 fingerprint first.")
    host = urlparse(normalise_creality_endpoint(connection.endpoint_url)).hostname
    if not host:
        raise MaterialDatabaseError("The Creality connection has no valid printer host.")
    remote_path = MATERIAL_DATABASE_PATHS["k1" if connection.printer.model.lower().startswith("k1") else "other"]
    client = paramiko.SSHClient()
    # Ignore system known_hosts; accept only the explicitly pinned fingerprint.
    client.set_missing_host_key_policy(_PinnedHostKey(fingerprint))
    try:
        try:
            client.connect(
                hostname=host, port=22, username=user, password=password,
                timeout=6, auth_timeout=6, banner_timeout=6, look_for_keys=False,
                allow_agent=False, disabled_algorithms=_ed25519_only_options(),
            )
        except paramiko.AuthenticationException as exc:
            raise MaterialDatabaseError("Printer SSH authentication failed; check the saved username and password.") from exc
        except MaterialDatabaseError:
            raise
        except (paramiko.SSHException, OSError, socket.error) as exc:
            raise MaterialDatabaseError("Could not establish the printer SSH connection or negotiate its host key.") from exc
        try:
            payload = _scp_read_database(client, remote_path)
        except MaterialDatabaseError:
            raise
        except (paramiko.SSHException, OSError, socket.error, EOFError) as exc:
            raise MaterialDatabaseError("Printer SCP retrieval failed; check SCP support and the database path.") from exc
        try:
            catalog = json.loads(payload.decode("utf-8-sig"))
        except (UnicodeError, ValueError) as exc:
            raise MaterialDatabaseError("Printer material database is not valid UTF-8 JSON.") from exc
        if not isinstance(catalog, (dict, list)):
            raise MaterialDatabaseError("The printer material database has an unsupported JSON root.")
    finally:
        client.close()

    # Only update the cached copy after validating the complete transfer.
    copied_at = timezone.now()
    PrinterMaterialDatabaseSnapshot.objects.update_or_create(
        connection=connection,
        defaults={"payload": catalog, "synced_at": copied_at, "byte_size": len(payload)},
    )
    return {"synced_at": copied_at.isoformat(),
            "top_level_items": len(catalog), "bytes": len(payload),
            "scope": "read-only-printer-material-database"}
