"""Bambu Studio CLI contract in the isolated MakerVault worker.

Kept separate from Orca's executable runner: shared ancestry does not prove
identical native 3MF output, profile/resource resolution or firmware mapping.
The approved isolated worker must provide a reviewed Bambu executable.
"""
import os
import logging
import io
import json
from xml.etree import ElementTree as ET
import re
import signal
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path

from .runner import MAX_GCODE_BYTES, MAX_MODEL_BYTES, MAX_PROFILE_BYTES, DEFAULT_TIMEOUT_SECONDS
from .runner import WorkerError, _regular_file, _output_path
from .orca_runner import _native_json
from .headless_env import slicing_environment
from .stl_validation import StlValidationError, validate_stl
from .three_mf_validation import validate_worker_3mf, BAMBU_VARIANT_OPTIONS, CORE_NS

logger = logging.getLogger(__name__)


def _native_project_matches_palette(model: bytes, palette: list[Path]):
    """Cross-check every embedded native Bambu material vector against the
    exact resolved owner-scoped preset staged for this job. No CLI override of
    second+ slots: pinned Bambu Studio 2.9.1 double-frees on that path.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(model)) as archive:
            settings = json.loads(archive.read("Metadata/project_settings.config"))
            root = ET.fromstring(archive.read("3D/3dmodel.model"))
        markers = [(n.get("name"), n.text) for n in root
                   if n.tag == "{" + CORE_NS + "}metadata"
                   and n.get("name") in ("Application", "BambuStudio:3mfVersion")]
        if markers != [("Application", "BambuStudio-02.09.01.70"),
                       ("BambuStudio:3mfVersion", "1")]:
            raise ValueError("missing Bambu-native identity")
        documents = [json.loads(path.read_bytes()) for path in palette]
        names = []
        types = []
        diameters = []
        ids = []
        support = []
        indices = []
        variants = []
        material_values = {key: [] for key in BAMBU_VARIANT_OPTIONS}
        for index, doc in enumerate(documents, 1):
            scalar = lambda key: (doc[key][0] if isinstance(doc.get(key), list)
                                 and len(doc[key]) == 1 else doc[key])
            names.append(scalar("name"))
            types.append(scalar("filament_type"))
            diameters.append(scalar("filament_diameter"))
            ids.append(scalar("filament_id"))
            support.append(scalar("filament_is_support")
                           if "filament_is_support" in doc else "0")
            native_variants = doc["filament_extruder_variant"]
            if not isinstance(native_variants, list) or not native_variants:
                raise ValueError("missing native filament variant")
            variants.extend(native_variants)
            indices.extend([str(index)] * len(native_variants))
            for key in material_values:
                material_values[key].extend(doc[key])
        expected = {
            "filament_settings_id": names, "filament_type": types,
            "filament_diameter": diameters, "filament_ids": ids,
            "filament_is_support": support,
            "filament_self_index": indices,
            "filament_extruder_variant": variants,
            **material_values,
        }
        if any(settings.get(key) != value for key, value in expected.items()):
            raise ValueError("native material vectors differ")
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError,
            zipfile.BadZipFile, IndexError) as exc:
        raise WorkerError(
            "Bambu native project does not match the selected filament profiles.") from None


def _select_single_nozzle_cli_variant(printer: Path) -> bool:
    """Normalise a proven Bambu CLI dual-variant fault in scratch only.

    Upstream BambuStudio issue #11893 documents that a single CSV value
    advertising Standard + High Flow can trigger a multi-extruder CLI path.
    Never guess a nozzle/extruder type: require a single physical nozzle and
    an unambiguous selected Standard/High Flow variant. This file is the
    isolated worker's transient copy; imported original profiles stay intact.
    """
    try:
        profile = json.loads(printer.read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeError, OSError):
        raise WorkerError("Invalid Bambu CLI machine profile.") from None
    if not isinstance(profile, dict):
        raise WorkerError("Invalid Bambu CLI machine profile.")
    nozzle = profile.get("nozzle_diameter")
    if not isinstance(nozzle, list) or len(nozzle) != 1:
        return False  # Do not collapse actual multiple-nozzle configurations.
    options = profile.get("extruder_variant_list")
    selected = profile.get("printer_extruder_variant")
    allowed = ("Direct Drive Standard", "Direct Drive High Flow")
    combined = ",".join(allowed)
    if options not in ([combined], list(allowed)):
        return False
    if selected not in ([combined], [allowed[0]], [allowed[1]]):
        return False
    if selected in ([allowed[0]], [allowed[1]]):
        chosen = selected[0]
    else:
        # A preset exposing both possible extruders is not by itself proof
        # which is fitted. The explicit native nozzle-volume selection is.
        volume = profile.get("nozzle_volume_type")
        if volume in ("Standard", ["Standard"]):
            chosen = allowed[0]
        elif volume in ("High Flow", ["High Flow"]):
            chosen = allowed[1]
        else:
            logger.warning("Bambu CLI extruder variant: ambiguous single-nozzle selection")
            return False
    profile["extruder_variant_list"] = [chosen]
    profile["printer_extruder_variant"] = [chosen]
    printer.write_text(json.dumps(profile, ensure_ascii=False, separators=(",", ":")),
                       encoding="utf-8")
    logger.info("Bambu CLI single-nozzle variant normalised in worker scratch")
    return True


def bambu_command(binary: Path, workdir: Path) -> list[str]:
    """Build fixed, documented Bambu CLI flags; no user-selected arguments."""
    binary = Path(binary)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise WorkerError("Reviewed Bambu Studio executable is unavailable.")
    if binary.is_symlink():
        # Official AppImage extraction may ship AppRun as a link to an
        # executable inside the same extracted bundle. Never follow a link
        # outside that bundle or accept symlinks under other entrypoint names.
        try:
            target = binary.resolve(strict=True)
            if binary.name != "AppRun" or not target.is_relative_to(binary.parent.resolve(strict=True)):
                raise WorkerError("Bambu Studio executable symlink escapes its bundle.")
        except (OSError, RuntimeError, ValueError) as exc:
            raise WorkerError("Bambu Studio executable symlink is invalid.") from exc
    workdir = Path(workdir).resolve(strict=True)
    stl = workdir / "input.stl"
    three_mf = workdir / "input.3mf"
    if stl.is_file() and not stl.is_symlink() and not three_mf.exists():
        model = _regular_file(workdir, "input.stl", MAX_MODEL_BYTES)
        try:
            validate_stl(model.read_bytes())
        except StlValidationError as exc:
            raise WorkerError("Input STL failed structural validation.") from exc
        is_stl = True
    elif three_mf.is_file() and not three_mf.is_symlink() and not stl.exists():
        model = _regular_file(workdir, "input.3mf", MAX_MODEL_BYTES)
        is_stl = False
    else:
        raise WorkerError("Choose exactly one supported STL or 3MF input.")
    printer = _regular_file(workdir, "printer.json", MAX_PROFILE_BYTES)
    process = _regular_file(workdir, "process.json", MAX_PROFILE_BYTES)
    filament = _regular_file(workdir, "filament.json", MAX_PROFILE_BYTES)
    # Bambu upstream explicitly requires *complete* native profiles.
    # Reuse existing scratch-only network-key sanitisation and post-process
    # rejection; never resolve unknown inheritance to arbitrary host files.
    for profile in (printer, process, filament):
        _native_json(profile)
    _select_single_nozzle_cli_variant(printer)
    # Use the exact worker-validated 0-based native filament palette.
    # Bambu CLI accepts a semicolon-separated list of complete native JSON
    # presets; never infer it from a physical AMS/CFS slot index.
    palette = []
    for index in range(16):
        candidate = workdir / ("filament-" + str(index) + ".json")
        if candidate.is_symlink():
            raise WorkerError("Bambu native palette cannot contain links.")
        if not candidate.exists():
            if any((workdir / ("filament-" + str(other) + ".json")).exists()
                   for other in range(index + 1, 16)):
                raise WorkerError("Bambu native palette must be contiguous.")
            break
        palette.append(_regular_file(workdir, candidate.name, MAX_PROFILE_BYTES))
    if palette:
        if is_stl or len(palette) < 2:
            raise WorkerError("Bambu multi-filament slicing requires 3MF and two or more native presets.")
        if palette[0].read_bytes() != filament.read_bytes():
            raise WorkerError("Bambu first native palette preset must match the selected filament.")
        for candidate in palette:
            _native_json(candidate)
    if not is_stl:
        # Validate extruder metadata against the *same* ordered native
        # palette used for the Bambu CLI. Validating without the palette
        # would accidentally reject legitimate per-object extruder keys.
        native_modifiers = (workdir / "native-modifier-project.marker").exists()
        if native_modifiers and palette:
            raise WorkerError("Modifier jobs cannot include an unverified multi-tool palette.")
        validate_worker_3mf(model.read_bytes(),
            native_tool_count=len(palette) if palette else None,
            allow_bambu_project=not native_modifiers,
            allow_bambu_combined_paint=bool(palette),
            allow_bambu_layer_ranges=bool(palette),
            allow_native_modifier_fixture=native_modifiers)
        if palette:
            _native_project_matches_palette(model.read_bytes(), palette)
    _output_path(workdir)
    output = workdir / "bambu-sliced.3mf"
    if output.exists() or output.is_symlink():
        raise WorkerError("Bambu Studio output already exists.")
    args = [str(binary)]
    if is_stl:
        # The upstream documented STL flow needs a placement arrangement.
        args += ["--arrange", "1"]
    args += ["--load-settings", str(printer) + ";" + str(process)]
    if not palette:
        args += ["--load-filaments", str(filament)]
    # For native multi-material 3MF, exact per-variant filament settings are
    # embedded and cross-checked above. Loading CLI filament 2+ corrupts
    # memory in the official pinned 02.09.01.70 executable.
    args += ["--slice", "0", "--export-3mf", str(output), str(model)]
    return args


def extract_single_bambu_gcode(sliced_project: Path, workdir: Path) -> Path:
    """Extract exactly one bounded plain G-code plate from native sliced 3MF.

    No arbitrary ZIP files or member names are extracted to the filesystem.
    Actual native 2.9.1 output/member layout still requires pinned-binary proof.
    """
    archive = _regular_file(workdir, sliced_project.name, 128 * 1024 * 1024)
    if archive.name != "bambu-sliced.3mf":
        raise WorkerError("Unexpected Bambu output artifact.")
    try:
        with zipfile.ZipFile(archive) as zf:
            if len(zf.infolist()) > 2000:
                raise WorkerError("Bambu native 3MF has too many entries.")
            matches = []
            seen_names = set()
            for info in zf.infolist():
                name = info.filename
                if name in seen_names:
                    raise WorkerError("Bambu native 3MF contains duplicate entries.")
                seen_names.add(name)
                # Reject unrecognized G-code members as well as multiple
                # recognised plates; never silently omit an unexpected toolpath.
                if name.lower().endswith(".gcode") and not re.fullmatch(
                        r"Metadata/plate_[1-9][0-9]*\.gcode", name):
                    raise WorkerError("Bambu native output includes an unexpected G-code plate.")
                if re.fullmatch(r"Metadata/plate_[1-9][0-9]*\.gcode", name):
                    if info.file_size <= 0 or info.file_size > MAX_GCODE_BYTES:
                        raise WorkerError("Bambu G-code exceeds size limits.")
                    if stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK:
                        raise WorkerError("Bambu output cannot contain symlink G-code.")
                    matches.append(info)
            if len(matches) != 1:
                raise WorkerError(
                    "Bambu native output must contain exactly one G-code plate.")
            output = _output_path(workdir)
            total = 0
            head = b""
            # Read only one plate in chunks; do not trust ZIP header sizes.
            try:
                with zf.open(matches[0]) as source, output.open("xb") as target:
                    while block := source.read(65536):
                        total += len(block)
                        if total > MAX_GCODE_BYTES:
                            raise WorkerError("Bambu G-code exceeds size limits.")
                        if len(head) < 4096:
                            head += block[:4096 - len(head)]
                        target.write(block)
            except BaseException:
                output.unlink(missing_ok=True)
                raise
    except WorkerError:
        raise
    except (zipfile.BadZipFile, EOFError, OSError, RuntimeError, ValueError) as exc:
        raise WorkerError("Bambu native 3MF output is invalid.") from exc
    if not total or b"\0" in head:
        output.unlink(missing_ok=True)
        raise WorkerError("Bambu generated unsupported binary or empty G-code.")
    return output


def _bambu_headless_environment(workdir: Path) -> dict[str, str]:
    """Provide Bambu writable XDG directories entirely inside job scratch.

    Its AppImage can start without a desktop while still creating settings,
    caches and runtime files. Do not let it fall back to an installer-owned
    executable tree, persistent host home or shared /tmp directory.
    """
    root = Path(workdir).resolve(strict=True)
    env = slicing_environment(root)
    for name, key in (
        ("xdg-config", "XDG_CONFIG_HOME"),
        ("xdg-cache", "XDG_CACHE_HOME"),
        ("xdg-data", "XDG_DATA_HOME"),
        ("xdg-runtime", "XDG_RUNTIME_DIR"),
    ):
        directory = root / name
        if directory.is_symlink():
            raise WorkerError("Unsafe Bambu scratch runtime directory.")
        directory.mkdir(mode=0o700, exist_ok=True)
        if not directory.is_dir() or directory.resolve() != directory:
            raise WorkerError("Invalid Bambu scratch runtime directory.")
        directory.chmod(0o700)
        env[key] = str(directory)
    return env


def _filesystem_error_details(tail: bytes) -> tuple[str, str]:
    """Only derive fixed diagnostic categories; never relay exception paths."""
    tail = tail.lower()
    if b"permission denied" in tail or b"operation not permitted" in tail:
        reason = "permission"
    elif b"no such file or directory" in tail:
        reason = "missing-path"
    elif b"read-only file system" in tail:
        reason = "read-only"
    elif b"file exists" in tail:
        reason = "already-exists"
    elif b"not a directory" in tail:
        reason = "not-directory"
    elif b"no space left on device" in tail:
        reason = "no-space"
    else:
        reason = "unknown"
    if b"/opt/engine-store/" in tail:
        area = "engine-store"
    elif b"makervault-slice-" in tail:
        area = "worker-scratch"
    elif b"/tmp/" in tail:
        area = "temporary"
    else:
        area = "unknown"
    return reason, area


def run_bambu(binary: Path, workdir: Path, *, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> dict:
    """Execute exact approved Bambu Studio in the isolated worker.

    The worker container, not this helper, is responsible for filesystem,
    network, identity and resource isolation. Real Bambu CLI acceptance is
    required before the service may route jobs here.
    """
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 900:
        raise WorkerError("Invalid Bambu slice timeout.")
    workdir = Path(workdir).resolve(strict=True)
    if not workdir.is_dir():
        raise WorkerError("Worker scratch directory is invalid.")
    command = bambu_command(binary, workdir)
    try:
        # Bounded, ephemeral diagnostics stay in an anonymous temporary file.
        # Never persist or relay native CLI output, file paths or profile data.
        with tempfile.TemporaryFile(mode="w+b") as diagnostics:
            proc = subprocess.Popen(
                command, cwd=str(workdir),
                env={**_bambu_headless_environment(workdir),
                     # Bambu 2.9.x can dereference a missing SSL_CERT_FILE even
                     # in headless/offline CLI startup.
                     "SSL_CERT_FILE": "/etc/ssl/certs/ca-certificates.crt"},
                stdout=diagnostics, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                proc.communicate(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.communicate()
                raise WorkerError("Bambu Studio slicing timed out.") from None
            if proc.returncode != 0:
                logger.warning("Bambu Studio native CLI exited with status %d", proc.returncode)
                if proc.returncode == 126:
                    raise WorkerError("Bambu Studio native runtime exited with status 126.")
                if proc.returncode == -signal.SIGABRT:
                    diagnostics.seek(0, os.SEEK_END)
                    total = diagnostics.tell()
                    diagnostics.seek(max(0, total - 8192), os.SEEK_SET)
                    tail = diagnostics.read(8192).lower()
                    # Classify only fixed public libc/loader markers. Never
                    # log the raw bytes; they may contain user profile data.
                    if b"double free" in tail or b"corruption" in tail:
                        cause = "allocator"
                    elif b"assertion" in tail or b"assert failed" in tail:
                        cause = "assertion"
                    elif b"terminate called" in tail or b"uncaught exception" in tail:
                        cause = "uncaught-exception"
                    else:
                        cause = "unclassified"
                    # Only constant, reviewed C++ exception types can appear
                    # in logs. The exception what() text can contain paths,
                    # user data and native profile values, so never emit it.
                    if cause == "uncaught-exception":
                        known_types = (
                            (b"filesystem_error", "filesystem-error"),
                            (b"bad_alloc", "bad-allocation"),
                            (b"out_of_range", "out-of-range"),
                            (b"invalid_argument", "invalid-argument"),
                            (b"length_error", "length-error"),
                            (b"domain_error", "domain-error"),
                            (b"range_error", "range-error"),
                            (b"logic_error", "logic-error"),
                            (b"runtime_error", "runtime-error"),
                        )
                        subtype = next((name for marker, name in known_types
                                        if marker in tail), "unknown")
                        logger.warning("Bambu Studio SIGABRT exception type: %s", subtype)
                    if b"filesystem_error" in tail:
                        reason, area = _filesystem_error_details(tail)
                        logger.warning("Bambu Studio filesystem exception: reason=%s area=%s",
                                       reason, area)
                    logger.warning("Bambu Studio SIGABRT classified: %s", cause)
                    raise WorkerError("Bambu Studio native CLI aborted with SIGABRT.")
                raise WorkerError("Bambu Studio CLI rejected the native profiles or model.")
        output = extract_single_bambu_gcode(workdir / "bambu-sliced.3mf", workdir)
        return {"status": "completed", "gcode_path": str(output),
                "bytes": output.stat().st_size}
    except OSError as exc:
        raise WorkerError("Isolated worker could not execute Bambu Studio.") from exc
