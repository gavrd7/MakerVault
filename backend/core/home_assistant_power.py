"""Explicit manual printer power via a Home Assistant switch (no automations).

Owner-scoped configuration lives in PrintingIntegrationSetting; assigned entity
IDs live in Printer.profile_data. No credentials or URLs reach printer payloads.
"""
import base64
import hashlib
import ipaddress
import re
import socket
from urllib.parse import urlsplit

import requests
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


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


def validate_url(value):
    if not isinstance(value, str) or len(value) > 300:
        raise HomeAssistantPowerError("Enter a local Home Assistant URL.")
    try:
        parsed = urlsplit(value.strip())
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise HomeAssistantPowerError("Invalid Home Assistant URL.") from exc
    if (parsed.scheme not in {"http", "https"} or not host or parsed.username
            or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"} or not port and ":" in parsed.netloc and parsed.netloc.endswith(":")):
        raise HomeAssistantPowerError("Use a Home Assistant HTTP(S) URL without credentials or paths.")
    # HA is expected to be on an explicitly trusted private network. Prevent
    # arbitrary requests to Internet services / cloud metadata endpoints.
    try:
        addresses = socket.getaddrinfo(host, port or (443 if parsed.scheme == "https" else 80),
                                       type=socket.SOCK_STREAM)
        ips = {ipaddress.ip_address(row[4][0]) for row in addresses}
    except (OSError, ValueError) as exc:
        raise HomeAssistantPowerError("Home Assistant host cannot be resolved.") from exc
    if not ips or any(not (ip.is_private or ip.is_loopback) or ip.is_link_local
                      or ip.is_multicast or ip.is_reserved and not ip.is_private
                      for ip in ips):
        raise HomeAssistantPowerError("Home Assistant must resolve to a private LAN address.")
    return value.strip().rstrip("/")


def ha_request(setting, method, endpoint, *, body=None):
    if not setting or not setting.enabled:
        raise HomeAssistantPowerError("Home Assistant printer power is disabled.")
    base = validate_url(setting.endpoint_url)
    token = decrypt_token(setting.config)
    try:
        response = requests.request(
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
    # If any live source indicates an active or uncertain job, fail closed.
    if printer.print_jobs.filter(status="printing").exists():
        return True
    for connection in printer.live_connections.filter(enabled=True):
        snapshot = connection.last_snapshot or {}
        states = [snapshot.get("state"), (snapshot.get("job") or {}).get("state"),
                  (snapshot.get("job") or {}).get("status")]
        if any(str(state or "").strip().casefold().replace("_", "-") in BUSY_STATES for state in states):
            return True
    return False


def set_switch(setting, entity, desired):
    if desired not in {"on", "off"} or not valid_entity(entity):
        raise HomeAssistantPowerError("Invalid power request.")
    ha_request(setting, "POST", "/api/services/switch/turn_" + desired, body={"entity_id": entity})
    return switch_state(setting, entity)
