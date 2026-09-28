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


def simplyprint_api_root(raw_url: str, company_id) -> str:
    base = normalise_service_url(raw_url or "https://api.simplyprint.io")
    company = str(company_id or "").strip()
    if not company.isdigit() or int(company) <= 0:
        raise PrintingIntegrationError("Enter the SimplyPrint account/company ID.")
    return f"{base}/{company}"


def _simplyprint_payload(response, context: str) -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        raise PrintingIntegrationError(f"SimplyPrint returned invalid JSON while {context}.") from exc
    if not isinstance(payload, dict):
        raise PrintingIntegrationError(f"SimplyPrint returned an unexpected response while {context}.")
    if response.status_code >= 400 or payload.get("status") is False:
        message = str(payload.get("message") or "").strip()
        detail = f": {message}" if message else ""
        raise PrintingIntegrationError(
            f"SimplyPrint returned HTTP {response.status_code}{detail} while {context}."
        )
    return payload


def probe_simplyprint(raw_url: str, company_id, api_key: str) -> dict:
    root = simplyprint_api_root(raw_url or "https://api.simplyprint.io", company_id)
    key = str(api_key or "").strip()
    if not key:
        raise PrintingIntegrationError("Enter a SimplyPrint API key.")

    try:
        response = requests.get(
            root + "/account/Test",
            headers={
                "Accept": "application/json",
                "X-API-KEY": key,
                "User-Agent": "MakerVault/0.6 (+SimplyPrint integration probe)",
            },
            timeout=(4, 15),
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise PrintingIntegrationError("MakerVault could not reach the SimplyPrint API.") from exc

    payload = _simplyprint_payload(response, "testing the API key")
    return {
        "endpoint_url": root.rsplit("/", 1)[0],
        "company_id": str(company_id),
        "message": payload.get("message") or "",
    }
