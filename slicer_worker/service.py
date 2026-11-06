"""Optional isolated MakerVault slicing service (worker-only process).

Never invoke this module in MakerVault web/Celery. The service is disabled
without an explicit enabled flag, strong secret and a verified engine.
All file paths are hardcoded scratch names; no arbitrary CLI arguments.
"""
import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid

from .runner import MAX_GCODE_BYTES, MAX_MODEL_BYTES, MAX_PROFILE_BYTES, WorkerError, run_prusa
from .orca_runner import run_orca


MAX_REQUEST_BYTES = 48 * 1024 * 1024
MAX_OUTPUT_BYTES = MAX_GCODE_BYTES


def configured_engine():
    """An installed executable is not enough: admin must opt in explicitly."""
    token = os.environ.get("SLICER_WORKER_TOKEN", "")
    engine = os.environ.get("SLICER_ENGINE", "orcaslicer")
    binary = os.environ.get("SLICER_ENGINE_BINARY", "")
    version = os.environ.get("SLICER_ENGINE_VERSION", "")
    if (
        os.environ.get("SLICER_WORKER_ENABLED") != "1"
        or len(token) < 32 or engine not in {"orcaslicer", "prusaslicer"}
        or not binary or not version or len(version) > 80
    ):
        return None
    path = Path(binary)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        return None
    try:
        result = subprocess.run(
            [str(path), "--version"], capture_output=True, timeout=8,
            env={"HOME": "/tmp", "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    # Exact verified version still requires a pinned build/fixture; this
    # health check only rules out obviously unrelated executable installs.
    if result.returncode != 0 or version.encode() not in result.stdout[:1024]:
        return None
    return {"binary": path, "engine": engine, "version": version, "token": token}


def _decode_payload(payload):
    if not isinstance(payload, dict) or set(payload) != {
        "job_id", "engine", "engine_version",
        "model", "printer_profile", "filament_profile", "process_profile",
    }:
        raise WorkerError("Invalid slicing job payload.")
    try:
        uuid.UUID(str(payload["job_id"]))
    except (TypeError, ValueError):
        raise WorkerError("Invalid job identifier.") from None
    if payload["engine"] not in {"orcaslicer", "prusaslicer"}:
        raise WorkerError("Unsupported isolated worker engine.")
    files = {}
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
        current = configured_engine()
        return self._json(200, {
            "ready": bool(current), "engine": current["engine"] if current else None,
            "version": current["version"] if current else None,
        })

    def do_POST(self):
        if self.path != "/v1/slice":
            return self._json(404, {"error": "Not found."})
        current = configured_engine()
        if not current:
            return self._json(503, {"error": "Worker engine is not installed and verified."})
        supplied = self.headers.get("Authorization", "")
        expected = "Bearer " + current["token"]
        if not hmac.compare_digest(supplied, expected):
            return self._json(403, {"error": "Worker request is unauthorized."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= MAX_REQUEST_BYTES:
            return self._json(413, {"error": "Invalid or oversized request."})
        try:
            self.connection.settimeout(30)
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict):
                raise WorkerError("Job request must be a JSON object.")
            if request.get("engine") != current["engine"] or request.get("engine_version") != current["version"]:
                raise WorkerError("Requested engine/version is unavailable.")
            files = _decode_payload(request)
            with tempfile.TemporaryDirectory(prefix="makervault-slice-") as tmp:
                workdir = Path(tmp)
                extension = ".json" if current["engine"] == "orcaslicer" else ".ini"
                for field, name in (
                    ("model", "input.stl"), ("printer_profile", "printer" + extension),
                    ("filament_profile", "filament" + extension),
                    ("process_profile", "process" + extension),
                ):
                    (workdir / name).write_bytes(files[field])
                runner = run_orca if current["engine"] == "orcaslicer" else run_prusa
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


def main():
    # Socket is intentionally not published by the optional Compose overlay.
    # Only the MakerVault app is attached to the separate internal network.
    HTTPServer(("0.0.0.0", 8088), Handler).serve_forever()


if __name__ == "__main__":
    main()
