"""Bounded authenticated transport to the opt-in isolated slicer worker.

This transport is not a Celery task or a job dispatcher. Neither filenames nor
engine command line arguments cross the API. Only the server's fixed worker
URL/token environment settings may select a remote destination.
"""
import base64
import hashlib
import json
import os
from urllib.parse import urlsplit
import uuid

import requests


MAX_REQUEST_MODEL = 32 * 1024 * 1024
MAX_REQUEST_PROFILE = 1024 * 1024
MAX_RESPONSE = 90 * 1024 * 1024
MAX_GCODE = 64 * 1024 * 1024


from .slicer_failure_messages import REASONS, explain_worker_failure


class SlicerWorkerError(ValueError):
    pass


def worker_settings():
    url = os.environ.get("MAKERVAULT_SLICER_WORKER_URL", "").rstrip("/")
    token = os.environ.get("MAKERVAULT_SLICER_WORKER_TOKEN", "")
    if not url or len(token) < 32:
        raise SlicerWorkerError("Isolated slicing service is not configured.")
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname or parsed.username or parsed.password
        or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
    ):
        raise SlicerWorkerError("Invalid isolated worker service configuration.")
    return url, token


def _session():
    session = requests.Session()
    session.trust_env = False
    return session


def health():
    url, _token = worker_settings()
    session = _session()
    try:
        response = session.get(url + "/health", timeout=(2, 8), allow_redirects=False)
        if response.status_code != 200 or len(response.content) > 4096:
            raise SlicerWorkerError("Slicing worker health check failed.")
        payload = response.json()
        if not isinstance(payload, dict):
            raise SlicerWorkerError("Worker returned invalid health information.")
        supported = {"orcaslicer", "crealityprint", "prusaslicer"}
        engines = {}
        if isinstance(payload.get("engines"), dict) and len(payload["engines"]) <= 3:
            for key, entry in payload["engines"].items():
                if key not in supported or not isinstance(entry, dict):
                    continue
                version, digest = entry.get("version"), entry.get("binary_sha256")
                if (entry.get("ready") is True and isinstance(version, str)
                        and 1 <= len(version) <= 80 and isinstance(digest, str)
                        and len(digest) == 64
                        and all(c in "0123456789abcdef" for c in digest)):
                    engines[key] = {"version": version, "binary_sha256": digest, "ready": True}
        return {
            "ready": payload.get("ready") is True,
            "engine": payload.get("engine") if payload.get("engine") in supported else None,
            "version": str(payload.get("version") or "")[:80],
            "binary_sha256": payload.get("binary_sha256")
                if isinstance(payload.get("binary_sha256"), str) and len(payload["binary_sha256"]) == 64
                else None,
            "engines": engines,
        }
    except (requests.RequestException, ValueError) as exc:
        raise SlicerWorkerError("Isolated slicing worker is unreachable or incompatible.") from exc
    finally:
        session.close()


def _encode(raw, limit):
    if not isinstance(raw, bytes) or not raw or len(raw) > limit:
        raise SlicerWorkerError("Slicing input is missing or too large.")
    return base64.b64encode(raw).decode("ascii")


def run_remote_job(job_id, engine, version, model, printer_profile, filament_profile, process_profile, *, timeout_seconds=900, model_format="stl", filament_profiles=None):
    if model_format not in {"stl", "3mf"}:
        raise SlicerWorkerError("Unsupported slicer input format.")
    if not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 900:
        raise SlicerWorkerError("Invalid slicing timeout.")
    if engine not in {"orcaslicer", "crealityprint", "prusaslicer"} or not isinstance(version, str) or not version or len(version) > 80:
        raise SlicerWorkerError("Unsupported slicing worker engine/version.")
    try:
        canonical_id = str(uuid.UUID(str(job_id)))
    except (TypeError, ValueError):
        raise SlicerWorkerError("Invalid slicing job identifier.") from None
    url, token = worker_settings()
    payload = {
        "job_id": canonical_id, "engine": engine, "engine_version": version,
        "model": _encode(model, MAX_REQUEST_MODEL),
        "printer_profile": _encode(printer_profile, MAX_REQUEST_PROFILE),
        "filament_profile": _encode(filament_profile, MAX_REQUEST_PROFILE),
        "process_profile": _encode(process_profile, MAX_REQUEST_PROFILE),
    }
    if model_format == "3mf":
        payload["model_format"] = "3mf"
    if filament_profiles is not None:
        if (engine != "orcaslicer" or model_format != "3mf"
                or not isinstance(filament_profiles, (list, tuple))
                or not 2 <= len(filament_profiles) <= 16):
            raise SlicerWorkerError("Multiple native filaments require an Orca 3MF job.")
        if any(not isinstance(profile, bytes) for profile in filament_profiles):
            raise SlicerWorkerError("Invalid native filament palette.")
        if filament_profiles[0] != filament_profile:
            raise SlicerWorkerError("The first native filament preset must match the legacy profile.")
        payload["filament_profiles"] = [
            _encode(profile, MAX_REQUEST_PROFILE) for profile in filament_profiles
        ]
    session = _session()
    response = None
    try:
        response = session.post(
            url + "/v1/slice",
            data=json.dumps(payload, separators=(",", ":")).encode(),
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            stream=True, timeout=(3, timeout_seconds), allow_redirects=False,
        )
        if response.status_code != 200:
            # The worker returns bounded, structured stage names. Never
            # include arbitrary response text in job messages or logs.
            allowed = {"validating request", "validating model and profile payloads",
                       "running slicer engine", "validating generated G-code"}
            stage = None
            reason = None
            reasons = set(REASONS)
            try:
                declared_error_length = response.headers.get("Content-Length")
                if (declared_error_length is None or (
                    declared_error_length.isdecimal() and int(declared_error_length) <= 1024
                )):
                    bounded = bytearray()
                    for chunk in response.iter_content(chunk_size=256):
                        bounded.extend(chunk)
                        if len(bounded) > 1024:
                            break
                    if len(bounded) <= 1024:
                        result = json.loads(bounded)
                        if isinstance(result, dict):
                            if result.get("stage") in allowed:
                                stage = result["stage"]
                            if result.get("reason") in reasons:
                                reason = result["reason"]
            except (ValueError, requests.RequestException, UnicodeDecodeError):
                pass
            message = explain_worker_failure(reason, response.status_code)
            if reason:
                message += " [" + reason + "]"
            raise SlicerWorkerError(message)
        declared = response.headers.get("Content-Length")
        if declared and (not declared.isdecimal() or int(declared) > MAX_RESPONSE):
            raise SlicerWorkerError("Worker response exceeds the allowed size.")
        buffer = bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            buffer.extend(chunk)
            if len(buffer) > MAX_RESPONSE:
                raise SlicerWorkerError("Worker response exceeds the allowed size.")
        result = json.loads(buffer)
        if not isinstance(result, dict) or result.get("status") != "completed":
            raise SlicerWorkerError("Worker returned an invalid slice result.")
        encoded = result.get("gcode")
        if not isinstance(encoded, str) or len(encoded) > ((MAX_GCODE + 2) // 3) * 4 + 8:
            raise SlicerWorkerError("Worker output is not bounded plain-text G-code.")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error):
            raise SlicerWorkerError("Invalid encoded G-code output.") from None
        if not data or len(data) > MAX_GCODE or b"\x00" in data[:4096]:
            raise SlicerWorkerError("Worker returned unsupported G-code content.")
        if result.get("bytes") != len(data) or result.get("sha256") != hashlib.sha256(data).hexdigest():
            raise SlicerWorkerError("Worker G-code checksum/length verification failed.")
        return data
    except (requests.RequestException, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SlicerWorkerError("Slicer worker transport failed.") from exc
    finally:
        if response is not None:
            response.close()
        session.close()
