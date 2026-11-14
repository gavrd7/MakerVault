"""Run the real Orca binary offline in a disposable staging container.

Requires the staging installer and three audited, fully resolved native JSON
profiles. Does not start printers, approve fixtures, or expose Docker's socket.

python3 scripts/probe_slicer_staging.py --printer printer.json \
  --filament filament.json --process process.json
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
DOTENV = ROOT / ".slicer-staging.env"
MAX_PROFILE_BYTES = 1024 * 1024
IMAGE_ID = re.compile(r"^sha256:[a-f0-9]{64}$")


# Direct script invocation puts scripts/ (not the repository root) on sys.path.
# Resolve the shared installer package consistently for CLI and unit imports.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.install_slicer_staging import APPROVED_ORCA_RELEASES


def _pinned_details(config=DOTENV):
    if config.is_symlink() or not config.is_file() or config.stat().st_mode & 0o077:
        raise ValueError("Private staging installer environment (.slicer-staging.env) is required.")
    variables = {}
    for line in config.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            variables[key.strip()] = value.strip().strip(chr(39) + chr(34))
    image = variables.get("MAKERVAULT_SLICER_WORKER_IMAGE", "")
    if not IMAGE_ID.fullmatch(image) or variables.get("MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST") != image:
        raise ValueError("Worker image is not pinned to the configured immutable SHA-256 ID.")
    engines = json.loads(variables.get("SLICER_ENGINES_JSON", "{}"))
    orca = engines.get("orcaslicer")
    if not isinstance(orca, dict) or orca.get("version") not in APPROVED_ORCA_RELEASES or orca.get("binary") != "/opt/engines/orcaslicer.AppImage":
        raise ValueError("The approved pinned Orca worker is not present in the staging manifest.")
    if not re.fullmatch("[a-f0-9]{64}", str(orca.get("binary_sha256", ""))):
        raise ValueError("Orca executable digest is missing or invalid.")
    return image, orca["version"]


def _pinned_image(config=DOTENV):
    """Compatibility helper for callers needing only the immutable image."""
    return _pinned_details(config)[0]


def probe(printer, filament, process, *, model=None, compound=False, experimental_all_plates=False, experimental_no_arrange=False, verify_object_effects=False, reverse_object_effects=False, second_filament=None, audit_changeovers=False, config=DOTENV, runner=subprocess.run):
    """Exercise real engine without app, network, Docker socket or host mounts."""
    image, installed_version = _pinned_details(config)
    sources = {"printer": printer, "filament": filament, "process": process}
    if audit_changeovers and second_filament is None:
        raise ValueError("Changeover audit requires two native filament profiles.")
    if second_filament is not None:
        if model is None or compound or verify_object_effects:
            raise ValueError("Two-tool probing requires an independent two-object 3MF.")
        sources["filament-1"] = second_filament
    with tempfile.TemporaryDirectory(prefix="makervault-slicer-probe-") as tmp:
        bundle = Path(tmp)
        bundle.chmod(0o755)
        for name, filename in sources.items():
            source = Path(filename)
            if source.is_symlink() or not source.is_file() or not 0 < source.stat().st_size <= MAX_PROFILE_BYTES:
                raise ValueError(f"{name} profile must be a regular JSON file no larger than 1 MiB.")
            raw = source.read_bytes()
            if len(raw) > MAX_PROFILE_BYTES:
                raise ValueError(f"{name} native profile exceeds 1 MiB.")
            try:
                data = json.loads(raw.decode("utf-8-sig"))
            except (ValueError, UnicodeError):
                raise ValueError(f"{name} native profile is not valid UTF-8 JSON.") from None
            if not isinstance(data, dict) or data.get("inherits"):
                raise ValueError(f"{name} profile must be fully resolved, without an inherits parent.")
            dest = bundle / f"{name}.json"
            dest.write_bytes(raw)
            dest.chmod(0o444)
        if model is not None:
            source = Path(model)
            if (source.is_symlink() or not source.is_file() or
                    source.suffix.lower() != ".3mf" or
                    not 0 < source.stat().st_size <= 32 * 1024 * 1024):
                raise ValueError("Multi-model fixture must be a bounded regular 3MF file.")
            # The worker independently checks the exact three allowed ZIP
            # members, mesh count, and all finite geometry/transforms.
            dest = bundle / "fixture.3mf"
            dest.write_bytes(source.read_bytes())
            dest.chmod(0o444)
        command = [
            "docker", "run", "--rm", "--network", "none", "--read-only",
            "--user", "10001:10001", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true", "--pids-limit", "96",
            "--memory", "3g", "--cpus", "2",
            "--tmpfs", "/tmp:rw,exec,nosuid,nodev,size=1g,mode=1777",
            "--mount", f"type=bind,src={bundle},dst=/fixtures,readonly",
            "--entrypoint", "python3", image,
            "-m", "slicer_worker.probe", "--engine", "orcaslicer",
            "--version", installed_version, "--binary", "/opt/engines/orcaslicer.AppImage",
            "--printer", "/fixtures/printer.json",
            "--filament", "/fixtures/filament.json",
            "--process", "/fixtures/process.json",
        ]
        if model is not None:
            command.extend(["--model", "/fixtures/fixture.3mf", "--expected-objects",
                            "1" if compound else "2"])
            if second_filament is not None:
                command.extend(["--second-filament", "/fixtures/filament-1.json"])
                if audit_changeovers:
                    command.append("--audit-changeovers")
            if compound:
                command.extend(["--expected-islands", "2"])
            if experimental_all_plates:
                command.append("--experimental-all-plates")
            if experimental_no_arrange:
                command.append("--experimental-no-arrange")
            if verify_object_effects:
                command.append("--verify-object-effects")
            if reverse_object_effects:
                command.append("--reverse-object-effects")
        return runner(command, check=False).returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("printer", "filament", "process"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--model", type=Path, help="Optional two-object MakerVault 3MF acceptance fixture")
    parser.add_argument("--second-filament", type=Path,
                        help="Second ordered native filament for offline real-Orca tool verification")
    parser.add_argument("--audit-changeovers", action="store_true",
                        help="Collect offline native toolchange and non-model extrusion evidence")
    parser.add_argument("--compound", action="store_true", help="Experimental combined-mesh 3MF geometry-island test")
    parser.add_argument("--experimental-all-plates", action="store_true", help="Offline diagnostic: slice all native plates")
    parser.add_argument("--experimental-no-arrange", action="store_true", help="Offline diagnostic: disable native auto-arrange")
    parser.add_argument("--verify-object-effects", action="store_true", help="Require measurable differences between the two native cube objects")
    parser.add_argument("--reverse-object-effects", action="store_true", help="Require stronger extrusion on the first cube after swapping native settings")
    args = parser.parse_args(argv)
    try:
        return probe(args.printer, args.filament, args.process, model=args.model, compound=args.compound,
                     experimental_all_plates=args.experimental_all_plates,
                     experimental_no_arrange=args.experimental_no_arrange,
                     verify_object_effects=args.verify_object_effects,
                     reverse_object_effects=args.reverse_object_effects,
                     second_filament=args.second_filament,
                     audit_changeovers=args.audit_changeovers)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print("Offline Orca acceptance probe refused: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
