"""Bambu Studio CLI contract candidate; NOT worker-enabled until binary acceptance.

Kept separate from Orca's executable runner: shared ancestry does not prove
identical native 3MF output, profile/resource resolution or firmware mapping.
The approved isolated worker must provide a reviewed Bambu executable.
"""
import os
import re
import signal
import stat
import subprocess
import zipfile
from pathlib import Path

from .runner import MAX_GCODE_BYTES, MAX_MODEL_BYTES, MAX_PROFILE_BYTES, DEFAULT_TIMEOUT_SECONDS
from .runner import WorkerError, _regular_file, _output_path
from .orca_runner import _native_json
from .stl_validation import StlValidationError, validate_stl
from .three_mf_validation import validate_worker_3mf


def bambu_command(binary: Path, workdir: Path) -> list[str]:
    """Build fixed, documented Bambu CLI flags; no user-selected arguments."""
    binary = Path(binary)
    if binary.is_symlink() or not binary.is_file() or not os.access(binary, os.X_OK):
        raise WorkerError("Reviewed Bambu Studio executable is unavailable.")
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
        validate_worker_3mf(model.read_bytes())
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
    _output_path(workdir)
    output = workdir / "bambu-sliced.3mf"
    if output.exists() or output.is_symlink():
        raise WorkerError("Bambu Studio output already exists.")
    args = [str(binary)]
    if is_stl:
        # The upstream documented STL flow needs a placement arrangement.
        args += ["--arrange", "1"]
    args += [
        "--load-settings", str(printer) + ";" + str(process),
        "--load-filaments", str(filament),
        "--slice", "0", "--export-3mf", str(output), str(model),
    ]
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
                if (name.startswith("Metadata/plate_") and
                        re.fullmatch(r"Metadata/plate_[1-9][0-9]*\.gcode", name)):
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


def run_bambu(binary: Path, workdir: Path, *, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> dict:
    """Candidate isolated executor; not registered for production admission.

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
        proc = subprocess.Popen(
            command, cwd=str(workdir),
            env={"HOME": str(workdir), "TMPDIR": str(workdir),
                 "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                 "PATH": "/usr/bin:/bin"},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            proc.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            raise WorkerError("Bambu Studio slicing timed out.") from None
        if proc.returncode != 0:
            raise WorkerError("Bambu Studio CLI rejected the native profiles or model.")
        output = extract_single_bambu_gcode(workdir / "bambu-sliced.3mf", workdir)
        return {"status": "completed", "gcode_path": str(output),
                "bytes": output.stat().st_size}
    except OSError as exc:
        raise WorkerError("Isolated worker could not execute Bambu Studio.") from exc
