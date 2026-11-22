"""Fixed-origin client for the isolated optional engine installer.

Only the server environment can select the installer endpoint and secret.
Browser users choose an engine and version, never arbitrary URLs or commands.
"""
import os
from urllib.parse import urlsplit
import requests


class EngineInstallerUnavailable(ValueError):
    pass


def _connection():
    url = os.environ.get("MAKERVAULT_SLICER_INSTALLER_URL", "").rstrip("/")
    token = os.environ.get("MAKERVAULT_SLICER_INSTALLER_TOKEN", "")
    parsed = urlsplit(url)
    if (len(token) < 32 or parsed.scheme != "http" or
            parsed.hostname not in {"slicer-worker", "slicer-engine-installer"} or parsed.port != 8091 or
            parsed.path or parsed.query or parsed.fragment):
        raise EngineInstallerUnavailable("Engine installer is not configured.")
    return url, token


def installer_request(method, endpoint, payload=None):
    if (method, endpoint) not in {
        ("GET", "/catalog"), ("GET", "/status"), ("POST", "/install"),
        ("POST", "/rollback"), ("POST", "/activate"), ("POST", "/uninstall")
    }:
        raise EngineInstallerUnavailable("Unsupported installer operation.")
    url, token = _connection()
    session = requests.Session()
    session.trust_env = False
    try:
        response = session.request(method, url + endpoint,
            headers={"Authorization": "Bearer " + token},
            json=payload, timeout=(3, 30), allow_redirects=False)
        if response.status_code not in {200, 202} or len(response.content) > 128 * 1024:
            raise EngineInstallerUnavailable("Engine installer request was rejected.")
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Unexpected installer response.")
        return data
    except (requests.RequestException, ValueError) as exc:
        raise EngineInstallerUnavailable("Engine installer is unavailable.") from exc
    finally:
        session.close()
