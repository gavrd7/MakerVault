"""Optional isolated MakerVault slicing service (worker-only process).

Never invoke this module in MakerVault web/Celery. The service is disabled
without an explicit enabled flag, strong secret and a verified engine.
All file paths are hardcoded scratch names; no arbitrary CLI arguments.
"""
import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import BoundedSemaphore, Thread
import json
import os
from pathlib import Path
from functools import lru_cache
import tempfile
import uuid

from .runner import MAX_GCODE_BYTES, MAX_MODEL_BYTES, MAX_PROFILE_BYTES, WorkerError, run_prusa
from .orca_runner import run_orca
from .creality_runner import run_creality
from .engine_registry import configured_engines
from .three_mf_validation import validate_worker_3mf


MAX_REQUEST_BYTES = 48 * 1024 * 1024
MAX_OUTPUT_BYTES = MAX_GCODE_BYTES

# One bounded slice at a time. Threaded health checks remain responsive while
# the one approved job is executing, without concurrent CPU/memory spikes.
SLICE_SLOT = BoundedSemaphore(value=1)

# A thread-per-connection HTTP server must also bound idle/slow request
# connections, independently of the single active slicer subprocess.
MAX_WORKER_CONNECTIONS = 8


class BoundedWorkerHTTPServer(ThreadingHTTPServer):
    """No unbounded per-client threads, including during long slices."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._connections = BoundedSemaphore(MAX_WORKER_CONNECTIONS)

    def process_request(self, request, client_address):
        if not self._connections.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._connections.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._connections.release()



def configured_engine():
    """Legacy single-engine accessor for tests and older installations."""
    entries = configured_engines()
    return next(iter(entries.values()), None) if len(entries) == 1 else None


def _decode_payload(payload):
    expected = {
        "job_id", "engine", "engine_version",
        "model", "printer_profile", "filament_profile", "process_profile",
    }
    if not isinstance(payload, dict) or (set(payload) != expected and
                                        set(payload) != expected | {"model_format"}):
        raise WorkerError("Invalid slicing job payload.")
    try:
        uuid.UUID(str(payload["job_id"]))
    except (TypeError, ValueError):
        raise WorkerError("Invalid job identifier.") from None
    if payload["engine"] not in {"orcaslicer", "crealityprint", "prusaslicer"}:
        raise WorkerError("Unsupported isolated worker engine.")
    model_format = payload.get("model_format", "stl")
    if model_format not in {"stl", "3mf"}:
        raise WorkerError("Unsupported model input format.")
    files = {"model_format": model_format}
    for key, limit in (
        ("model", MAX_MODEL_BYTES),
        ("printer_profile", MAX_PROFILE_BYTES),
        ("filament_profile", MAX_PROFILE_BYTES),
        ("process_profile", MAX_PROFILE_BYTES),
    ):
        encoded = payload[key]
        if not isinstance(encoded, str) or len(encoded) > ((limit + 2) // 3) * 4 + 8:
            raise WorkerError("Oversized or invalid slicing input.")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error):
            raise WorkerError("Invalid slicing input encoding.") from None
        if not raw or len(raw) > limit:
            raise WorkerError("Invalid slicing input size.")
        files[key] = raw
    if model_format == "3mf":
        validate_worker_3mf(files["model"])
    return files


class Handler(BaseHTTPRequestHandler):
    server_version = "MakerVaultSlicerWorker/0"

    def log_message(self, format, *args):
        # Avoid logging tokens, private filenames or raw source.
        pass

    def _json(self, status, value):
        body = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/health":
            return self._json(404, {"error": "Not found."})
        engines = configured_engines()
        current = next(iter(engines.values()), None) if len(engines) == 1 else None
        return self._json(200, {
            "ready": bool(engines), "engine": current["engine"] if current else None,
            "version": current["version"] if current else None,
            "binary_sha256": current["binary_sha256"] if current else None,
            "engines": {key: {"version": value["version"],
                              "binary_sha256": value["binary_sha256"], "ready": True}
                        for key, value in engines.items()},
        })

    def do_POST(self):
        if self.path != "/v1/slice":
            return self._json(404, {"error": "Not found."})
        engines = configured_engines()
        if not engines:
            return self._json(503, {"error": "No verified slicing engine is installed."})
        supplied = self.headers.get("Authorization", "")
        expected = "Bearer " + next(iter(engines.values()))["token"]
        if not hmac.compare_digest(supplied, expected):
            return self._json(403, {"error": "Worker request is unauthorized."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= MAX_REQUEST_BYTES:
            return self._json(413, {"error": "Invalid or oversized request."})
        if not SLICE_SLOT.acquire(blocking=False):
            return self._json(429, {"error": "Worker is already processing a slice."})
        try:
            self.connection.settimeout(30)
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict):
                raise WorkerError("Job request must be a JSON object.")
            current = engines.get(request.get("engine"))
            if not current or request.get("engine_version") != current["version"]:
                raise WorkerError("Requested engine/version is unavailable.")
            files = _decode_payload(request)
            with tempfile.TemporaryDirectory(prefix="makervault-slice-") as tmp:
                workdir = Path(tmp)
                extension = ".json" if current["engine"] in {"orcaslicer", "crealityprint"} else ".ini"
                for field, name in (
                    ("model", "input." + files["model_format"]), ("printer_profile", "printer" + extension),
                    ("filament_profile", "filament" + extension),
                    ("process_profile", "process" + extension),
                ):
                    (workdir / name).write_bytes(files[field])
                runner = {"orcaslicer": run_orca,
                          "crealityprint": run_creality,
                          "prusaslicer": run_prusa}[current["engine"]]
                receipt = runner(current["binary"], workdir)
                data = (workdir / "output.gcode").read_bytes()
                if not data or len(data) > MAX_OUTPUT_BYTES:
                    raise WorkerError("Generated G-code exceeded the output size limit.")
                return self._json(200, {
                    "status": "completed", "bytes": receipt["bytes"],
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "gcode": base64.b64encode(data).decode("ascii"),
                })
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError, WorkerError):
            return self._json(422, {"error": "Slicing input or output was rejected."})
        except OSError:
            return self._json(500, {"error": "Worker failed to process the slicing job."})
        finally:
            SLICE_SLOT.release()


def main():
    # Socket is intentionally not published by the optional Compose overlay.
    # Only the MakerVault app is attached to the separate internal network.
    server = BoundedWorkerHTTPServer(("0.0.0.0", 8088), Handler)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
