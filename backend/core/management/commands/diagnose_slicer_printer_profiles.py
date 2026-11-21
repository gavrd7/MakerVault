"""Read-only native cross-printer compatibility smoke test.

Uses explicitly selected, integrity-checked imported profiles and the pinned
isolated worker. This never creates a SliceJob, persists modified profiles,
runs printer API calls, or permits the resulting G-code to be printed.
"""
import hashlib
import io
import json
import math
import uuid
import zipfile
from types import SimpleNamespace

from django.core.management.base import BaseCommand, CommandError

from core.models import SlicerProfile
from core.slicer_approval import fixture_stl, _approved_gcode
from core.slicer_bed_dimensions import trusted_plate_dimensions
from core.management.commands.diagnose_creality_paint_features import _metrics
from core.slicer_creality_project import (
    build_creality_positioned_plate, build_creality_project_candidate,
)
from core.slicer_execution import verified_installation
from core.slicer_flush_adapters import (
    apply_orca_native_flush, resolve_flush_capability,
)
from core.slicer_native_compatibility import check_native_compatibility
from core.slicer_native_material_palette import _single_positive_diameter
from core.slicer_native_resolution import resolved_native_profile
from core.slicer_plate_3mf import build_plate_3mf
from core.slicer_worker_client import run_remote_job
from core.slicer_tower_diagnostics import tower_deposition_metrics


SUPPORTED_TOPOLOGIES = ("single_nozzle_changer", "independent_toolheads",
                        "toolchanger", "idex", "manual_filament_change",
                        "single_material", "unknown")


def _fixture_items(count, width, depth):
    """Distinct 10mm tetrahedra on an origin-aligned rectangular bed."""
    if type(count) is not int or not 1 <= count <= 4:
        raise ValueError("Native compatibility fixture supports one to four materials.")
    if min(width, depth) < 90 or width > 1000 or depth > 1000:
        raise ValueError("Native fixture requires a verified 90–1000mm rectangular bed.")
    gap = 18.0
    centre = (count - 1) / 2
    return [
        ({
            "instance_id": "fixture-%d" % tool, "x_mm": (tool - centre) * gap,
            "y_mm": 0, "rotation_deg": 0, "scale_percent": 100,
        }, fixture_stl())
        for tool in range(count)
    ]


def _safe_native_result(data):
    """Report evidence without returning G-code, machine macros or paths."""
    result = _metrics(data)
    return {"gcode_sha256": _approved_gcode(data),
            "gcode_bytes": len(data),
            "motion_sha256": result["motion_sha256"],
            "machine_command_sha256": result["machine_command_sha256"],
            "g1_with_extrusion": result["g1_with_extrusion"],
            "tool0_selects": result["tool0_selects"],
            "tool1_selects": result["tool1_selects"],
            "note": "Native offline slicing; no physical printer validation."}


def _compatible_filament_diameter(filament_blobs, *, engine="orcaslicer"):
    """Validate each engine's native diameter representation, without guessing.

    Orca's one-element vector and Creality Print's scalar are different
    native schemas. Both require an exact positive bounded diameter, and
    mixed-diameter tool palettes remain forbidden for offline fixtures.
    """
    if engine not in {"orcaslicer", "crealityprint"}:
        raise ValueError("Unsupported native filament diameter encoding.")
    diameters = []
    for blob in filament_blobs:
        try:
            data = json.loads(blob)
        except (UnicodeDecodeError, TypeError, ValueError) as exc:
            raise ValueError("Invalid native filament preset.") from exc
        if not isinstance(data, dict):
            raise ValueError("Invalid native filament preset.")
        if engine == "orcaslicer":
            diameter = _single_positive_diameter(data)
        else:
            raw = data.get("filament_diameter")
            diameter = None
            if not isinstance(raw, (list, tuple, dict, bool)) and raw is not None:
                try:
                    parsed = float(raw)
                except (ValueError, TypeError, OverflowError):
                    pass
                else:
                    if math.isfinite(parsed) and 1 <= parsed <= 3.5:
                        diameter = parsed
        if diameter is None:
            raise ValueError("Native filament diameter is missing or invalid.")
        diameters.append(diameter)
    if not diameters or max(diameters) - min(diameters) > 0.001:
        raise ValueError("Mixed native filament diameters cannot be tested together.")
    return diameters[0]


def _read_creality_project_settings(project_blob):
    """Inspect only the generated effective native project configuration.

    The worker itself consumes the 3MF, not a standalone process JSON.
    Read exactly the setting file the native 3MF route receives.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(project_blob)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError("Duplicate Creality native archive entries.")
            data = archive.read("Metadata/project_settings.config")
    except (zipfile.BadZipFile, KeyError, OSError, ValueError) as exc:
        raise ValueError("Invalid self-contained Creality project settings.") from exc
    if len(data) > 4 * 1024 * 1024:
        raise ValueError("Creality native project settings exceed audit limit.")
    try:
        config = json.loads(data)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("Invalid Creality native project settings JSON.") from exc
    if not isinstance(config, dict):
        raise ValueError("Creality native project settings must be an object.")
    return config


def _creality_flush_basis(project_config):
    """Fail closed on missing/invalid native matrix and multiplier evidence."""
    import math
    matrix = project_config.get("flush_volumes_matrix")
    if not isinstance(matrix, list) or len(matrix) != 16:
        raise ValueError("Creality native project requires its complete 4x4 matrix.")
    for value in matrix:
        try:
            number = float(value) if not isinstance(value, bool) else math.nan
        except (ValueError, TypeError, OverflowError):
            raise ValueError("Invalid native Creality matrix entry.") from None
        if not math.isfinite(number) or not 0 <= number <= 20000:
            raise ValueError("Invalid native Creality matrix entry.")
    multiplier = project_config.get("flush_multiplier")
    if multiplier is None:
        return float(matrix[1]), None
    if isinstance(multiplier, (bool, list, dict, tuple)):
        raise ValueError("Invalid Creality native scalar flush multiplier.")
    try:
        number = float(multiplier)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("Invalid Creality native scalar flush multiplier.") from None
    if not math.isfinite(number) or not 0.1 <= number <= 3:
        raise ValueError("Invalid Creality native scalar flush multiplier.")
    return float(matrix[1]), number


def _creality_control_project(base, candidate):
    """Ensure no printer scripts or unrelated native fields were modified."""
    original = _read_creality_project_settings(base)
    test = _read_creality_project_settings(candidate)
    changed = {key for key in set(original) | set(test)
               if original.get(key) != test.get(key)}
    if not changed.issubset({
            "flush_multiplier", "flush_volumes_matrix", "flush_volumes_changed"}):
        raise ValueError("Unexpected native Creality project settings changed.")
    with (zipfile.ZipFile(io.BytesIO(base)) as before,
          zipfile.ZipFile(io.BytesIO(candidate)) as after):
        before_names = before.namelist()
        after_names = after.namelist()
        if set(before_names) != set(after_names):
            raise ValueError("Native Creality project entry set changed.")
        for name in before_names:
            if name == "Metadata/project_settings.config":
                continue
            if before.read(name) != after.read(name):
                raise ValueError("Native Creality project geometry or metadata changed.")
    return original, test, changed


def _creality_flush_override_control(project_blob):
    """Add only reviewed native process override declarations, not printer scripts.

    This is a disposable diagnostic, intentionally NOT the production adapter.
    """
    data = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(project_blob)) as source, zipfile.ZipFile(
            data, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=False) as target:
        names = source.namelist()
        if len(names) != len(set(names)) or len(names) not in (6, 7):
            raise ValueError("Unsupported native control project archive.")
        settings = _read_creality_project_settings(project_blob)
        palette = settings.get("filament_settings_id")
        original = settings.get("different_settings_to_system")
        if not isinstance(palette, list) or len(palette) != 4:
            raise ValueError("Native override control requires four palette slots.")
        if (not isinstance(original, list) or len(original) != len(palette) + 2
                or any(not isinstance(v, str) or len(v) > 8192 for v in original)):
            raise ValueError("Native process overrides are unavailable or invalid.")
        import re
        rows = list(original)
        existing = [x for x in rows[0].split(";") if x]
        if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", key) for key in existing):
            raise ValueError("Unsupported existing native process override key.")
        for key in ("flush_multiplier", "flush_volumes_matrix", "flush_volumes_changed"):
            if key not in existing:
                existing.append(key)
        rows[0] = ";".join(existing)
        settings["different_settings_to_system"] = rows
        for name in names:
            content = (json.dumps(settings, separators=(",", ":")).encode()
                       if name == "Metadata/project_settings.config"
                       else source.read(name))
            target.writestr(name, content)
    return data.getvalue()


def _creality_purge_route_control(project_blob, enabled):
    """Switch only the native purge destination on a disposable Creality 3MF."""
    if type(enabled) is not bool:
        raise ValueError("Purge route control requires an explicit boolean.")
    config = _read_creality_project_settings(project_blob)
    config["purge_in_prime_tower"] = "1" if enabled else "0"
    result = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(project_blob)) as source, zipfile.ZipFile(
            result, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=False) as target:
        names = source.namelist()
        if len(names) != len(set(names)) or len(names) not in (6, 7):
            raise ValueError("Unsupported native Creality purge route archive.")
        for item in source.infolist():
            content = (json.dumps(config, separators=(",", ":")).encode()
                       if item.filename == "Metadata/project_settings.config"
                       else source.read(item.filename))
            target.writestr(item, content)
    candidate = result.getvalue()
    original, changed, keys = _creality_control_project_with_extra(
        project_blob, candidate, {"purge_in_prime_tower"})
    if not keys.issubset({"purge_in_prime_tower"}) or (
            changed.get("purge_in_prime_tower") != ("1" if enabled else "0")):
        raise ValueError("Purge routing control changed unrelated native options.")
    return candidate



def _validate_creality_purge_route_pair(baseline, parent, candidate, enabled):
    """Validate baseline and parent isolation before running native slicer."""
    if type(enabled) is not bool:
        raise ValueError("Invalid native purge route selection.")
    original, changed, keys = _creality_control_project_with_extra(
        baseline, candidate, {"purge_in_prime_tower"})
    if keys - {"flush_multiplier", "purge_in_prime_tower"}:
        raise ValueError("Purge route candidate changed baseline settings.")
    _parent_before, parent_after, parent_keys = (
        _creality_control_project_with_extra(
            parent, candidate, {"purge_in_prime_tower"}))
    if parent_keys - {"purge_in_prime_tower"}:
        raise ValueError("Purge route candidate changed its multiplier parent.")
    requested = "1" if enabled else "0"
    if (parent_after.get("purge_in_prime_tower") != requested or
            parent_after.get("flush_multiplier") != "2.0"):
        raise ValueError("Purge route control lost its fixed multiplier or routing.")
    return True





def _creality_mark_native_process_options(project_blob, keys):
    """Mark only reviewed print options on a disposable native project.

    Creality's project preset merge can restore unmarked process options.
    This tests whether the native process override list controls retention.
    """
    import re
    allowed = {"prime_volume", "purge_in_prime_tower"}
    if not isinstance(keys, (tuple, list)) or not keys or any(
            key not in allowed for key in keys) or len(set(keys)) != len(keys):
        raise ValueError("Unsupported native print override control.")
    config = _read_creality_project_settings(project_blob)
    names = config.get("filament_settings_id")
    rows = config.get("different_settings_to_system")
    if (not isinstance(names, list) or len(names) != 4
            or not isinstance(rows, list) or len(rows) != len(names) + 2
            or any(not isinstance(row, str) or len(row) > 8192 for row in rows)):
        raise ValueError("Unsupported native process override vector.")
    existing = [value for value in rows[0].split(";") if value]
    if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", key) for key in existing):
        raise ValueError("Untrusted native process override name.")
    for key in keys:
        if key not in existing:
            existing.append(key)
    modified = dict(config)
    modified["different_settings_to_system"] = [
        ";".join(existing), *rows[1:]]
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(project_blob)) as source, zipfile.ZipFile(
            output, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=False) as target:
        members = source.namelist()
        if len(members) != len(set(members)) or len(members) not in (6, 7):
            raise ValueError("Invalid native marked control archive.")
        for member in source.infolist():
            content = (json.dumps(modified, separators=(",", ":")).encode()
                       if member.filename == "Metadata/project_settings.config"
                       else source.read(member.filename))
            target.writestr(member, content)
    candidate = output.getvalue()
    _before, after, changes = _creality_control_project_with_extra(
        project_blob, candidate, {"different_settings_to_system"})
    if (changes - {"different_settings_to_system"} or
            after["different_settings_to_system"][1:] != rows[1:]):
        raise ValueError("Native process marker control changed unrelated settings.")
    return candidate


def _creality_mark_native_printer_purge(project_blob):
    """Mark the machine-owned purge route only in the printer override slot.

    Creality v7.3.1 treats purge_in_prime_tower as a machine setting.
    Keep process and filament override vectors untouched.
    """
    import re
    project = _read_creality_project_settings(project_blob)
    names = project.get("filament_settings_id")
    rows = project.get("different_settings_to_system")
    if (not isinstance(names, list) or len(names) != 4
            or not isinstance(rows, list) or len(rows) != len(names) + 2
            or any(not isinstance(row, str) or len(row) > 8192 for row in rows)
            or project.get("purge_in_prime_tower") != "1"):
        raise ValueError("Invalid native printer purge marker input.")
    index = len(names) + 1
    existing = [value for value in rows[index].split(";") if value]
    if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", key) for key in existing):
        raise ValueError("Untrusted native printer override name.")
    if "purge_in_prime_tower" not in existing:
        existing.append("purge_in_prime_tower")
    updated = dict(project)
    updated_rows = rows[:]
    updated_rows[index] = ";".join(existing)
    updated["different_settings_to_system"] = updated_rows
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(project_blob)) as source, zipfile.ZipFile(
            output, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=False) as target:
        members = source.namelist()
        if len(members) != len(set(members)) or len(members) not in (6, 7):
            raise ValueError("Invalid native printer marker archive.")
        for member in source.infolist():
            data = (json.dumps(updated, separators=(",", ":")).encode()
                    if member.filename == "Metadata/project_settings.config"
                    else source.read(member.filename))
            target.writestr(member, data)
    candidate = output.getvalue()
    before, after, keys = _creality_control_project_with_extra(
        project_blob, candidate, {"different_settings_to_system"})
    if (keys - {"different_settings_to_system"}
            or after["different_settings_to_system"][:-1] != rows[:-1]
            or after.get("purge_in_prime_tower") != "1"
            or before.get("change_filament_gcode") != after.get("change_filament_gcode")):
        raise ValueError("Native printer purge marker altered unrelated settings.")
    return candidate


def _creality_prime_volume_control(project_blob, volume_mm3=180):
    """Create an offline positive control without changing native scripts."""
    if type(volume_mm3) is not int or not 90 <= volume_mm3 <= 300:
        raise ValueError("Invalid bounded native tower volume control.")
    original = _read_creality_project_settings(project_blob)
    baseline_volume = original.get("prime_volume")
    if isinstance(baseline_volume, (bool, dict, list)) or baseline_volume is None:
        raise ValueError("Native prime volume source is missing or invalid.")
    try:
        old_value = float(baseline_volume)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Invalid native prime volume value.") from None
    if not math.isfinite(old_value) or not 0 < old_value < volume_mm3:
        raise ValueError("Native prime volume cannot form an increasing control.")
    modified = dict(original)
    modified["prime_volume"] = str(volume_mm3)
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(project_blob)) as source, zipfile.ZipFile(
            output, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=False) as dest:
        members = source.namelist()
        if len(members) != len(set(members)) or len(members) not in (6, 7):
            raise ValueError("Invalid native tower volume project archive.")
        for member in source.infolist():
            data = (json.dumps(modified, separators=(",", ":")).encode()
                    if member.filename == "Metadata/project_settings.config"
                    else source.read(member.filename))
            dest.writestr(member, data)
    result = output.getvalue()
    _before, after, keys = _creality_control_project_with_extra(
        project_blob, result, {"prime_volume"})
    if keys != {"prime_volume"} or after["prime_volume"] != str(volume_mm3):
        raise ValueError("Native prime volume positive control changed unrelated data.")
    return result


def _creality_emitted_setting_audit(gcode):
    """Read safe numerical/flag settings emitted by Creality into G-code.

    This captures G-code *text*, not the slicer's in-memory effective PrintConfig.
    Never return raw comments, unrecognised field values, or native scripts.
    """
    import re
    if not isinstance(gcode, bytes) or not 0 < len(gcode) <= 64 * 1024 * 1024:
        raise ValueError("Invalid bounded native G-code audit input.")
    recognised = {
        "flush_multiplier", "purge_in_prime_tower", "enable_prime_tower",
        "prime_volume", "prime_tower_width", "flush_volumes_matrix",
    }
    pattern = re.compile(
        r"^;\s*(" + "|".join(sorted(recognised)) +
        r")\s*(?:=|:)\s*(.*?)\s*$", re.I)
    found = {}
    conflicts = set()
    for line in gcode.decode("utf-8", errors="replace").splitlines():
        if len(line) > 8192:
            continue
        match = pattern.fullmatch(line.strip())
        if match is None:
            continue
        key, raw = match.group(1).lower(), match.group(2).strip()
        value = None
        if key == "flush_volumes_matrix":
            # Never expose a whole source matrix, including custom materials.
            value = "present" if raw else "empty"
        elif key in {"purge_in_prime_tower", "enable_prime_tower"}:
            if raw in {"0", "1"}:
                value = "enabled" if raw == "1" else "disabled"
        else:
            try:
                number = float(raw)
            except (ValueError, TypeError, OverflowError):
                pass
            else:
                if math.isfinite(number) and 0 <= number <= 20000:
                    value = round(number, 4)
        if value is None:
            continue
        if key in found and found[key] != value:
            conflicts.add(key)
        else:
            found[key] = value
    for key in conflicts:
        found.pop(key, None)
    return {
        "evidence_source": "generated_gcode_comment_metadata_not_native_runtime_config",
        "settings": found,
        "conflicting_keys": sorted(conflicts),
        "recognised_keys_absent": sorted(recognised - set(found) - conflicts),
        "limitation": "Only recognised emitted G-code comment values; absence does not prove settings were ignored.",
    }



def _creality_marked_result_comparison(controls, marked_name, parent_name):
    """Compare a marked slice with its explicit parent, never a guessed key."""
    if (not isinstance(controls, dict) or marked_name not in controls
            or parent_name not in controls or marked_name == parent_name):
        raise ValueError("Missing Creality marked or parent control.")
    marked, parent = controls[marked_name], controls[parent_name]
    for entry in (marked, parent):
        if (not isinstance(entry, dict)
                or not isinstance(entry.get("tower_deposition"), dict)
                or not isinstance(entry.get("emitted_gcode_settings_comparison"), dict)):
            raise ValueError("Missing native Creality comparison evidence.")
    def emitted(config):
        return config["emitted_gcode_settings_comparison"]["candidate"]["settings"]
    try:
        before, after = emitted(parent), emitted(marked)
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise ValueError("Invalid Creality emitted settings evidence.")
        return {
            "motion_changed_vs_unmarked": (
                marked["motion_sha256"] != parent["motion_sha256"]),
            "machine_commands_changed_vs_unmarked": (
                marked["machine_command_sha256"] != parent["machine_command_sha256"]),
            "tower_extrusion_changed_vs_unmarked": (
                marked["tower_deposition"]["positive_e_length_mm"] !=
                parent["tower_deposition"]["positive_e_length_mm"]),
            "emitted_keys_changed_vs_unmarked": sorted(
                key for key in set(before) | set(after)
                if before.get(key) != after.get(key)),
        }
    except (KeyError, TypeError) as exc:
        raise ValueError("Incomplete native Creality marked comparison.") from exc


def _creality_emitted_comparison(baseline, candidate):
    """Compare only scrubbed native comment evidence across two slice outputs."""
    before = _creality_emitted_setting_audit(baseline)
    after = _creality_emitted_setting_audit(candidate)
    return {
        "candidate": after,
        "changed_emitted_keys": sorted(
            key for key in set(before["settings"]) | set(after["settings"])
            if before["settings"].get(key) != after["settings"].get(key)),
    }


def _creality_purge_route_audit(config):
    """Report a bounded project setting snapshot, not effective runtime values."""
    if not isinstance(config, dict):
        raise ValueError("Invalid Creality native project configuration.")
    def flag(key):
        value = config.get(key)
        if value is None:
            return "absent"
        if value is True or value == "1" or (type(value) is int and value == 1):
            return "enabled"
        if value is False or value == "0" or (type(value) is int and value == 0):
            return "disabled"
        return "unrecognised"

    def bounded_number(key):
        value = config.get(key)
        if value is None:
            return None
        if isinstance(value, (bool, list, dict)):
            return None
        try:
            number = float(value)
        except (ValueError, TypeError, OverflowError):
            return None
        return round(number, 4) if math.isfinite(number) and 0 <= number <= 20000 else None

    return {
        "evidence_source": "generated_native_3mf_not_runtime_effective_config",
        "purge_in_prime_tower": flag("purge_in_prime_tower"),
        "enable_prime_tower": flag("enable_prime_tower"),
        "multicolor_method": flag("multicolor_method"),
        "prime_volume_mm3": bounded_number("prime_volume"),
        "filament_minimal_purge_on_wipe_tower_present": (
            "filament_minimal_purge_on_wipe_tower" in config),
        "flush_multiplier": bounded_number("flush_multiplier"),
        "flush_matrix_present": isinstance(config.get("flush_volumes_matrix"), list)
                                and len(config["flush_volumes_matrix"]) == 16,
        "limitation": "Project encoding only; native loader and printer firmware may use different effective values.",
    }


def _validate_creality_override_pair(unmarked, marked):
    before, after, keys = _creality_control_project_with_extra(
        unmarked, marked, {"different_settings_to_system"})
    if keys != {"different_settings_to_system"}:
        raise ValueError("Native override pair changed unrelated settings.")
    if (before.get("flush_multiplier") != after.get("flush_multiplier")
            or before.get("flush_volumes_matrix") != after.get("flush_volumes_matrix")
            or before.get("flush_volumes_changed") != after.get("flush_volumes_changed")):
        raise ValueError("Native override pair changed flushing numeric values.")
    return True


def _creality_control_project_with_extra(base, candidate, extra_keys):
    original = _read_creality_project_settings(base)
    test = _read_creality_project_settings(candidate)
    changed = {key for key in set(original) | set(test)
               if original.get(key) != test.get(key)}
    if not changed.issubset({
            "flush_multiplier", "flush_volumes_matrix", "flush_volumes_changed"
            } | set(extra_keys)):
        raise ValueError("Unexpected native Creality project settings changed.")
    with (zipfile.ZipFile(io.BytesIO(base)) as before,
          zipfile.ZipFile(io.BytesIO(candidate)) as after):
        before_names = before.namelist()
        after_names = after.namelist()
        if (len(before_names) != len(set(before_names)) or
                set(before_names) != set(after_names)):
            raise ValueError("Native Creality control entries mismatch.")
        for name in before_names:
            if name != "Metadata/project_settings.config" and (
                    before.read(name) != after.read(name)):
                raise ValueError("Native Creality geometry or metadata changed.")
    return original, test, changed


def _native_nozzle_count(printer_blob):
    """Count nozzles from the *resolved native machine profile*, never names."""
    try:
        printer = json.loads(printer_blob)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Native machine nozzle information is invalid.") from exc
    if not isinstance(printer, dict):
        raise ValueError("Native machine must be a JSON object.")
    values = printer.get("nozzle_diameter")
    if not isinstance(values, list) or not 1 <= len(values) <= 16:
        raise ValueError("Native machine must declare one to sixteen nozzle diameters.")
    import math
    for item in values:
        try:
            diameter = float(item) if not isinstance(item, bool) else math.nan
        except (ValueError, TypeError):
            raise ValueError("Invalid native machine nozzle diameter.") from None
        if not math.isfinite(diameter) or not 0.1 <= diameter <= 3:
            raise ValueError("Invalid native machine nozzle diameter.")
    return len(values)


def _same_native_pair(profile, owner, engine, version, kind):
    return (profile and profile.owner_id == owner
            and profile.engine == engine and profile.engine_version == version
            and profile.kind == kind and profile.status in {"candidate", "verified"})


class Command(BaseCommand):
    help = "Audit or offline-slice exact selected printer profiles without printer communication."

    def add_arguments(self, parser):
        parser.add_argument("--engine", choices=("orcaslicer", "crealityprint"), required=True)
        parser.add_argument("--list-profiles", action="store_true",
                            help="List up to 100 available imported native profile identities")
        parser.add_argument("--name-contains", help="Filter local imported profile list by bounded name fragment")
        parser.add_argument("--printer-profile-id")
        parser.add_argument("--process-profile-id")
        parser.add_argument("--filament-profile-id", action="append", default=[])
        parser.add_argument("--topology", choices=SUPPORTED_TOPOLOGIES)
        parser.add_argument("--native", action="store_true",
                            help="Send ONLY disposable offline fixture to approved worker")
        parser.add_argument("--test-flush", action="store_true",
                            help="Run bounded native A/B flushing controls for Orca or Creality single-nozzle changers")

    def handle(self, *args, **opts):
        engine = opts["engine"]
        if opts["list_profiles"]:
            query = SlicerProfile.objects.filter(engine=engine)
            fragment = opts.get("name_contains")
            if fragment:
                if not 1 <= len(fragment) <= 100 or any(ord(ch) < 32 for ch in fragment):
                    raise CommandError("Invalid imported profile name filter.")
                query = query.filter(name__icontains=fragment)
            rows = list(query.order_by(
                "engine_version", "kind", "pk").values(
                "pk", "name", "source_scope", "kind", "engine_version", "status")[:100])
            self.stdout.write(json.dumps({"schema": 1, "engine": engine,
                "profiles": [{"id": str(row["pk"]), "name": str(row["name"])[:120],
                              "source_scope": str(row["source_scope"])[:100],
                              "kind": row["kind"], "version": row["engine_version"],
                              "status": row["status"]} for row in rows],
                "truncated_at": 100, "note": "Listing only, not native validation."}, indent=2))
            return
        if opts["test_flush"] and not opts["native"]:
            raise CommandError("--test-flush requires --native.")
        if not opts["topology"]:
            raise CommandError("Explicit --topology required; printer names cannot imply topology.")
        source_ids = [opts["printer_profile_id"], opts["process_profile_id"],
                      *opts["filament_profile_id"]]
        if (not 3 <= len(source_ids) <= 6 or any(x is None for x in source_ids)):
            raise CommandError("Select printer, process and one to four native filament profile IDs.")
        try:
            profile_ids = [uuid.UUID(v) for v in source_ids]
        except (TypeError, ValueError):
            raise CommandError("Invalid selected profile UUID.") from None
        records = {
            str(p.pk): p for p in SlicerProfile.objects.select_related(
                "file_asset").filter(pk__in=profile_ids)
        }
        if len(records) != len(set(profile_ids)):
            raise CommandError("Some selected imported native profiles were not found.")
        printer, process, *filaments = [records[str(key)] for key in profile_ids]
        owner = printer.owner_id
        version = printer.engine_version
        if (not _same_native_pair(printer, owner, engine, version, "printer")
                or not _same_native_pair(process, owner, engine, version, "process")
                or any(not _same_native_pair(p, owner, engine, version, "filament")
                       for p in filaments)):
            raise CommandError("Native profiles must match one owner, engine and exact version.")
        # A repeated native filament preset for two logical tools is permitted:
        # they are distinct physical spool assignments but share material type.
        native = {
            "printer": resolved_native_profile(printer),
            "process": resolved_native_profile(process),
            "filaments": [resolved_native_profile(p) for p in filaments],
        }
        for kind, raw in (("printer", native["printer"]),
                          ("process", native["process"]),
                          *[("filament", blob) for blob in native["filaments"]]):
            check_native_compatibility(engine, version, kind, raw)
        count = len(filaments)
        try:
            filament_diameter = _compatible_filament_diameter(
                native["filaments"], engine=engine)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        width, depth = trusted_plate_dimensions(printer)
        try:
            nozzles = _native_nozzle_count(native["printer"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        if opts["topology"] == "single_nozzle_changer" and nozzles != 1:
            raise CommandError("A single-nozzle changer requires exactly one native nozzle.")
        if opts["topology"] in ("independent_toolheads", "toolchanger", "idex"):
            if nozzles != count or count < 2:
                raise CommandError("Independent toolhead fixture needs one verified native nozzle per logical tool.")
            if opts["topology"] == "idex" and nozzles != 2:
                raise CommandError("IDEX fixture requires two verified nozzles.")
        cap = resolve_flush_capability(
            engine, opts["topology"], nozzle_count=nozzles,
            material_count=count)
        summary = {
            "schema": 1, "engine": engine, "version": version,
            "topology": opts["topology"], "logical_material_count": count,
            "native_nozzle_count": nozzles,
            "filament_diameter_mm": filament_diameter,
            "bed_mm": [width, depth],
            "native_flush_encoding_supported": cap.supported_for_encoding_only,
            "unsupported_reason": cap.reason,
            "physical_purge": "unverified",
            "offline_only": True, "native_run": "not_requested",
        }
        if not opts["native"]:
            self.stdout.write(json.dumps(summary, indent=2))
            return
        installed = verified_installation().get(engine)
        if not installed or installed.get("version") != version:
            raise CommandError("Matching authenticated pinned engine is not available.")
        if count > 1 and engine == "crealityprint" and (
                count != 2 or opts["topology"] != "single_nozzle_changer"):
            raise CommandError("Creality multi-material fixture only supports its verified two-tool single-nozzle project.")
        if opts["test_flush"] and (
                not cap.supported_for_encoding_only or count < 2):
            raise CommandError("Native flushing A/B test requires a supported single-nozzle changer.")
        # Reject missing/incompatible matrices *before* using worker time.
        first_flush_volume = None
        if opts["test_flush"] and engine == "orcaslicer":
            raw_matrix = json.loads(native["process"]).get("flush_volumes_matrix")
            if not isinstance(raw_matrix, list) or len(raw_matrix) != count * count:
                raise CommandError("No complete native flush matrix for directional A/B fixture.")
            try:
                first_flush_volume = float(raw_matrix[1])
            except (TypeError, ValueError, OverflowError):
                raise CommandError("Native T0-to-T1 flush volume is invalid.") from None
            if not 0 <= first_flush_volume <= 19950:
                raise CommandError("Native T0-to-T1 volume exceeds safe A/B fixture bounds.")
        if count == 1:
            model = fixture_stl()
            kwargs = {}
        elif engine == "orcaslicer":
            items = _fixture_items(count, width, depth)
            model = build_plate_3mf(items, bed_width=width, bed_depth=depth,
                                    native_tool_indices=list(range(count)))
            kwargs = {"model_format": "3mf", "filament_profiles": native["filaments"]}
        else:
            items = _fixture_items(count, width, depth)
            geometry = build_creality_positioned_plate(
                items, bed_width=width, bed_depth=depth,
                tool_ids=list(range(count)))
            def build_creality(flush=None):
                return build_creality_project_candidate(
                    geometry, printer=native["printer"], process=native["process"],
                    filaments=native["filaments"], bed_width=width, bed_depth=depth,
                    version=version, flush_settings=flush,
                    # Only diagnostic controls are intentionally UNMARKED.
                    # Normal MakerVault project building defaults to marking
                    # explicit native flush overrides for Creality's CLI.
                    preserve_native_flush_overrides=False,
                    tool_bindings={"fixture-slot-0": 0, "fixture-slot-1": 1}
                    if flush is not None else None)
            model = build_creality()
            kwargs = {"model_format": "3mf",
                      "filament_profiles": native["filaments"],
                      "creality_native_project": True}
        def slice_native(process_blob, model_blob=None):
            return run_remote_job(
                uuid.uuid4(), engine, version, model if model_blob is None else model_blob,
                native["printer"], native["filaments"][0], process_blob,
                timeout_seconds=900, **kwargs)
        # Validate Creality controls and baseline provenance before any worker
        # execution; generated zero/140 fallback values are NOT user defaults.
        creality_controls = None
        creality_route_flush_controls = None
        if opts["test_flush"] and engine == "crealityprint":
            baseline_config = _read_creality_project_settings(model)
            first_flush_volume, native_multiplier = _creality_flush_basis(baseline_config)
            if not 0 <= first_flush_volume <= 19950:
                raise CommandError("Native Creality directional volume is outside safe A/B bounds.")
            # The imported K2 preset has no native multiplier: test 1.00
            # and 2.00 as EXPLICIT disposable controls, not inherited
            # defaults or changes to the user's saved profiles.
            multiplier_controls = (1.0, 2.0)
            def settings(multiplier=None, transition=None):
                return {
                    "multiplier": multiplier, "prime_tower": "native",
                    "transitions": [] if transition is None else [{
                        "from_slot_id": transition[0],
                        "to_slot_id": transition[1],
                        "volume_mm3": transition[2],
                    }],
                }
            creality_controls = [
                ("forward", build_creality(settings(
                    transition=("fixture-slot-0", "fixture-slot-1",
                                first_flush_volume + 25)))),
            ]
            for requested in multiplier_controls:
                creality_controls.append((
                    "multiplier_" + str(requested).replace(".", "_"),
                    build_creality(settings(multiplier=requested))))
            for requested in multiplier_controls:
                name = "multiplier_" + str(requested).replace(".", "_")
                source_control = next(project for key, project in creality_controls
                                      if key == name)
                marked = _creality_flush_override_control(source_control)
                _validate_creality_override_pair(source_control, marked)
                creality_controls.append((name + "_marked", marked))
            # Source-backed route isolation: Creality's tower planner can
            # substitute prime_volume when purge_in_prime_tower is disabled.
            # Compare both routes at a fixed explicit 2.0 multiplier; do not
            # change any manufacturer scripts or production flush adapter.
            fixed_control = next(project for key, project in creality_controls
                                 if key == "multiplier_2_0")
            for route_enabled in (False, True):
                route_name = "purge_route_" + ("tower" if route_enabled else "toolchange")
                creality_controls.append((
                    route_name, _creality_purge_route_control(
                        fixed_control, route_enabled)))
            # An independent setting expected to influence native tower
            # generation in the source, isolated from all flush fields.
            positive_control = _creality_prime_volume_control(fixed_control)
            creality_controls.append((
                "prime_volume_positive_control", positive_control))
            creality_controls.append((
                "prime_volume_marked",
                _creality_mark_native_process_options(
                    positive_control, ["prime_volume"])))
            tower_source = next(project for key, project in creality_controls
                                if key == "purge_route_tower")
            creality_controls.append((
                "purge_route_tower_marked",
                _creality_mark_native_process_options(
                    tower_source, ["purge_in_prime_tower"])))
            creality_controls.append((
                "purge_route_tower_printer_marked",
                _creality_mark_native_printer_purge(tower_source)))
            # Now isolate the directional flush matrix and scalar multiplier
            # ONLY while the printer-level purge route is preserved.
            # The native preset merger also needs process-level declarations
            # for the matrix; no production profile or script is modified.
            flush_at_two = _creality_mark_native_printer_purge(
                _creality_flush_override_control(tower_source))
            flush_at_one_source = _creality_purge_route_control(
                next(project for key, project in creality_controls
                     if key == "multiplier_1_0"), True)
            flush_at_one = _creality_mark_native_printer_purge(
                _creality_flush_override_control(flush_at_one_source))
            forward_two_source = build_creality(settings(
                multiplier=2.0, transition=(
                    "fixture-slot-0", "fixture-slot-1",
                    first_flush_volume + 25)))
            forward_two_route = _creality_purge_route_control(
                forward_two_source, True)
            flush_forward_two = _creality_mark_native_printer_purge(
                _creality_flush_override_control(forward_two_route))
            creality_route_flush_controls = [
                ("tower_flush_multiplier_1_0", flush_at_one),
                ("tower_flush_multiplier_2_0", flush_at_two),
                ("tower_flush_forward_2_0", flush_forward_two),
            ]
            for label, candidate, source in (
                    ("tower_flush_multiplier_1_0", flush_at_one, flush_at_one_source),
                    ("tower_flush_multiplier_2_0", flush_at_two, tower_source),
                    ("tower_flush_forward_2_0", flush_forward_two, forward_two_route)):
                original, changed, differences = _creality_control_project_with_extra(
                    source, candidate, {"different_settings_to_system"})
                if (differences - {"different_settings_to_system"}
                        or original["flush_volumes_matrix"] != changed["flush_volumes_matrix"]
                        or changed.get("purge_in_prime_tower") != "1"):
                    raise CommandError("Native tower flush control changed unrelated fields.")
                # The process and printer declarations must both be present.
                declarations = changed["different_settings_to_system"]
                if (not isinstance(declarations, list)
                        or "flush_volumes_matrix" not in declarations[0].split(";")
                        or "flush_multiplier" not in declarations[0].split(";")
                        or "purge_in_prime_tower" not in declarations[-1].split(";")):
                    raise CommandError("Native tower flush override declarations are missing.")
                _creality_flush_basis(changed)
            if (float(_read_creality_project_settings(flush_forward_two)
                      ["flush_volumes_matrix"][1])
                    != first_flush_volume + 25):
                raise CommandError("Native tower directional matrix control was not isolated.")
            for name, candidate in creality_controls:
                original, changed, keys = _creality_control_project_with_extra(
                    model, candidate,
                    ({"purge_in_prime_tower", "different_settings_to_system"}
                     if name in {"purge_route_tower_marked",
                                 "purge_route_tower_printer_marked"}
                     else {"different_settings_to_system", "prime_volume"}
                     if name == "prime_volume_marked"
                     else {"different_settings_to_system"} if name.endswith("_marked")
                     else {"purge_in_prime_tower"} if name.startswith("purge_route_")
                     else {"prime_volume"} if name == "prime_volume_positive_control"
                     else set()))
                if name == "forward":
                    if (float(changed["flush_volumes_matrix"][1]) !=
                            first_flush_volume + 25 or
                            changed["flush_volumes_matrix"][4] !=
                            original["flush_volumes_matrix"][4]):
                        raise CommandError("Creality forward directional fixture was not isolated.")
                    if changed.get("flush_multiplier") != original.get("flush_multiplier"):
                        raise CommandError("Creality native multiplier changed in directional fixture.")
                elif name == "prime_volume_marked":
                    _original, _marked, marker_keys = _creality_control_project_with_extra(
                        positive_control, candidate, {"different_settings_to_system"})
                    if marker_keys - {"different_settings_to_system"}:
                        raise CommandError("Creality prime volume marker isolation failed.")
                elif name in {"purge_route_tower_marked",
                                "purge_route_tower_printer_marked"}:
                    _original, _marked, marker_keys = _creality_control_project_with_extra(
                        tower_source, candidate, {"different_settings_to_system"})
                    if marker_keys - {"different_settings_to_system"}:
                        raise CommandError("Creality purge routing marker isolation failed.")
                elif name == "prime_volume_positive_control":
                    if (keys - {"flush_multiplier", "prime_volume"} or
                            changed.get("flush_multiplier") != "2.0" or
                            changed.get("prime_volume") != "180"):
                        raise CommandError("Creality prime volume control baseline isolation failed.")
                    _p0, _p1, parent_keys = _creality_control_project_with_extra(
                        fixed_control, candidate, {"prime_volume"})
                    if parent_keys != {"prime_volume"}:
                        raise CommandError("Creality prime volume parent isolation failed.")
                elif name.startswith("purge_route_"):
                    try:
                        _validate_creality_purge_route_pair(
                            model, fixed_control, candidate,
                            name == "purge_route_tower")
                    except ValueError as exc:
                        raise CommandError("Creality purge route isolation failed.") from exc
                else:
                    raw_name = name.removeprefix("multiplier_").removesuffix("_marked")
                    requested = float(raw_name.replace("_", "."))
                    if ("flush_volumes_matrix" in keys or
                            float(changed["flush_multiplier"]) != requested):
                        raise CommandError("Creality multiplier control changed directional volumes.")
                    if name.endswith("_marked") and (
                            "different_settings_to_system" not in keys):
                        raise CommandError("Native flushing marker control is missing override declarations.")
        output = slice_native(native["process"])
        summary["native_run"] = "sliced"
        summary["baseline"] = _safe_native_result(output)
        if opts["test_flush"] and engine == "orcaslicer":
            first = first_flush_volume
            modified = apply_orca_native_flush(
                native["process"], {
                    "prime_tower": "native", "multiplier": None,
                    "transitions": [{
                        "from_slot_id": "fixture-slot-0",
                        "to_slot_id": "fixture-slot-1",
                        "volume_mm3": first + 25,
                    }],
                },
                routes=[SimpleNamespace(slot_id="fixture-slot-%d" % n,
                                        tool_index=n) for n in range(count)],
                tool_count=count, topology="single_nozzle_changer")
            control = slice_native(modified)
            summary["directional_matrix_control"] = {
                "baseline_raw_mm3": first,
                "requested_raw_mm3": first + 25,
                **_safe_native_result(control),
                "gcode_changed": hashlib.sha256(output).digest() != hashlib.sha256(control).digest(),
                "motion_changed": _metrics(output)["motion_sha256"] != _metrics(control)["motion_sha256"],
                "machine_commands_changed": (
                    _metrics(output)["machine_command_sha256"] !=
                    _metrics(control)["machine_command_sha256"]),
                "note": "Motion or command change is stronger than metadata difference, but is NOT physical purge validation.",
            }
        if creality_controls is not None:
            # Project packager overlays printer and process native settings.
            # If neither contains a matrix, its conservative 140mm3 values
            # are diagnostic placeholders, never vendor-calculated defaults.
            machine_source = json.loads(native["printer"])
            process_source = json.loads(native["process"])
            if "flush_volumes_matrix" in process_source:
                matrix_source = "resolved_native_process"
            elif "flush_volumes_matrix" in machine_source:
                matrix_source = "resolved_native_printer"
            else:
                matrix_source = "candidate_builder_140mm3_fallback_unverified"
            summary["creality_purge_route_project_audit"] = (
                _creality_purge_route_audit(_read_creality_project_settings(model)))
            summary["creality_flush_basis"] = {
                "matrix_source": matrix_source,
                "baseline_t0_to_t1_mm3": first_flush_volume,
                "native_scalar_multiplier": native_multiplier,
                "multiplier_default_known": native_multiplier is not None,
            }
            baseline_metrics = _metrics(output)
            baseline_tower = tower_deposition_metrics(output)
            summary["native_tower_deposition_baseline"] = baseline_tower
            summary["creality_emitted_gcode_baseline_audit"] = _creality_emitted_setting_audit(output)
            summary["creality_flush_controls"] = {}
            for name, candidate in creality_controls:
                result = slice_native(native["process"], candidate)
                measured = _metrics(result)
                tower = tower_deposition_metrics(result)
                summary["creality_flush_controls"][name] = {
                    **_safe_native_result(result),
                    "emitted_gcode_settings_comparison": _creality_emitted_comparison(output, result),
                    "purge_route_project_audit": (
                        _creality_purge_route_audit(_read_creality_project_settings(candidate))
                        if name.startswith("purge_route_") else None),
                    "tower_deposition": tower,
                    "tower_comparison_available": (
                        baseline_tower["classification"] == "native_feature_marker"
                        and tower["classification"] == "native_feature_marker"),
                    "tower_xy_width_changed": (
                        tower["xy_width_mm"] != baseline_tower["xy_width_mm"]
                        if baseline_tower["classification"] == "native_feature_marker"
                        and tower["classification"] == "native_feature_marker" else None),
                    "tower_xy_depth_changed": (
                        tower["xy_depth_mm"] != baseline_tower["xy_depth_mm"]
                        if baseline_tower["classification"] == "native_feature_marker"
                        and tower["classification"] == "native_feature_marker" else None),
                    "tower_e_length_changed": (
                        tower["positive_e_length_mm"] != baseline_tower["positive_e_length_mm"]
                        if baseline_tower["classification"] == "native_feature_marker"
                        and tower["classification"] == "native_feature_marker" else None),
                    "gcode_changed": hashlib.sha256(result).digest() != hashlib.sha256(output).digest(),
                    "motion_changed": measured["motion_sha256"] != baseline_metrics["motion_sha256"],
                    "machine_commands_changed": measured["machine_command_sha256"] !=
                                                baseline_metrics["machine_command_sha256"],
                    "note": "Offline native comparison only; physical purge is unverified.",
                }
            if creality_route_flush_controls is not None:
                summary["creality_tower_flush_sensitivity"] = {}
                for name, candidate in creality_route_flush_controls:
                    native_output = slice_native(native["process"], candidate)
                    summary["creality_tower_flush_sensitivity"][name] = {
                        **_safe_native_result(native_output),
                        "emitted_gcode_setting_audit": _creality_emitted_setting_audit(
                            native_output),
                        "tower_deposition": tower_deposition_metrics(native_output),
                        "note": "Offline isolated source-setting comparison; not validated purge volume.",
                    }
                controls = summary["creality_tower_flush_sensitivity"]
                for name, parent_name in (
                        ("tower_flush_multiplier_1_0", "tower_flush_multiplier_2_0"),
                        ("tower_flush_forward_2_0", "tower_flush_multiplier_2_0")):
                    current = controls[name]
                    parent = controls[parent_name]
                    current["vs_multiplier_2_0"] = {
                        "motion_changed": current["motion_sha256"] != parent["motion_sha256"],
                        "machine_commands_changed": (
                            current["machine_command_sha256"] != parent["machine_command_sha256"]),
                        "tower_extrusion_changed": (
                            current["tower_deposition"]["positive_e_length_mm"] !=
                            parent["tower_deposition"]["positive_e_length_mm"]),
                        "tower_xy_changed": (
                            current["tower_deposition"]["xy_width_mm"] !=
                            parent["tower_deposition"]["xy_width_mm"]
                            or current["tower_deposition"]["xy_depth_mm"] !=
                            parent["tower_deposition"]["xy_depth_mm"]),
                    }
                summary["creality_tower_flush_sensitivity"]["provenance"] = {
                    "matrix_source": "candidate_builder_140mm3_fallback_unverified"
                    if matrix_source == "candidate_builder_140mm3_fallback_unverified"
                    else matrix_source,
                    "directional_control": "t0_to_t1_plus_25_mm3_at_multiplier_2_0",
                    "scope": "disposable_native_3mf_with_printer_purge_and_process_flush_markers",
                    "physical_purge": "unverified",
                }
            # Compare the two route controls directly to the same 2.0
            # reference rather than only to a potentially different baseline.
            route_reference = summary["creality_flush_controls"]["multiplier_2_0"]
            for route_name in ("purge_route_tower", "purge_route_toolchange"):
                current = summary["creality_flush_controls"][route_name]
                current["motion_changed_vs_multiplier_2_0"] = (
                    current["motion_sha256"] != route_reference["motion_sha256"])
                current["machine_commands_changed_vs_multiplier_2_0"] = (
                    current["machine_command_sha256"] !=
                    route_reference["machine_command_sha256"])
                current["tower_extrusion_changed_vs_multiplier_2_0"] = (
                    current["tower_deposition"]["positive_e_length_mm"] !=
                    route_reference["tower_deposition"]["positive_e_length_mm"])
            prime_control = summary["creality_flush_controls"]["prime_volume_positive_control"]
            prime_control["requested_prime_volume_mm3"] = 180
            prime_control["motion_changed_vs_multiplier_2_0"] = (
                prime_control["motion_sha256"] != route_reference["motion_sha256"])
            prime_control["machine_commands_changed_vs_multiplier_2_0"] = (
                prime_control["machine_command_sha256"] !=
                route_reference["machine_command_sha256"])
            prime_control["tower_extrusion_changed_vs_multiplier_2_0"] = (
                prime_control["tower_deposition"]["positive_e_length_mm"] !=
                route_reference["tower_deposition"]["positive_e_length_mm"])
            # All four marked controls use explicit parent names. The
            # prime-volume parent is NOT named "prime_volume".
            for marked_name, parent_name in (
                    ("multiplier_1_0_marked", "multiplier_1_0"),
                    ("multiplier_2_0_marked", "multiplier_2_0"),
                    ("prime_volume_marked", "prime_volume_positive_control"),
                    ("purge_route_tower_marked", "purge_route_tower"),
                    ("purge_route_tower_printer_marked", "purge_route_tower")):
                summary["creality_flush_controls"][marked_name].update(
                    _creality_marked_result_comparison(
                        summary["creality_flush_controls"], marked_name, parent_name))
            summary["creality_flush_controls"]["forward"]["requested_t0_to_t1_mm3"] = first_flush_volume + 25
            summary["native_tool_selects_observed"] = {
                "t0": baseline_metrics["tool0_selects"],
                "t1": baseline_metrics["tool1_selects"],
                "both_tool_ids_seen": (
                    baseline_metrics["tool0_selects"] > 0
                    and baseline_metrics["tool1_selects"] > 0),
                "note": "Native tool ID observations, NOT physical CFS tool-change or purge proof.",
            }
            for requested in multiplier_controls:
                name = "multiplier_" + str(requested).replace(".", "_")
                summary["creality_flush_controls"][name]["requested_multiplier"] = requested
                summary["creality_flush_controls"][name + "_marked"]["requested_multiplier"] = requested
                summary["creality_flush_controls"][name + "_marked"]["override_markers"] = (
                    "flush_multiplier;flush_volumes_matrix;flush_volumes_changed")
            summary["creality_flush_basis"]["multiplier_control_origin"] = (
                "explicit_disposable_1_00_vs_2_00_not_native_default")
        after = verified_installation().get(engine)
        if after != installed:
            raise CommandError("Pinned engine approval changed during offline diagnostics.")
        self.stdout.write(json.dumps(summary, indent=2))
