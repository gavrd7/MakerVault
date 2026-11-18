"""Verify a Creality self-contained native 3MF project without trusting ZIP metadata.

The core model and per-object tool metadata use the existing restricted
MakerVault 3MF validator. Embedded project config is allowlisted separately
and is never interpreted as an executable command.
"""
import io
import json
import zipfile

from .runner import WorkerError
from .three_mf_validation import validate_worker_3mf

PROJECT_SETTINGS = "Metadata/project_settings.config"
CORE_MEMBERS = {"3D/3dmodel.model", "Metadata/model_settings.config",
                "[Content_Types].xml", "_rels/.rels"}
BLOCKED = {"post_process", "post_process_script", "post_process_scripts",
           "post_processing_script", "upload_host", "upload_url",
           "print_host", "print_host_webui", "printhost_apikey"}


def validate_creality_project(data, *, native_tool_count=2):
    if not isinstance(data, bytes) or len(data) > 32 * 1024 * 1024:
        raise WorkerError("Invalid Creality native project size.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            parts = archive.infolist()
            if (len(parts) != 5 or set(p.filename for p in parts) !=
                    CORE_MEMBERS | {PROJECT_SETTINGS} or
                    any(p.is_dir() or p.file_size <= 0 or
                        p.file_size > (4 * 1024 * 1024 if p.filename == PROJECT_SETTINGS
                                       else 80 * 1024 * 1024) for p in parts) or
                    sum(p.file_size for p in parts) > 96 * 1024 * 1024):
                raise WorkerError("Creality native project contains unsupported content.")
            project = json.loads(archive.read(PROJECT_SETTINGS))
            if (not isinstance(project, dict) or len(project) > 4096 or
                    project.get("name") != "project_settings" or
                    project.get("from") != "project" or
                    not isinstance(project.get("version"), str) or
                    not project["version"].startswith("7.3.")):
                raise WorkerError("Creality native project settings are invalid.")
            if any(key.lower() in BLOCKED for key in project):
                raise WorkerError("Creality native project contains blocked settings.")
            names = project.get("filament_settings_id")
            if not isinstance(names, list) or len(names) != native_tool_count or any(
                    not isinstance(name, str) or not 0 < len(name) <= 256 for name in names):
                raise WorkerError("Creality native project filament palette is incomplete.")
            # Validate the restrictive core plate using the existing worker
            # validator, not the project's richer vendor parser.
            core = io.BytesIO()
            with zipfile.ZipFile(core, "w", compression=zipfile.ZIP_DEFLATED,
                                 allowZip64=False) as trimmed:
                for name in sorted(CORE_MEMBERS):
                    trimmed.writestr(name, archive.read(name))
        validate_worker_3mf(core.getvalue(), native_tool_count=native_tool_count)
    except WorkerError:
        raise
    except (ValueError, KeyError, TypeError, OSError, zipfile.BadZipFile,
            UnicodeDecodeError):
        raise WorkerError("Malformed Creality native project.") from None
    return True
