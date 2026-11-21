"""Bambu Studio CLI contract candidate; NOT worker-enabled until binary acceptance.

Kept separate from Orca's executable runner: shared ancestry does not prove
identical native 3MF output, profile/resource resolution or firmware mapping.
The approved isolated worker must provide a reviewed Bambu executable.
"""
import os
import re
import stat
import zipfile
from pathlib import Path

from .runner import MAX_GCODE_BYTES, MAX_MODEL_BYTES, MAX_PROFILE_BYTES
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
            for info in zf.infolist():
                name = info.filename
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
            raw = zf.read(matches[0])
    except (zipfile.BadZipFile, EOFError, OSError, RuntimeError) as exc:
        raise WorkerError("Bambu native 3MF output is invalid.") from exc
    if not raw or len(raw) > MAX_GCODE_BYTES or b"\0" in raw[:4096]:
        raise WorkerError("Bambu generated unsupported binary or empty G-code.")
    output = _output_path(workdir)
    with output.open("xb") as stream:
        stream.write(raw)
    return output
