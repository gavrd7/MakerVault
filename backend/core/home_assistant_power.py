"""Explicit manual printer power via a Home Assistant switch (no automations).

Owner-scoped configuration lives in PrintingIntegrationSetting; assigned entity
IDs live in Printer.profile_data. No credentials or URLs reach printer payloads.
"""
import base64
import hashlib
import ipaddress
import re
import socket
from datetime import timedelta
from urllib.parse import urlsplit

import requests
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.utils import timezone


class HomeAssistantPowerError(ValueError):
    pass


ENTITY_PATTERN = re.compile(r"^switch\.[a-z0-9_]{1,128}$")
BUSY_STATES = frozenset({
    "printing", "paused", "pausing", "resuming", "processing",
    "self-testing", "heating", "cooling", "finishing", "busy",
})


def valid_entity(value):
    return isinstance(value, str) and bool(ENTITY_PATTERN.fullmatch(value))


def _cipher():
    key = hashlib.sha256(("makervault-home-assistant-v1:" + settings.SECRET_KEY).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_token(raw):
    if not isinstance(raw, str) or not 8 <= len(raw.strip()) <= 4096:
        raise HomeAssistantPowerError("Enter a valid Home Assistant access token.")
    return _cipher().encrypt(raw.strip().encode("utf-8")).decode("ascii")


def decrypt_token(config):
    value = (config or {}).get("encrypted_token")
    if not isinstance(value, str) or not value:
        raise HomeAssistantPowerError("Configure a Home Assistant access token.")
    try:
        return _cipher().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise HomeAssistantPowerError("Saved Home Assistant token cannot be decrypted.") from exc


_PRIVATE_LAN_NETWORKS = tuple(ipaddress.ip_network(network) for network in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "127.0.0.0/8", "::1/128", "fc00::/7",
))


def _safe_private_ip(address):
    return (any(address in network for network in _PRIVATE_LAN_NETWORKS
                if network.version == address.version)
            and not address.is_link_local and not address.is_multicast)


def validate_url(value):
    """Accept private LAN endpoints or public HTTPS hostnames for HA.

    Public IP literals, public plaintext HTTP, metadata/link-local targets,
    credentials, redirects and arbitrary URL paths are deliberately refused.
    External HTTPS domains are supported for trusted reverse-proxy installs.
    """
    if not isinstance(value, str) or not value.strip() or len(value) > 300:
        raise HomeAssistantPowerError("Enter a Home Assistant server URL.")
    normalized = value.strip()
    try:
        parsed = urlsplit(normalized)
        host, port = parsed.hostname, parsed.port
    except ValueError as exc:
        raise HomeAssistantPowerError("Invalid Home Assistant URL or port.") from exc
    if parsed.scheme not in {"http", "https"}:
        raise HomeAssistantPowerError("Use an http:// or https:// Home Assistant URL.")
    if not host:
        raise HomeAssistantPowerError("Enter a Home Assistant server hostname or IP address.")
    if parsed.username or parsed.password:
        raise HomeAssistantPowerError("Put the access token in the token field, not the URL.")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise HomeAssistantPowerError("Use only the server address, without /api paths or query parameters.")
    if parsed.netloc.endswith(":"):
        raise HomeAssistantPowerError("Remove the empty port from the Home Assistant URL.")
    # DNS names are allowed, including private reverse-proxy and public HTTPS
    # virtual hosts. Never accept a public IP literal as the destination.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not _safe_private_ip(literal):
            raise HomeAssistantPowerError("Use a private network IP, or a trusted HTTPS domain.")
    elif parsed.scheme == "http":
        # Plain HTTP hostnames can rebind between validation and the socket
        # connection, exposing the bearer token to a different LAN service.
        # Require an explicit private IP for HTTP until DNS-pinned transports
        # are supported. HTTPS hostnames retain certificate authentication.
        raise HomeAssistantPowerError("Use a private IP address for HTTP Home Assistant URLs, or use HTTPS.")
    elif "." not in host and host != "localhost":
        # A single-label LAN hostname is still valid (Docker DNS, for example).
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,252}", host):
            raise HomeAssistantPowerError("Invalid Home Assistant hostname.")
    try:
        addresses = socket.getaddrinfo(host, port or (443 if parsed.scheme == "https" else 80),
                                       type=socket.SOCK_STREAM)
        ips = {ipaddress.ip_address(row[4][0]) for row in addresses}
    except (OSError, ValueError) as exc:
        raise HomeAssistantPowerError(
            "Home Assistant hostname cannot be resolved by the MakerVault server."
        ) from exc
    if not ips:
        raise HomeAssistantPowerError("Home Assistant hostname has no usable address.")
    private = all(_safe_private_ip(ip) for ip in ips)
    public = all(ip.is_global for ip in ips)
    if not private and not public:
        raise HomeAssistantPowerError(
            "Home Assistant DNS contains mixed or restricted network addresses."
        )
    if public and (parsed.scheme != "https" or literal is not None):
        raise HomeAssistantPowerError(
            "External Home Assistant addresses must use a trusted HTTPS hostname."
        )
    return normalized.rstrip("/")


def ha_request(setting, method, endpoint, *, body=None):
    if not setting or not setting.enabled:
        raise HomeAssistantPowerError("Home Assistant printer power is disabled.")
    base = validate_url(setting.endpoint_url)
    token = decrypt_token(setting.config)
    try:
        with requests.Session() as session:
            # Avoid forwarding the Home Assistant bearer token to any proxy
            # configured through environment variables.
            session.trust_env = False
            response = session.request(
                method, base + endpoint,
                headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
                json=body, timeout=(3, 7), allow_redirects=False,
            )
    except requests.RequestException as exc:
        raise HomeAssistantPowerError("Could not reach Home Assistant.") from exc
    if not 200 <= response.status_code < 300:
        raise HomeAssistantPowerError("Home Assistant refused the request (HTTP %d)." % response.status_code)
    try:
        return response.json()
    except ValueError as exc:
        raise HomeAssistantPowerError("Home Assistant returned an invalid response.") from exc


def get_switches(setting):
    data = ha_request(setting, "GET", "/api/states")
    if not isinstance(data, list):
        raise HomeAssistantPowerError("Home Assistant returned an invalid entity list.")
    switches = []
    for entry in data:
        if not isinstance(entry, dict) or not valid_entity(entry.get("entity_id")):
            continue
        name = entry.get("attributes") if isinstance(entry.get("attributes"), dict) else {}
        switches.append({
            "entity_id": entry["entity_id"],
            "name": str(name.get("friendly_name") or entry["entity_id"])[:120],
            "state": entry.get("state") if entry.get("state") in {"on", "off"} else "unknown",
        })
    return sorted(switches, key=lambda item: item["name"].casefold())[:500]


def switch_state(setting, entity):
    if not valid_entity(entity):
        raise HomeAssistantPowerError("Invalid assigned switch.")
    data = ha_request(setting, "GET", "/api/states/" + entity)
    if not isinstance(data, dict) or data.get("entity_id") != entity:
        raise HomeAssistantPowerError("Home Assistant returned a different switch.")
    return data.get("state") if data.get("state") in {"on", "off"} else "unknown"


def printer_is_busy(printer):
    """Fail closed on active telemetry; don't let stale history block an idle printer.

    A recently polled, connected, explicitly idle printer can override a
    historical print record that was not marked complete. A stale, missing or
    conflicting snapshot cannot override that record.
    """
    history_active = printer.print_jobs.filter(status="printing").exists()
    now = timezone.now()
    verified_idle = False
    has_connection = False
    for connection in printer.live_connections.filter(enabled=True):
        has_connection = True
        snapshot = connection.last_snapshot or {}
        job = snapshot.get("job")
        if not isinstance(job, dict):
            job = {}
        states = [snapshot.get("state"), job.get("state"), job.get("status")]
        normalized = {
            str(state or "").strip().casefold().replace("_", "-")
            for state in states if state is not None
        }
        # Even older telemetry indicating an active print is not proof it ended.
        if normalized & BUSY_STATES:
            return True
        checked = getattr(connection, "last_checked_at", None)
        interval = getattr(connection, "poll_interval_seconds", 30) or 30
        max_age = timedelta(seconds=max(120, 2 * interval))
        if (checked and now - checked <= max_age
                and getattr(connection, "status", None) == "connected"
                and str(snapshot.get("state") or "").strip().casefold()
                in {"idle", "ready", "standby", "complete", "completed"}):
            verified_idle = True
    # Unknown/stale telemetry is not evidence that the printer is safe to
    # power down. Require a fresh idle snapshot for connected printers; for
    # deliberately offline/unmonitored printers only explicit UI confirmation
    # remains available, and a recorded active job still blocks shutdown.
    return (not verified_idle if has_connection else history_active)

def set_switch(setting, entity, desired):
    if desired not in {"on", "off"} or not valid_entity(entity):
        raise HomeAssistantPowerError("Invalid power request.")
    # A successful service response acknowledges the command, not an immediate
    # physical state transition. Home Assistant state updates can lag behind.
    ha_request(setting, "POST", "/api/services/switch/turn_" + desired, body={"entity_id": entity})
    return desired
