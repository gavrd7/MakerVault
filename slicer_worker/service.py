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

from .runner import MAX_GCODE_BYTES, MAX_MODEL_BYTES, MAX_PROFILE_BYTES, WorkerError, run_prusa
from .orca_runner import run_orca
from .creality_runner import run_creality
from .engine_registry import configured_engines
from .three_mf_validation import validate_worker_3mf
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
            set(payload) - expected - {"model_format", "filament_profiles", "creality_model_stls", "creality_tool_ids", "creality_native_project"}):
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
    if "filament_profiles" in payload:
        palette = payload["filament_profiles"]
        if (not ((payload["engine"] == "orcaslicer" and model_format == "3mf") or
                 (payload["engine"] == "crealityprint" and (
                    (model_format == "stl" and "creality_model_stls" in payload) or
                    (model_format == "3mf" and payload.get("creality_native_project") is True))))
                or not isinstance(palette, list) or not 2 <= len(palette) <= 16):
            raise WorkerError("Multi-filament requests require Orca 3MF and two to sixteen presets.")
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
    if "creality_native_project" in payload:
        if (payload["creality_native_project"] is not True or
                payload["engine"] != "crealityprint" or model_format != "3mf" or
                len(files.get("filament_profiles", [])) != 2 or
                "creality_model_stls" in payload or "creality_tool_ids" in payload):
            raise WorkerError("Invalid Creality project slicing contract.")
        from .creality_project_validation import validate_creality_project
        validate_creality_project(files["model"], native_tool_count=2)
        files["creality_native_project"] = True
    elif model_format == "3mf":
        validate_worker_3mf(files["model"],
            native_tool_count=len(files["filament_profiles"])
                if "filament_profiles" in files else None)
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
            with tempfile.TemporaryDirectory(prefix="makervault-slice-") as tmp:
                workdir = Path(tmp)
                extension = ".json" if current["engine"] in {"orcaslicer", "crealityprint"} else ".ini"
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
                          "prusaslicer": run_prusa}[current["engine"]]
                receipt = runner(current["binary"], workdir)
                stage = "validating generated G-code"
                data = (workdir / "output.gcode").read_bytes()
                if not data or len(data) > MAX_OUTPUT_BYTES:
                    raise WorkerError("Generated G-code exceeded the output size limit.")
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
                "3MF input exceeds worker limits.": "invalid-3mf",
                "3MF triangle count exceeds worker limit.": "invalid-3mf",
                "3MF vertex count exceeds worker limit.": "invalid-3mf",
                "3MF package contents are not bounded.": "invalid-3mf",
                "3MF archive expansion exceeds the limit.": "invalid-3mf",
                "Unsupported 3MF package members.": "invalid-3mf",
                "Unsupported native 3MF triangle attributes.": "unsupported-native-facet-attributes",
                "Unsupported native painted facet annotation.": "invalid-native-paint-facets",
                "Combined native painting is not verified.": "combined-native-paint-not-supported",
                "Combining seam and support paint is not verified.": "combined-native-paint-not-supported",
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
                "3MF build must contain one to twelve objects.": "invalid-3mf",
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
