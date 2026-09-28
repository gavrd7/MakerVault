from __future__ import annotations

from urllib.parse import urlparse

import requests


class PrintingIntegrationError(ValueError):
    pass


def normalise_service_url(raw_url: str) -> str:
    value = str(raw_url or "").strip().rstrip("/")
    if not value:
        raise PrintingIntegrationError("Enter a service URL.")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise PrintingIntegrationError("Service URL must use HTTP or HTTPS.")
    if not parsed.hostname:
        raise PrintingIntegrationError("Service URL must include a host.")
    if parsed.username or parsed.password:
        raise PrintingIntegrationError("Credentials embedded in service URLs are not supported.")
    return value


def probe_spoolman(raw_url: str) -> dict:
    base = normalise_service_url(raw_url)
    if base.endswith("/api/v1"):
        info_url = base + "/info"
    else:
        info_url = base + "/api/v1/info"

    try:
        response = requests.get(
            info_url,
            headers={"User-Agent": "MakerVault/0.6 (+Spoolman integration probe)"},
            timeout=(3, 7),
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise PrintingIntegrationError("MakerVault could not reach the Spoolman server.") from exc

    if response.status_code != 200:
        raise PrintingIntegrationError(
            f"Spoolman probe returned HTTP {response.status_code}."
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise PrintingIntegrationError("Spoolman returned an invalid response.") from exc

    if not isinstance(payload, dict):
        raise PrintingIntegrationError("Spoolman returned an unexpected response.")

    return {
        "endpoint_url": base,
        "info": payload,
    }
