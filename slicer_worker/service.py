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
import logging
import os
from pathlib import Path
from functools import lru_cache
import tempfile
import uuid
import zlib

from .runner import (MAX_GCODE_BYTES, MAX_MODEL_BYTES, MAX_PROFILE_BYTES, WorkerError,
                     DEFAULT_TIMEOUT_SECONDS, MAX_NATIVE_SLICE_TIMEOUT_SECONDS, run_prusa)
from .orca_runner import run_orca
from .creality_runner import run_creality
from .bambu_runner import run_bambu
from .engine_registry import configured_engines
from .three_mf_validation import validate_worker_3mf
from .resource_budget import model_input_budget, gcode_output_budget
from .material_gcode_audit import expected_native_tools, verify_multi_material_output


logger = logging.getLogger(__name__)

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
    if not isinstance(payload, dict) or not expected.issubset(payload) or (
            set(payload) - expected - {"model_format", "filament_profiles", "creality_model_stls", "creality_tool_ids", "creality_native_project", "native_modifier_project", "prusa_placed_stl", "creality_placed_stl", "creality_model_raw_sha256", "prusa_offline_mmu", "prusa_offline_xl", "prusa_offline_colour", "prusa_offline_xl_colour",
                "orca_streamed_plate", "orca_streamed_sha256", "slice_timeout_seconds"}):
        raise WorkerError("Invalid slicing job payload.")
    try:
        uuid.UUID(str(payload["job_id"]))
    except (TypeError, ValueError):
        raise WorkerError("Invalid job identifier.") from None
    if payload["engine"] not in {"orcaslicer", "crealityprint", "prusaslicer", "bambustudio"}:
        raise WorkerError("Unsupported isolated worker engine.")
    model_format = payload.get("model_format", "stl")
    if model_format not in {"stl", "3mf"}:
        raise WorkerError("Unsupported model input format.")
    if payload["engine"] == "prusaslicer" and model_format == "3mf" and (
            payload["engine_version"] != "2.9.7" or any(key in payload for key in (
                "filament_profiles", "creality_model_stls", "creality_tool_ids",
                "creality_native_project", "native_modifier_project", "prusa_placed_stl"))):
        raise WorkerError("Invalid native Prusa project execution contract.")
    if "prusa_offline_xl" in payload:
        metadata = payload["prusa_offline_xl"]
        if (payload["engine"] != "prusaslicer" or
                payload["engine_version"] != "2.9.7" or model_format != "3mf"
                or not isinstance(metadata, dict) or set(metadata) != {"tools"}
                or "prusa_offline_mmu" in payload
                or "prusa_offline_colour" in payload
                or any(key in payload for key in (
                    "filament_profiles", "creality_model_stls", "creality_tool_ids",
                    "creality_native_project", "native_modifier_project", "prusa_placed_stl"))):
            raise WorkerError("Invalid Prusa offline XL execution contract.")
    if "prusa_offline_mmu" in payload:
        metadata = payload["prusa_offline_mmu"]
        if (payload["engine"] != "prusaslicer" or
                payload["engine_version"] != "2.9.7" or model_format != "3mf"
                or "prusa_offline_xl" in payload
                or "prusa_offline_colour" in payload
                or not isinstance(metadata, dict)
                or set(metadata) != {"tools", "tower"}
                or any(key in payload for key in (
                    "filament_profiles", "creality_model_stls", "creality_tool_ids",
                    "creality_native_project", "native_modifier_project", "prusa_placed_stl"))):
            raise WorkerError("Invalid Prusa offline MMU execution contract.")
    if "prusa_offline_xl_colour" in payload:
        metadata=payload["prusa_offline_xl_colour"]
        if (payload["engine"]!="prusaslicer" or
                payload["engine_version"]!="2.9.7" or model_format!="3mf" or
                not isinstance(metadata,dict) or set(metadata) not in ({"tool"},{"tools"}) or
                any(key in payload for key in (
                    "prusa_offline_mmu","prusa_offline_xl","prusa_offline_colour",
                    "filament_profiles","creality_model_stls","creality_tool_ids",
                    "creality_native_project","native_modifier_project",
                    "prusa_placed_stl"))):
            raise WorkerError("Invalid offline Prusa XL colour contract.")
    if "prusa_offline_colour" in payload:
        metadata=payload["prusa_offline_colour"]
        if (payload["engine"]!="prusaslicer" or
                payload["engine_version"]!="2.9.7" or model_format!="3mf" or
                not isinstance(metadata,dict) or set(metadata) not in
                ({"tool","tower"},{"tools","tower"}) or
                any(key in payload for key in (
                    "prusa_offline_mmu","prusa_offline_xl","filament_profiles",
                    "creality_model_stls","creality_tool_ids",
                    "creality_native_project","native_modifier_project",
                    "prusa_placed_stl"))):
            raise WorkerError("Invalid offline Prusa colour execution contract.")
    if ("creality_model_raw_sha256" in payload) != ("creality_placed_stl" in payload):
        raise WorkerError("Missing authenticated Creality placed STL digest.")
    digest = payload.get("creality_model_raw_sha256")
    if digest is not None and (not isinstance(digest, str) or len(digest) != 64
                              or any(c not in "0123456789abcdef" for c in digest)):
        raise WorkerError("Invalid Creality placed STL digest.")
    if "creality_placed_stl" in payload and (
            payload["creality_placed_stl"] is not True or
            payload["engine"] != "crealityprint" or
            payload["engine_version"] != "7.3.1" or model_format != "stl" or
            any(key in payload for key in (
                "filament_profiles", "creality_model_stls", "creality_tool_ids",
                "creality_native_project", "native_modifier_project",
                "prusa_placed_stl", "prusa_offline_mmu", "prusa_offline_xl",
                "prusa_offline_colour"))):
        raise WorkerError("Invalid Creality placed-STL execution contract.")
    if "prusa_placed_stl" in payload and (
            payload["prusa_placed_stl"] is not True or
            payload["engine"] != "prusaslicer" or
            payload["engine_version"] != "2.9.7" or model_format != "stl" or
            any(key in payload for key in (
                "filament_profiles", "creality_model_stls", "creality_tool_ids",
                "creality_native_project", "native_modifier_project"))):
        raise WorkerError("Invalid Prusa placed-STL execution contract.")
    if ("creality_model_raw_sha256" in payload) != ("creality_placed_stl" in payload):
        raise WorkerError("Missing authenticated Creality placed STL digest.")
    creality_digest = payload.get("creality_model_raw_sha256")
    if "creality_placed_stl" in payload:
        if (payload["creality_placed_stl"] is not True
                or payload["engine"] != "crealityprint"
                or payload["engine_version"] != "7.3.1"
                or model_format != "stl"
                or not isinstance(creality_digest, str) or len(creality_digest) != 64
                or any(c not in "0123456789abcdef" for c in creality_digest)
                or any(key in payload for key in (
                    "filament_profiles", "creality_model_stls", "creality_tool_ids",
                    "creality_native_project", "native_modifier_project",
                    "orca_streamed_plate", "orca_streamed_sha256"))):
            raise WorkerError("Invalid Creality placed-STL execution contract.")
    streamed = payload.get("orca_streamed_plate") is True
    if "orca_streamed_plate" in payload or "orca_streamed_sha256" in payload:
        digest = payload.get("orca_streamed_sha256")
        if (not streamed or payload["engine"] != "orcaslicer"
                or payload["engine_version"] != "2.5.0"
                or model_format != "3mf"
                or not isinstance(digest, str) or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
                or any(key in payload for key in (
                    "filament_profiles", "creality_model_stls", "creality_tool_ids",
                    "creality_native_project", "native_modifier_project"))):
            raise WorkerError("Invalid streamed Orca plate contract.")
    native_timeout = payload.get("slice_timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if (type(native_timeout) is not int or
            not 1 <= native_timeout <= MAX_NATIVE_SLICE_TIMEOUT_SECONDS):
        raise WorkerError("Invalid native slice timeout.")
    if streamed:
        from .streamed_orca_validation import streamed_orca_memory_budget
        streamed_limit = streamed_orca_memory_budget() // 8
        if not streamed_limit:
            raise WorkerError("Insufficient worker memory for streamed Orca geometry.")
    else:
        streamed_limit = model_input_budget()
    files = {"model_format": model_format, "slice_timeout_seconds": native_timeout}
    for key, limit in (
        ("model", streamed_limit),
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
    if payload.get("creality_placed_stl") is True:
        from .stl_validation import validate_stl
        # This optional contract is only ever activated by the authenticated
        # Creality 7.3.1 single-material placed-plate request. Decompress
        # strictly to the maximum representable bounded binary STL, and
        # reject trailing streams and mismatched source digests.
        limit = min(84 + 50 * 1_500_000, model_input_budget())
        try:
            stream = zlib.decompressobj()
            original = stream.decompress(files["model"], limit + 1)
        except zlib.error as exc:
            raise WorkerError("Invalid Creality placed STL compression.") from exc
        if (not stream.eof or stream.unconsumed_tail or stream.unused_data
                or len(original) > limit or len(original) < 84
                or hashlib.sha256(original).hexdigest() != digest):
            raise WorkerError("Creality placed STL integrity or expansion check failed.")
        validate_stl(original, max_triangles=1_500_000)
        files["model"] = original
        files["creality_placed_stl"] = True
    if streamed:
        if hashlib.sha256(files["model"]).hexdigest() != payload["orca_streamed_sha256"]:
            raise WorkerError("Streamed Orca plate integrity check failed.")
        from .streamed_orca_validation import validate_streamed_orca_3mf
        validate_streamed_orca_3mf(files["model"])
        files["orca_streamed_plate"] = True
    if payload.get("prusa_placed_stl") is True:
        files["prusa_placed_stl"] = True
    if "filament_profiles" in payload:
        palette = payload["filament_profiles"]
        if (not ((payload["engine"] in {"orcaslicer", "bambustudio"} and model_format == "3mf") or
                 (payload["engine"] == "crealityprint" and (
                    (model_format == "stl" and "creality_model_stls" in payload) or
                    (model_format == "3mf" and payload.get("creality_native_project") is True))))
                or not isinstance(palette, list) or not 2 <= len(palette) <= 16):
            raise WorkerError("Multi-filament requests require native 3MF and two to sixteen presets.")
        decoded = []
        for entry in palette:
            if not isinstance(entry, str) or len(entry) > ((MAX_PROFILE_BYTES + 2)//3)*4 + 8:
                raise WorkerError("Invalid native filament palette entry.")
            try:
                raw = base64.b64decode(entry, validate=True)
            except (ValueError, base64.binascii.Error):
                raise WorkerError("Invalid native filament palette encoding.") from None
            if not raw or len(raw) > MAX_PROFILE_BYTES:
                raise WorkerError("Invalid native filament palette size.")
            decoded.append(raw)
        # A single-profile request and the first palette item must agree,
        # preventing disagreement between legacy and multi-tool contracts.
        if decoded[0] != files["filament_profile"]:
            raise WorkerError("Native filament palette does not match its first preset.")
        files["filament_profiles"] = decoded
    if "prusa_offline_mmu" in payload:
        from .prusa_offline_contract import validate_prusa_offline_mmu_inputs
        details = payload["prusa_offline_mmu"]
        receipt = validate_prusa_offline_mmu_inputs(
            project=files["model"], printer=files["printer_profile"],
            filament=files["filament_profile"], process=files["process_profile"],
            tools=details["tools"], tower=details["tower"])
        files["prusa_offline_mmu"] = {
            "tools": list(receipt["tools"]), "tower": details["tower"]}
    if "prusa_offline_xl" in payload:
        from .prusa_offline_contract import validate_prusa_offline_xl_inputs
        details = payload["prusa_offline_xl"]
        receipt = validate_prusa_offline_xl_inputs(
            project=files["model"], printer=files["printer_profile"],
            filament=files["filament_profile"], process=files["process_profile"],
            tools=details["tools"])
        files["prusa_offline_xl"] = {"tools": list(receipt["tools"])}
    if "prusa_offline_xl_colour" in payload:
        from .prusa_offline_contract import validate_prusa_offline_xl_colour_inputs
        details=payload["prusa_offline_xl_colour"]
        receipt=validate_prusa_offline_xl_colour_inputs(
            project=files["model"],printer=files["printer_profile"],
            filament=files["filament_profile"],process=files["process_profile"],
            **({"tools":details["tools"]} if "tools" in details
               else {"tool":details["tool"]}))
        files["prusa_offline_xl_colour"]={
            "tools":receipt["tools"]} if "tools" in receipt else {"tool":receipt["tool"]}
    if "prusa_offline_colour" in payload:
        from .prusa_offline_contract import validate_prusa_offline_colour_inputs
        details=payload["prusa_offline_colour"]
        receipt=validate_prusa_offline_colour_inputs(
            project=files["model"],printer=files["printer_profile"],
            filament=files["filament_profile"],process=files["process_profile"],
            **({"tools":details["tools"]} if "tools" in details
               else {"tool":details["tool"]}),tower=details["tower"])
        files["prusa_offline_colour"]={
            **({"tools":receipt["tools"]} if "tools" in receipt
               else {"tool":receipt["tool"]}),"tower":receipt["tower"]}
    if "creality_model_stls" in payload:
        if (payload["engine"] != "crealityprint" or model_format != "stl" or
                "filament_profiles" not in files):
            raise WorkerError("Creality multi-STL requires a native filament palette.")
        stls = payload["creality_model_stls"]
        tools = payload.get("creality_tool_ids")
        if (not isinstance(stls, list) or not 2 <= len(stls) <= 12 or
                not isinstance(tools, list) or len(tools) != len(stls) or
                any(type(tool) is not int or not 1 <= tool <= len(files["filament_profiles"])
                    for tool in tools) or len(set(tools)) < 2):
            raise WorkerError("Invalid Creality multi-STL model/tool mapping.")
        decoded = []
        for entry in stls:
            if not isinstance(entry, str) or len(entry) > ((MAX_MODEL_BYTES + 2)//3)*4 + 8:
                raise WorkerError("Invalid Creality multi-STL model size.")
            try:
                raw = base64.b64decode(entry, validate=True)
            except (ValueError, base64.binascii.Error):
                raise WorkerError("Invalid Creality multi-STL model encoding.") from None
            if not raw or len(raw) > MAX_MODEL_BYTES:
                raise WorkerError("Invalid Creality multi-STL model size.")
            from .stl_validation import validate_stl
            validate_stl(raw)
            decoded.append(raw)
        if decoded[0] != files["model"]:
            raise WorkerError("Creality first model does not match job input.")
        files["creality_model_stls"] = decoded
        files["creality_tool_ids"] = tools
    elif "creality_tool_ids" in payload:
        raise WorkerError("Creality tool assignments require native STL models.")
    if "native_modifier_project" in payload:
        # This is a distinct single-material contract. Neither a 2+ tool
        # palette nor an arbitrary uploaded native project can request it.
        approved = {"orcaslicer": "2.5.0", "bambustudio": "02.09.01.70",
                    "crealityprint": "7.3.1"}
        if (payload["native_modifier_project"] is not True
                or approved.get(payload["engine"]) != payload["engine_version"]
                or model_format != "3mf"
                or any(key in payload for key in (
                    "filament_profiles", "creality_native_project",
                    "creality_model_stls", "creality_tool_ids"))):
            raise WorkerError("Unverified modifier project execution contract.")
        if payload["engine"] == "crealityprint":
            from .creality_modifier_validation import validate_creality_modifier_project
            validate_creality_modifier_project(files["model"])
        else:
            validate_worker_3mf(files["model"], allow_native_modifier_fixture=True)
        files["native_modifier_project"] = True
    if "creality_native_project" in payload:
        if (payload["creality_native_project"] is not True or
                payload["engine"] != "crealityprint" or model_format != "3mf" or
                len(files.get("filament_profiles", [])) != 2 or
                "creality_model_stls" in payload or "creality_tool_ids" in payload):
            raise WorkerError("Invalid Creality project slicing contract.")
        from .creality_project_validation import validate_creality_project
        validate_creality_project(files["model"], native_tool_count=2)
        files["creality_native_project"] = True
    elif model_format == "3mf" and payload["engine"] == "prusaslicer":
        if not (files.get("prusa_offline_mmu") or files.get("prusa_offline_xl") or files.get("prusa_offline_colour") or
                files.get("prusa_offline_xl_colour")):
            from .prusa_3mf_validation import validate_prusa_native_3mf
            validate_prusa_native_3mf(files["model"])
    elif model_format == "3mf" and not files.get("native_modifier_project") and not streamed:
        options = {"native_tool_count": len(files["filament_profiles"])
                   if "filament_profiles" in files else None}
        if payload["engine"] == "bambustudio":
            options["allow_bambu_project"] = True
            if "filament_profiles" in files:
                options["allow_bambu_combined_paint"] = True
                options["allow_bambu_layer_ranges"] = True
        validate_worker_3mf(files["model"], **options)
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
        request_limit = max(MAX_REQUEST_BYTES, model_input_budget() * 2 + 12 * 1024 * 1024)
        if self.headers.get("X-MakerVault-Streamed-Orca") == "v1":
            from .streamed_orca_validation import streamed_orca_memory_budget
            request_limit = max(0, streamed_orca_memory_budget() // 6 + 4 * 1024 * 1024)
        if not 0 < length <= request_limit:
            return self._json(413, {"error": "Invalid or oversized request."})
        if not SLICE_SLOT.acquire(blocking=False):
            return self._json(429, {"error": "Worker is already processing a slice."})
        stage = "validating request"
        try:
            self.connection.settimeout(30)
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict):
                raise WorkerError("Job request must be a JSON object.")
            current = engines.get(request.get("engine"))
            if not current or request.get("engine_version") != current["version"]:
                raise WorkerError("Requested engine/version is unavailable.")
            stage = "validating model and profile payloads"
            files = _decode_payload(request)
            if ((self.headers.get("X-MakerVault-Streamed-Orca") == "v1")
                    != bool(files.get("orca_streamed_plate"))):
                raise WorkerError("Unverified streamed Orca request envelope.")
            with tempfile.TemporaryDirectory(prefix="makervault-slice-") as tmp:
                workdir = Path(tmp)
                extension = ".json" if current["engine"] in {"orcaslicer", "crealityprint", "bambustudio"} else ".ini"
                for field, name in (
                    ("model", "input." + files["model_format"]), ("printer_profile", "printer" + extension),
                    ("filament_profile", "filament" + extension),
                    ("process_profile", "process" + extension),
                ):
                    (workdir / name).write_bytes(files[field])
                if "filament_profiles" in files:
                    for index, native in enumerate(files["filament_profiles"]):
                        (workdir / ("filament-" + str(index) + ".json")).write_bytes(native)
                if files.get("creality_native_project"):
                    (workdir / "creality-native-project.marker").write_text("v1")
                if files.get("native_modifier_project"):
                    (workdir / "native-modifier-project.marker").write_text("v1")
                if files.get("creality_placed_stl"):
                    (workdir / "creality-placed-stl.marker").write_text("v1")
                if files.get("orca_streamed_plate"):
                    (workdir / "orca-streamed-plate.marker").write_text("v1")
                if files.get("prusa_placed_stl"):
                    (workdir / "prusa-placed-stl.marker").write_text("v1")
                if files.get("prusa_offline_mmu"):
                    (workdir / "prusa-offline-mmu.marker").write_text("v1")
                if files.get("prusa_offline_xl"):
                    (workdir / "prusa-offline-xl.marker").write_text("v1")
                if files.get("prusa_offline_colour"):
                    (workdir / "prusa-offline-colour.marker").write_text("v1")
                if files.get("prusa_offline_xl_colour"):
                    (workdir / "prusa-offline-xl-colour.marker").write_text("v1")

                if "creality_model_stls" in files:
                    for index, raw in enumerate(files["creality_model_stls"]):
                        (workdir / ("input-" + str(index) + ".stl")).write_bytes(raw)
                    (workdir / "creality-material-map.json").write_text(
                        json.dumps({"model_count": len(files["creality_model_stls"]),
                                    "filament_count": len(files["filament_profiles"]),
                                    "tool_ids": files["creality_tool_ids"]}))
                stage = "running slicer engine"
                runner = {"orcaslicer": run_orca,
                          "crealityprint": run_creality,
                          "prusaslicer": run_prusa,
                          "bambustudio": run_bambu}[current["engine"]]
                if (current["engine"] == "prusaslicer" and
                        (files.get("prusa_offline_mmu") or
                         files.get("prusa_offline_colour"))):
                    from .prusa_gcode_audit import run_prusa_mmu_with_numeric_recheck
                    receipt, data = run_prusa_mmu_with_numeric_recheck(
                        runner, current["binary"], workdir,
                        timeout_seconds=files["slice_timeout_seconds"],
                        max_bytes=gcode_output_budget())
                else:
                    receipt = runner(current["binary"], workdir,
                                     timeout_seconds=files["slice_timeout_seconds"])
                    data = (workdir / "output.gcode").read_bytes()
                    if not data or len(data) > gcode_output_budget():
                        raise WorkerError("Generated G-code exceeded the output size limit.")
                stage = "validating generated G-code"
                if current["engine"] == "prusaslicer":
                    from .prusa_gcode_audit import audit_prusa_positive_e
                    audit_prusa_positive_e(data)
                if files.get("prusa_offline_mmu"):
                    from .prusa_material_gcode_audit import audit_prusa_material_model_gcode
                    details = files["prusa_offline_mmu"]
                    audit_prusa_material_model_gcode(
                        data, files["model"], printer_ini=files["printer_profile"],
                        tools=details["tools"], tower=details["tower"],
                        process_ini=files["process_profile"])
                if files.get("prusa_offline_colour"):
                    from .prusa_colour_gcode_audit import audit_prusa_offline_colour_gcode
                    details=files["prusa_offline_colour"]
                    if "tools" in details:
                        from .prusa_colour_gcode_audit import audit_prusa_dual_colour_gcode
                        audit_prusa_dual_colour_gcode(
                            data,files["model"],printer_ini=files["printer_profile"],
                            tools=details["tools"],tower=details["tower"])
                    else:
                        audit_prusa_offline_colour_gcode(
                            data,files["model"],printer_ini=files["printer_profile"],
                            tool=details["tool"],tower=details["tower"])
                if files.get("prusa_offline_xl_colour"):
                    details=files["prusa_offline_xl_colour"]
                    if "tools" in details:
                        from .prusa_colour_gcode_audit import audit_prusa_dual_colour_gcode
                        audit_prusa_dual_colour_gcode(
                            data,files["model"],printer_ini=files["printer_profile"],
                            tools=details["tools"],tower=None)
                    else:
                        from .prusa_colour_gcode_audit import audit_prusa_xl_colour_gcode
                        audit_prusa_xl_colour_gcode(
                            data,files["model"],printer_ini=files["printer_profile"],
                            tool=details["tool"])
                if files.get("prusa_offline_xl"):
                    from .prusa_material_gcode_audit import audit_prusa_material_model_gcode
                    audit_prusa_material_model_gcode(
                        data, files["model"], printer_ini=files["printer_profile"],
                        tools=files["prusa_offline_xl"]["tools"],
                        process_ini=files["process_profile"])
                if files.get("native_modifier_project"):
                    # A successful native CLI exit is not proof that every
                    # requested region was used in the generated toolpaths.
                    from .modifier_gcode_audit import audit_modifier_positive_e
                    translation_xy = (0.0, 0.0)
                    if current["engine"] == "bambustudio":
                        from .bambu_runner import verified_bambu_modifier_shift
                        translation_xy = verified_bambu_modifier_shift(
                            files["model"], workdir / "bambu-sliced.3mf")
                    audit_modifier_positive_e(
                        data, files["model"], current["engine"],
                        translation_xy=translation_xy)
                if "filament_profiles" in files:
                    expected = (set(tool - 1 for tool in files["creality_tool_ids"])
                                if "creality_tool_ids" in files
                                else expected_native_tools(files["model"]))
                    verify_multi_material_output(data, expected)
                return self._json(200, {
                    "status": "completed", "bytes": receipt["bytes"],
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "gcode": base64.b64encode(data).decode("ascii"),
                })
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError, WorkerError) as exc:
            # Only report a bounded diagnostic category, never command output,
            # profile JSON, private paths, bearer tokens or source filenames.
            safe_reasons = {
                "Invalid Creality modifier upload size.": "creality-region-archive-invalid",
                "Unsafe Creality modifier XML declaration.": "creality-region-archive-invalid",
                "Malformed native Creality modifier XML.": "creality-region-archive-invalid",
                "Invalid native Creality modifier object identity.": "creality-region-graph-invalid",
                "Unsafe Creality modifier relationship.": "creality-region-graph-invalid",
                "Unsupported external modifier mesh relationship.": "creality-region-graph-invalid",
                "Invalid Creality native modifier model.": "creality-region-graph-invalid",
                "Unexpected modifier mesh units.": "creality-region-graph-invalid",
                "Invalid native Creality model generator.": "creality-region-graph-invalid",
                "Nonprinting modifier may not enter the build.": "creality-region-graph-invalid",
                "Invalid Creality modifier project identity.": "creality-region-metadata-invalid",
                "Unapproved Creality modifier project version.": "creality-region-metadata-invalid",
                "Unsafe native modifier metadata.": "creality-region-metadata-invalid",
                "Unexpected Creality modifier material tool.": "creality-region-metadata-invalid",
                "Unexpected Creality modifier settings entry.": "creality-region-metadata-invalid",
                "Unsafe Creality modifier plate.": "creality-region-metadata-invalid",
                "Unapproved Creality modifier plate setting.": "creality-region-metadata-invalid",
                "Invalid modifier target plate object.": "creality-region-metadata-invalid",
                "Unsafe Creality modifier plate item.": "creality-region-metadata-invalid",
                "Creality modifier native settings exceed nesting limit.": "creality-region-profiles-invalid",
                "Oversized native modifier project settings.": "creality-region-profiles-invalid",
                "Unsafe native modifier project setting.": "creality-region-profiles-invalid",
                "Oversized native modifier settings vector.": "creality-region-profiles-invalid",
                "Invalid native modifier project value.": "creality-region-profiles-invalid",
                "Oversized native modifier project field.": "creality-region-profiles-invalid",
                # Fixed worker-authored error strings only: never echo raw
                # native 3MF/project contents or private preset data.
                "Unsafe Creality modifier project archive.": "creality-region-archive-invalid",
                "Invalid Creality native modifier parent.": "creality-region-graph-invalid",
                "Invalid native external modifier object graph.": "creality-region-graph-invalid",
                "Unsafe Creality modifier external link.": "creality-region-graph-invalid",
                "Unsafe external modifier mesh identity.": "creality-region-graph-invalid",
                "Invalid external modifier mesh count.": "creality-region-graph-invalid",
                "Creality modifier part count mismatch.": "creality-region-parts-invalid",
                "Creality native region part type mismatch.": "creality-region-parts-invalid",
                "Unexpected Creality modifier settings sections.": "creality-region-metadata-invalid",
                "Creality modifier source object mapping is invalid.": "creality-region-metadata-invalid",
                "Creality modifier native metadata owner mismatch.": "creality-region-metadata-invalid",
                "Invalid native modifier profile vector.": "creality-region-profiles-invalid",
                "Invalid Creality modifier native palette.": "creality-region-profiles-invalid",
                "Unapproved native modifier process settings.": "creality-region-profiles-invalid",
                "Malformed Creality native modifier archive.": "creality-region-archive-invalid",
                "Invalid native region part-to-component mapping.": "creality-region-parts-invalid",
                "Unsafe native region component graph.": "creality-region-graph-invalid",

                "Generated G-code deposits material inside a requested negative volume.": "native-negative-deposition",
                "Requested native modifier has no model deposition in the generated G-code.": "native-modifier-no-deposition",
                "Unable to audit native modifier geometry.": "native-region-geometry-invalid",
                "Invalid Creality Print JSON profile.": "creality-profile-json-invalid",
                "Creality Print profile requires a self-contained, verified native preset.": "creality-profile-parent-unresolved",
                "Creality Print profile nesting exceeds the limit.": "creality-profile-structure-invalid",
                "Creality Print profile has too many properties.": "creality-profile-structure-invalid",
                "Creality Print profile contains too many entries.": "creality-profile-structure-invalid",
                "Creality Print native profile includes a blocked post-processing command.": "creality-post-processing-blocked",
                "Unsafe native profile setting.": "unsafe-profile-settings",
                "Verified Creality Print executable is unavailable.": "creality-engine-unavailable",
                "Creality Print output directory must not exist yet.": "creality-output-path-conflict",
                "Creality Print did not complete the CLI slice in time.": "creality-cli-timeout",
                "Creality Print failed to slice using the selected native profiles.": "creality-cli-exited",
                "Creality Print CLI could not initialise its headless Qt platform.": "creality-qt-platform-failed",
                "Creality Print CLI is missing a runtime library.": "creality-runtime-library-missing",
                "Creality Print CLI rejected a command-line option.": "creality-cli-option-invalid",
                "Creality Print CLI rejected its command-line parameters.": "creality-cli-parameters-invalid",
                "Creality Print CLI received conflicting commands.": "creality-cli-command-conflict",
                "Creality Print CLI did not recognise a slicing command.": "creality-cli-command-missing",
                "Creality Print CLI could not load a native preset.": "creality-native-preset-invalid",
                "Creality Print rejected its embedded 3MF project configuration.": "creality-native-project-invalid",
                "Creality Print rejected the 3MF project file version.": "creality-project-version-unsupported",
                "Creality Print rejected native 3MF slicing parameters during validation.": "creality-cli-validation-error",
                "Creality Print produced no safe output directory.": "creality-no-output-directory",
                "Creality Print did not produce exactly one supported G-code artifact.": "creality-unexpected-output-layout",
                "Creality Print G-code output is empty or oversized.": "creality-missing-gcode",
                "Creality Print output exceeds the G-code limit.": "output-too-large",
                "Creality Print produced unsupported binary G-code.": "invalid-gcode",
                "Creality Print worker could not launch the approved binary.": "creality-launch-failed",
                "OrcaSlicer failed. Check the engine-native profiles.": "engine-exited",
                "Reviewed Bambu Studio executable is unavailable.": "engine-unavailable",
                "Bambu Studio CLI rejected the native profiles or model.": "bambu-cli-exited",
                "Bambu Studio native runtime exited with status 126.": "bambu-runtime-exit-126",
                "Bambu Studio native CLI aborted with SIGABRT.": "bambu-cli-aborted",
                "Bambu generated unsupported binary or empty G-code.": "invalid-gcode",
                "Bambu native output must contain exactly one G-code plate.": "unexpected-output-layout",
                "Bambu native output includes an unexpected G-code plate.": "unexpected-output-layout",
                "Bambu combined painting needs an exact native project palette.": "validation-error",
                "Bambu multi-material 3MF requires native project settings.": "validation-error",
                "Bambu project settings require a bounded native palette.": "validation-error",
                "Unsafe Bambu project setting keys.": "validation-error",
                "Missing Bambu native preset identity.": "validation-error",
                "Bambu project palette does not match the native tool count.": "validation-error",
                "Invalid Bambu project filament colour.": "validation-error",
                "Invalid Bambu project nozzle diameter.": "validation-error",
                "Isolated worker could not execute Bambu Studio.": "engine-launch-failed",
                "Orca profile requires an unbundled parent preset; use a verified complete native profile bundle.": "unresolved-profile-parent",
                "OrcaSlicer produced no safe output directory.": "no-output-directory",
                "OrcaSlicer must produce exactly one G-code plate and only expected metadata.": "unexpected-output-layout",
                "Generated G-code exceeded the output size limit.": "output-too-large",
                "Requested engine/version is unavailable.": "engine-version-mismatch",
                "OrcaSlicer output is missing or exceeds its limit.": "missing-gcode",
                "Invalid native Orca JSON profile.": "invalid-profile-json",
                "Orca profile must be a JSON object.": "invalid-profile-json",
                "Native Orca profile nesting exceeds its limit.": "invalid-profile-structure",
                "Native Orca profile contains too many entries.": "invalid-profile-structure",
                "Unsafe Orca profile command or network setting.": "unsafe-profile-settings",
                "Approved OrcaSlicer binary is unavailable.": "engine-unavailable",
                "Invalid slicing job payload.": "invalid-job-payload",
                "Invalid job identifier.": "invalid-job-payload",
                "Unsupported isolated worker engine.": "engine-version-mismatch",
                "Unsupported model input format.": "unsupported-input-format",
                "Oversized or invalid slicing input.": "input-size-invalid",
                "Invalid slicing input encoding.": "input-encoding-invalid",
                "Invalid slicing input size.": "input-size-invalid",
                "Multi-filament requests require Orca 3MF and two to sixteen presets.": "native-palette-contract-invalid",
                "Creality multi-STL requires a native filament palette.": "native-palette-contract-invalid",
                "Invalid Creality multi-STL model/tool mapping.": "native-tool-use-mismatch",
                "Invalid Creality multi-STL model size.": "input-size-invalid",
                "Invalid Creality multi-STL model encoding.": "input-encoding-invalid",
                "Creality first model does not match job input.": "invalid-job-payload",
                "Creality tool assignments require native STL models.": "native-palette-contract-invalid",
                "Invalid native Creality multi-STL filament assignment.": "native-tool-use-mismatch",
                "Creality multi-STL material assignments cannot use 3MF.": "native-palette-contract-invalid",
                "Invalid native filament palette entry.": "native-palette-entry-invalid",
                "Invalid native filament palette encoding.": "native-palette-encoding-invalid",
                "Invalid native filament palette size.": "native-palette-size-invalid",
                "Job request must be a JSON object.": "invalid-job-payload",
                "Input STL failed structural validation.": "invalid-stl",
                "Slicing timed out.": "engine-timeout",
                "OrcaSlicer produced unsupported binary G-code.": "invalid-gcode",
                "G-code exceeded size limit.": "output-too-large",
                "Isolated worker could not run OrcaSlicer.": "engine-launch-failed",
                "Modifier fixtures cannot activate other native project extensions.": "invalid-3mf",
                "3MF input exceeds worker limits.": "invalid-3mf",
                "3MF triangle count exceeds worker limit.": "invalid-3mf",
                "3MF vertex count exceeds worker limit.": "invalid-3mf",
                "3MF package contents are not bounded.": "invalid-3mf",
                "Bambu project is missing a valid printable height.": "invalid-native-project-settings",
                "Invalid Bambu native filament IDs.": "invalid-native-project-settings",
                "Bambu filament support vector does not match the palette.": "invalid-native-project-settings",
                "Bambu native material vector does not match variants.": "invalid-native-project-settings",
                "Bambu variable layers require an exact native palette.": "invalid-native-layer-settings",
                "Unsafe Bambu native material vector.": "invalid-native-project-settings",
                "Bambu native project does not match the selected filament profiles.": "native-filament-palette-mismatch",
                "Invalid Bambu filament extruder variants.": "invalid-native-project-settings",
                "Invalid Bambu filament self-index.": "invalid-native-project-settings",
                "Bambu filament variant mapping is inconsistent.": "invalid-native-project-settings",
                "3MF archive expansion exceeds the limit.": "invalid-3mf",
                "Unsupported 3MF package members.": "invalid-3mf",
                "Unsupported native 3MF triangle attributes.": "unsupported-native-facet-attributes",
                "Unsupported native painted facet annotation.": "invalid-native-paint-facets",
                "Combined native painting is not verified.": "combined-native-paint-not-supported",
                "Combining seam and support paint is not verified.": "combined-native-paint-not-supported",
                "Creality multi-channel painting needs a single object.": "combined-native-paint-not-supported",
                "Creality painting extensions need exactly two native tools.": "native-palette-contract-invalid",
                "Native variable layer test requires an approved single object.": "native-multimaterial-variable-layers-unsupported",
                "Invalid 3MF project geometry.": "invalid-3mf",
                "Malformed native 3MF plate manifest.": "invalid-3mf",
                "Unsupported native 3MF plate manifest.": "invalid-3mf",
                "Multi-object 3MF requires explicit native plate membership.": "invalid-3mf",
                "3MF plate membership does not match mesh objects.": "invalid-3mf",
                "3MF transform is missing or invalid.": "invalid-3mf",
                "Every native object must select a tool and two native tools must be used.": "native-tool-use-mismatch",
                "Painted colour refers to an unavailable native filament.": "native-paint-tool-out-of-range",
                "Colour painting requires verified native multi-tool slicing.": "native-paint-channel-conflict",
                "Native object extruder.": "native-object-tool-invalid",
                "Invalid native object extruder.": "native-object-tool-invalid",
                "Multi-filament 3MF requires native object assignments.": "native-object-tool-missing",
                "Native filament palette does not match its first preset.": "native-filament-palette-mismatch",
                "Multi-filament palette does not match the native 3MF job.": "native-filament-palette-mismatch",
                "Non-contiguous native filament palette.": "native-filament-palette-mismatch",
                "Invalid native object value.": "native-object-settings-invalid",
                "Unsupported per-object slicer setting.": "native-object-settings-invalid",
                "Invalid native plate instance identity.": "native-plate-instance-invalid",
                "Invalid native filament tool count.": "native-filament-palette-mismatch",
                "Native layer range metadata is oversized.": "invalid-native-layer-ranges",
                "3MF plate metadata is oversized.": "invalid-native-plate",
                "Unexpected 3MF namespace.": "invalid-3mf",
                "3MF build must contain one to 200 objects.": "invalid-3mf",
                "3MF build references unknown objects.": "invalid-3mf",
                "Native variable layer test requires one single-material object.": "native-multimaterial-variable-layers-unsupported",
                "Malformed native variable layer configuration.": "invalid-native-layer-ranges",
                "Unexpected native variable layer structure.": "invalid-native-layer-ranges",
                "Variable layer object does not match native mesh.": "invalid-native-layer-ranges",
                "Invalid native variable layer band count.": "invalid-native-layer-ranges",
                "Unsupported native layer range.": "invalid-native-layer-ranges",
                "Unsupported native layer range setting.": "invalid-native-layer-ranges",
                "Invalid native layer range value.": "invalid-native-layer-ranges",
                "Unsafe native variable layer range.": "invalid-native-layer-ranges",
                "3MF build contains empty objects.": "invalid-3mf",
                "3MF vertex coordinates are invalid.": "invalid-3mf",
                "3MF contains unsafe geometry.": "invalid-3mf",
                "Invalid per-object 3MF settings identity.": "native-object-settings-invalid",
                "Invalid per-object settings count.": "native-object-settings-invalid",
                "Unsafe per-object 3MF metadata.": "native-object-settings-invalid",
                "Duplicate native extruder assignment.": "native-object-tool-invalid",
                "Unsafe native object value.": "native-object-settings-invalid",
                "Native object integer value required.": "native-object-settings-invalid",
                "Unknown native 3MF metadata.": "native-object-settings-invalid",
                "Exactly one final native plate mapping is required.": "invalid-native-plate",
                "Unexpected 3MF plate mapping.": "invalid-native-plate",
                "3MF does not target exactly one plate.": "invalid-native-plate",
                "Invalid 3MF native plate instance.": "native-plate-instance-invalid",
                "Unsafe 3MF plate metadata.": "invalid-native-plate",
                "3MF transform is unsafe.": "invalid-3mf",
                "Multi-filament 3MF object lacks an extruder.": "native-object-tool-missing",
                "Invalid native painted tool state.": "native-paint-tool-out-of-range",
                "Invalid multi-material output.": "invalid-gcode",
                "Missing multi-material verification targets.": "native-tool-use-mismatch",
                "Multi-material G-code is not valid UTF-8.": "invalid-gcode",
                "Native output lacks required filament changes and deposited extrusion.": "native-gcode-tools-missing",
                "Native object percent unit is missing.": "native-object-settings-invalid",
            }
            if str(exc).startswith("OrcaSlicer CLI exited: "):
                candidate = str(exc).removeprefix("OrcaSlicer CLI exited: ").removesuffix(".")
                categories = {
                    "qt-platform-failed", "missing-runtime-library", "appimage-runtime-failed",
                    "unsupported-cli-option", "native-profile-load-failed", "engine-exited",
                    "native-project-settings-invalid", "native-project-load-failed",
                    "cli-validation-exit-238", "cli-validation-exit-239",
                    "cli-print-validation-exit-205", "native-line-width-invalid",
                }
                reason = candidate if candidate in categories else "engine-exited"
            else:
                reason = safe_reasons.get(str(exc), "validation-error")
            # For an otherwise unclassified worker admission error, record
            # only a bounded, code-owned source location. Never log exception
            # text, native project data, file paths, profiles or CLI output.
            if (stage == "validating model and profile payloads" and reason in {"validation-error", "creality-region-profiles-invalid"}):
                origin = None
                tb = exc.__traceback__
                while tb is not None:
                    code = tb.tb_frame.f_code
                    candidate = (code.co_filename.rsplit("/", 1)[-1], code.co_name, tb.tb_lineno)
                    if candidate[0] in {
                        "creality_modifier_validation.py",
                        "modifier_3mf_validation.py",
                        "three_mf_validation.py",
                    }:
                        origin = candidate
                    tb = tb.tb_next
                if origin is not None:
                    logger.warning("Native project admission diagnostic: module=%s function=%s line=%d",
                                   *origin)
            logger.warning("Isolated slicer rejected job at %s (%s, %s)", stage,
                           type(exc).__name__, reason)
            response = {
                "error": "Slicing input or output was rejected.",
                "stage": stage, "reason": reason,
            }
            # Safe machine-readable status only; never return raw engine logs,
            # CLI arguments, local paths, profile content or credentials.
            cli_exit_code = getattr(exc, "cli_exit_code", None)
            if (stage == "running slicer engine"
                    and type(cli_exit_code) is int and 1 <= cli_exit_code <= 255
                    and reason.startswith("creality-")):
                response["cli_exit_code"] = cli_exit_code
                topic = getattr(exc, "cli_validation_category", None)
                if (cli_exit_code == 205
                        and reason == "creality-cli-validation-error"
                        and topic in {
                            "prime-tower", "layer-height", "line-width",
                            "nozzle", "flow", "filament", "supports",
                            "build-plate",
                        }):
                    response["validation_category"] = topic
            if reason == "native-project-settings-invalid":
                keys = getattr(exc, "option_keys", ())
                if isinstance(keys, (list, tuple)):
                    import re
                    safe = [key for key in keys[:8]
                            if isinstance(key, str) and re.fullmatch(r"[a-z][a-z0-9_]{1,63}", key)
                            and not any(word in key for word in (
                                "secret", "password", "token", "apikey", "api_key",
                                "authorization", "credential", "private", "access_key"
                            ))]
                    if safe:
                        response["setting_keys"] = list(dict.fromkeys(safe))
            return self._json(422, response)
        except OSError as exc:
            logger.exception("Isolated slicer filesystem failure at %s", stage)
            return self._json(500, {
                "error": "Worker failed to process the slicing job.",
                "stage": stage,
            })
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
