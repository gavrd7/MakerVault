"""Disposable, offline Orca diagnostic fixture runner; never exposed as API.

Uses the same command and reference profiles as the real acceptance probe but
prints bounded process diagnostics. Run only in the restricted CI container,
never in production with user content or secrets.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from .headless_env import slicing_environment
from .orca_runner import orca_command
from .probe import fixture_stl


def diagnose(printer, filament, process, binary, *, model=None, second_filament=None):
    with tempfile.TemporaryDirectory(prefix="makervault-orca-diagnostic-") as directory:
        root = Path(directory)
        if model is not None:
            source = Path(model)
            if source.is_symlink() or not source.is_file() or not 0 < source.stat().st_size <= 32 * 1024 * 1024:
                raise ValueError("Unsafe diagnostic 3MF.")
            shutil.copyfile(source, root / "input.3mf")
        else:
            (root / "input.stl").write_bytes(fixture_stl())
        for name, source in (("printer", printer), ("filament", filament), ("process", process)):
            source = Path(source)
            if source.is_symlink() or not source.is_file() or not 0 < source.stat().st_size <= 1024 * 1024:
                raise ValueError("Unsafe diagnostic profile.")
            shutil.copyfile(source, root / (name + ".json"))
        if second_filament is not None:
            source = Path(second_filament)
            if model is None or source.is_symlink() or not source.is_file() or not 0 < source.stat().st_size <= 1024 * 1024:
                raise ValueError("Unsafe diagnostic second filament.")
            shutil.copyfile(root / "filament.json", root / "filament-0.json")
            shutil.copyfile(source, root / "filament-1.json")
        command = orca_command(Path(binary), root)
        # Diagnostic data is bounded in its display, only public upstream
        # profiles are used in CI; never emit arbitrary user-supplied files.
        result = subprocess.run(command, cwd=root, env=slicing_environment(root),
                                capture_output=True, timeout=120, check=False)
        print(json.dumps({
            "returncode": result.returncode,
            "stdout_tail": result.stdout.decode("utf-8", "replace")[-5000:],
            "stderr_tail": result.stderr.decode("utf-8", "replace")[-5000:],
            "output_names": [p.name for p in (root / "orca-output").iterdir()]
                            if (root / "orca-output").is_dir() else [],
        }, indent=2))
        return result.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", default="/opt/engines/orcaslicer.AppImage")
    for name in ("printer", "filament", "process"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--model", help="Official, locally generated two-tool 3MF fixture.")
    parser.add_argument("--second-filament", help="Official second filament preset.")
    args = parser.parse_args()
    diagnose(args.printer, args.filament, args.process, args.binary,
             model=args.model, second_filament=args.second_filament)


if __name__ == "__main__":
    main()
