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


def _pinned_image(config=DOTENV):
    if config.is_symlink() or not config.is_file() or config.stat().st_mode & 0o077:
        raise ValueError("Private staging installer environment (.slicer-staging.env) is required.")
    variables = {}
    for line in config.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            variables[key.strip()] = value.strip().strip("'\\"")
    image = variables.get("MAKERVAULT_SLICER_WORKER_IMAGE", "")
    if not IMAGE_ID.fullmatch(image) or variables.get("MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST") != image:
        raise ValueError("Worker image is not pinned to the configured immutable SHA-256 ID.")
    engines = json.loads(variables.get("SLICER_ENGINES_JSON", "{}"))
    orca = engines.get("orcaslicer")
    if not isinstance(orca, dict) or orca.get("version") != "2.4.2" or orca.get("binary") != "/opt/engines/orcaslicer.AppImage":
        raise ValueError("The pinned Orca 2.4.2 worker is not present in the staging manifest.")
    if not re.fullmatch("[a-f0-9]{64}", str(orca.get("binary_sha256", ""))):
        raise ValueError("Orca executable digest is missing or invalid.")
    return image


def probe(printer, filament, process, *, config=DOTENV, runner=subprocess.run):
    """Exercise real engine without app, network, Docker socket or host mounts."""
    image = _pinned_image(config)
    sources = {"printer": printer, "filament": filament, "process": process}
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
        command = [
            "docker", "run", "--rm", "--network", "none", "--read-only",
            "--user", "10001:10001", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true", "--pids-limit", "96",
            "--memory", "3g", "--cpus", "2",
            "--tmpfs", "/tmp:rw,exec,nosuid,nodev,size=1g,mode=1777",
            "--mount", f"type=bind,src={bundle},dst=/fixtures,readonly",
            "--entrypoint", "python3", image,
            "-m", "slicer_worker.probe", "--engine", "orcaslicer",
            "--version", "2.4.2", "--binary", "/opt/engines/orcaslicer.AppImage",
            "--printer", "/fixtures/printer.json",
            "--filament", "/fixtures/filament.json",
            "--process", "/fixtures/process.json",
        ]
        return runner(command, check=False).returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("printer", "filament", "process"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        return probe(args.printer, args.filament, args.process)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print("Offline Orca acceptance probe refused: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
