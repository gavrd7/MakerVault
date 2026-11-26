"""Bounded authenticated transport to the opt-in isolated slicer worker.

This transport is not a Celery task or a job dispatcher. Neither filenames nor
engine command line arguments cross the API. Only the server's fixed worker
URL/token environment settings may select a remote destination.
"""
import base64
import hashlib
import json
import math
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
        supported.add("bambustudio")
        engines = {}
        if isinstance(payload.get("engines"), dict) and len(payload["engines"]) <= len(supported):
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


def run_remote_job(job_id, engine, version, model, printer_profile, filament_profile, process_profile, *, timeout_seconds=900, model_format="stl", filament_profiles=None,
                   creality_model_stls=None, creality_tool_ids=None,
                   creality_native_project=False, native_modifier_project=False, prusa_placed_stl=False,
                   prusa_offline_mmu=None, prusa_offline_xl=None,
                   prusa_offline_colour=None):
    if model_format not in {"stl", "3mf"}:
        raise SlicerWorkerError("Unsupported slicer input format.")
    if not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 900:
        raise SlicerWorkerError("Invalid slicing timeout.")
    supported = {"orcaslicer", "crealityprint", "prusaslicer"}
    supported.add("bambustudio")
    if (engine not in supported or not isinstance(version, str)
            or not version or len(version) > 80
            or (engine == "bambustudio" and version != "02.09.01.70")):
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
    if prusa_offline_xl is not None:
        if (engine != "prusaslicer" or version != "2.9.7" or
                model_format != "3mf" or not isinstance(prusa_offline_xl, dict)
                or set(prusa_offline_xl) != {"tools"} or
                prusa_offline_mmu is not None or
                prusa_offline_colour is not None or
                any((filament_profiles is not None, creality_model_stls is not None,
                     creality_tool_ids is not None, creality_native_project,
                     native_modifier_project, prusa_placed_stl))):
            raise SlicerWorkerError("Invalid offline Prusa XL worker contract.")
        tools=prusa_offline_xl["tools"]
        if (not isinstance(tools,(tuple,list)) or not 2<=len(tools)<=5 or
                any(type(t) is not int or not 1<=t<=5 for t in tools)
                or len(set(tools))<2):
            raise SlicerWorkerError("Invalid offline Prusa XL material tool selection.")
        payload["prusa_offline_xl"]={"tools":list(tools)}
    if prusa_offline_mmu is not None:
        if (engine != "prusaslicer" or version != "2.9.7" or
                model_format != "3mf" or not isinstance(prusa_offline_mmu, dict)
                or set(prusa_offline_mmu) != {"tools", "tower"}
                or prusa_offline_xl is not None
                or prusa_offline_colour is not None
                or any((filament_profiles is not None, creality_model_stls is not None,
                        creality_tool_ids is not None, creality_native_project,
                        native_modifier_project, prusa_placed_stl))):
            raise SlicerWorkerError("Invalid offline Prusa MMU worker contract.")
        tools = prusa_offline_mmu["tools"]
        tower = prusa_offline_mmu["tower"]
        if (not isinstance(tools, (tuple,list)) or not 2 <= len(tools) <= 5
                or any(type(v) is not int or not 1 <= v <= 5 for v in tools)
                or len(set(tools)) < 2 or
                not isinstance(tower, (tuple,list)) or len(tower) != 5
                or any(type(v) not in (int,float) or not math.isfinite(v)
                       for v in tower)):
            raise SlicerWorkerError("Invalid offline Prusa MMU material and tower mapping.")
        payload["prusa_offline_mmu"] = {"tools": list(tools), "tower": list(tower)}
    if prusa_offline_colour is not None:
        if (engine!="prusaslicer" or version!="2.9.7" or
                model_format!="3mf" or not isinstance(prusa_offline_colour,dict)
                or set(prusa_offline_colour)!={"tool","tower"}
                or prusa_offline_mmu is not None or prusa_offline_xl is not None
                or any((filament_profiles is not None, creality_model_stls is not None,
                        creality_tool_ids is not None, creality_native_project,
                        native_modifier_project, prusa_placed_stl))):
            raise SlicerWorkerError("Invalid offline Prusa colour worker contract.")
        tool=prusa_offline_colour["tool"]
        tower=prusa_offline_colour["tower"]
        if (type(tool) is not int or not 1<=tool<=4 or
                not isinstance(tower,(tuple,list)) or len(tower)!=5 or
                any(type(v) not in (int,float) or not math.isfinite(v)
                    for v in tower)):
            raise SlicerWorkerError("Invalid offline Prusa painted tool or tower.")
        payload["prusa_offline_colour"]={"tool":tool,"tower":list(tower)}
    if prusa_placed_stl:
        if (prusa_placed_stl is not True or engine != "prusaslicer"
                or version != "2.9.7" or model_format != "stl"
                or filament_profiles is not None or native_modifier_project
                or creality_native_project or creality_model_stls is not None
                or creality_tool_ids is not None):
            raise SlicerWorkerError("Unverified Prusa placed-STL execution contract.")
        payload["prusa_placed_stl"] = True
    if native_modifier_project:
        approved = {"orcaslicer": "2.5.0",
                    "bambustudio": "02.09.01.70",
                    "crealityprint": "7.3.1"}
        if (native_modifier_project is not True or model_format != "3mf"
                or approved.get(engine) != version
                or filament_profiles is not None
                or creality_native_project or creality_model_stls is not None
                or creality_tool_ids is not None):
            raise SlicerWorkerError("Unverified native modifier execution contract.")
        payload["native_modifier_project"] = True
    if filament_profiles is not None:
        if (not ((engine in {"orcaslicer", "bambustudio"} and model_format == "3mf") or
                 (engine == "crealityprint" and
                  ((model_format == "stl" and creality_model_stls is not None) or
                   (model_format == "3mf" and creality_native_project is True))))
                or not isinstance(filament_profiles, (list, tuple))
                or not 2 <= len(filament_profiles) <= 16):
            raise SlicerWorkerError("Multiple native filaments require an Orca 3MF or Creality multi-STL job.")
        if any(not isinstance(profile, bytes) for profile in filament_profiles):
            raise SlicerWorkerError("Invalid native filament palette.")
        if filament_profiles[0] != filament_profile:
            raise SlicerWorkerError("The first native filament preset must match the legacy profile.")
        payload["filament_profiles"] = [
            _encode(profile, MAX_REQUEST_PROFILE) for profile in filament_profiles
        ]
    if creality_native_project:
        if (creality_native_project is not True or engine != "crealityprint"
                or model_format != "3mf" or creality_model_stls is not None
                or creality_tool_ids is not None or
                filament_profiles is None or len(filament_profiles) != 2):
            raise SlicerWorkerError("Invalid Creality self-contained project contract.")
        payload["creality_native_project"] = True
    if creality_model_stls is not None:
        if (engine != "crealityprint" or model_format != "stl" or
                filament_profiles is None or not isinstance(creality_model_stls, (list, tuple))
                or not 2 <= len(creality_model_stls) <= 12 or
                not isinstance(creality_tool_ids, (list, tuple)) or
                len(creality_tool_ids) != len(creality_model_stls) or
                any(type(tool) is not int or not 1 <= tool <= len(filament_profiles)
                    for tool in creality_tool_ids) or
                len(set(creality_tool_ids)) < 2 or
                any(not isinstance(item, bytes) for item in creality_model_stls) or
                creality_model_stls[0] != model):
            raise SlicerWorkerError("Invalid Creality native multi-STL model/tool mapping.")
        payload["creality_model_stls"] = [
            _encode(item, MAX_REQUEST_MODEL) for item in creality_model_stls
        ]
        payload["creality_tool_ids"] = list(creality_tool_ids)
    elif creality_tool_ids is not None:
        raise SlicerWorkerError("Creality tool IDs require multi-STL models.")
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
            reason_details = None
            cli_exit_code = None
            validation_category = None
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
                            native_code = result.get("cli_exit_code")
                            if (engine == "crealityprint" and type(native_code) is int
                                    and 1 <= native_code <= 255
                                    and isinstance(reason, str)
                                    and reason.startswith("creality-")):
                                cli_exit_code = native_code
                            topic = result.get("validation_category")
                            if (engine == "crealityprint" and native_code == 205
                                    and reason == "creality-cli-validation-error"
                                    and topic in {
                                        "prime-tower", "layer-height", "line-width",
                                        "nozzle", "flow", "filament", "supports",
                                        "build-plate",
                                    }):
                                validation_category = topic
                            setting_keys = result.get("setting_keys") if reason == "native-project-settings-invalid" else None
                            if isinstance(setting_keys, list) and len(setting_keys) <= 8:
                                import re
                                safe_keys = [key for key in setting_keys
                                             if isinstance(key, str) and
                                             re.fullmatch(r"[a-z][a-z0-9_]{1,63}", key) and
                                             not any(word in key for word in (
                                                 "secret", "password", "token", "apikey",
                                                 "api_key", "authorization", "credential",
                                                 "private", "access_key"
                                             ))]
                                if safe_keys:
                                    reason_details = ", ".join(dict.fromkeys(safe_keys))
            except (ValueError, requests.RequestException, UnicodeDecodeError):
                pass
            message = explain_worker_failure(reason, response.status_code)
            if reason_details:
                message += " Rejected native setting(s): " + reason_details + "."
            if cli_exit_code is not None:
                native_error = {
                    205: "CLI_VALIDATE_ERROR (-51)",
                    232: "CLI_FILE_VERSION_NOT_SUPPORTED (-24)",
                    254: "CLI_INVALID_PARAMS (-2)",
                }.get(cli_exit_code, "native CLI failure")
                # SliceJob.message is bounded to 240 characters. Put the
                # reason marker FIRST and keep a compact, useful diagnostic,
                # otherwise the frontend help never recognises the reason.
                marker = "[" + reason + "] " if reason else ""
                prefix = "Creality Print exit " + str(cli_exit_code) + " (" + native_error + "). "
                if validation_category is not None:
                    prefix += "Validation category: " + validation_category.replace("-", " ") + ". "
                message = (marker + prefix + message)[:240]
            else:
                if validation_category is not None:
                    message += " Validation category: " + validation_category.replace("-", " ") + "."
                if reason:
                    message += " [" + reason + "]"
            # The worker already sends a fixed, allowlisted stage, not raw
            # slicer output or private paths. Preserve it even for a generic
            # validation-error, otherwise native project versus CLI failures
            # become indistinguishable to the operator.
            if stage is not None:
                message += " Stage: " + stage + "."
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
