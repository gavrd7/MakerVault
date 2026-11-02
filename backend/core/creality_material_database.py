"""Creality material database mirror: bounded, read-only SSH/SFTP fetch.

The live printer's material_database.json is never changed. Unlike CFS slot
telemetry this reads its saved catalogue. No write-capable SSH command is sent.
"""
import base64
import hashlib
import json
import socket
from urllib.parse import urlparse

import paramiko
from django.utils import timezone

from .printer_connectivity import normalise_creality_endpoint

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
            raise paramiko.SSHException("Printer SSH host key does not match the configured fingerprint.")
        client.get_host_keys().add(hostname, key.get_name(), key)


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
    # No system-host-key fallback or auto-add. Always verify the pinned key.
    client.set_missing_host_key_policy(_PinnedHostKey(fingerprint))
    try:
        client.connect(
            hostname=host, port=22, username=user, password=password,
            timeout=6, auth_timeout=6, banner_timeout=6, look_for_keys=False,
            allow_agent=False,
        )
        try:
            with client.open_sftp() as sftp:
                if sftp.stat(remote_path).st_size > MAX_DATABASE_BYTES:
                    raise MaterialDatabaseError("Printer material database is too large to import safely.")
                with sftp.open(remote_path, "rb") as remote:
                    payload = remote.read(MAX_DATABASE_BYTES + 1)
        except (paramiko.SSHException, OSError):
            # Some Creality SSH builds implement SCP but no SFTP subsystem.
            # The remote command is a fixed, literal, read-only file read.
            stdin, stdout, stderr = client.exec_command("cat " + remote_path, timeout=10)
            stdin.close()
            payload = stdout.read(MAX_DATABASE_BYTES + 1)
            if len(payload) > MAX_DATABASE_BYTES:
                raise MaterialDatabaseError("Printer material database is too large to import safely.")
            if stdout.channel.recv_exit_status() != 0:
                raise MaterialDatabaseError("Printer material database could not be read.")
        if len(payload) > MAX_DATABASE_BYTES:
            raise MaterialDatabaseError("Printer material database exceeded the 5 MB read limit.")
        catalog = json.loads(payload.decode("utf-8-sig"))
        if not isinstance(catalog, (dict, list)):
            raise MaterialDatabaseError("The printer material database has an unsupported JSON root.")
    except (paramiko.SSHException, socket.error, OSError, UnicodeError, ValueError) as exc:
        raise MaterialDatabaseError("Could not read the printer material database; check SSH access, host key and file path.") from exc
    finally:
        client.close()
    # Cache the exact printer-side JSON separately from MakerVault's filament
    # products: no new manufacturer, colour or spool is guessed or written.
    cfg["material_database_snapshot"] = catalog
    cfg["material_database_synced_at"] = timezone.now().isoformat()
    connection.config = cfg
    connection.save(update_fields=["config", "updated_at"])
    return {"synced_at": cfg["material_database_synced_at"],
            "top_level_items": len(catalog), "bytes": len(payload),
            "scope": "read-only-printer-material-database"}
