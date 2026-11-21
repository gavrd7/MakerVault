"""Stage independently reviewed Orca/Creality Linux AppImages for a local worker build.

This helper NEVER downloads anything. Obtain the exact official Linux asset
and independently confirm its expected SHA-256 before invoking it.

Example:
 python3 -m slicer_worker.stage_engines \
   --engine orcaslicer 2.4.2 /tmp/OrcaSlicer.AppImage <64-hex-sha256>

Build a candidate image with:
 docker build -f slicer_worker/Dockerfile.bundle -t makervault-slicer-candidate:local .
No binary or image is automatically approved by this step.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys

ENGINES = frozenset({"orcaslicer", "crealityprint"})
HEX = re.compile(r"^[0-9a-f]{64}$")
VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,79}$")
LIMIT_BYTES = 1024 * 1024 * 1024


def stage_engines(selections, destination):
    """Stage each independently selected binary into a local ignored directory."""
    if not selections or len(selections) > len(ENGINES):
        raise ValueError("Select one or two independent engines.")
    requested = {}
    for engine, version, filename, checksum in selections:
        if engine not in ENGINES or engine in requested:
            raise ValueError("Select unique OrcaSlicer or Creality Print engines.")
        if not VERSION.fullmatch(version) or not HEX.fullmatch(checksum):
            raise ValueError("Engine version and SHA-256 are required.")
        source = Path(filename)
        if (source.is_symlink() or not source.is_file() or
                not source.name.endswith(".AppImage") or
                not 0 < source.stat().st_size <= LIMIT_BYTES):
            raise ValueError("Select a regular official Linux AppImage below 1 GiB.")
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != checksum:
            raise ValueError("Expected SHA-256 did not match the " + engine + " asset.")
        requested[engine] = (version, source, checksum)
    target = Path(destination)
    if target.exists():
        if target.is_symlink() or not target.is_dir() or any(target.iterdir()):
            raise ValueError("Staging destination must be an empty, non-symlinked directory.")
    else:
        target.mkdir(parents=True, mode=0o700)
    results = {}
    for engine, (version, source, checksum) in requested.items():
        staged = target / (engine + ".AppImage")
        with source.open("rb") as src, staged.open("xb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
        staged.chmod(0o555)
        results[engine] = {
            "binary": "/opt/engines/" + engine + ".AppImage",
            "version": version,
            "binary_sha256": checksum,
        }
    manifest = {"engines": results, "fixture_approved": False}
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "worker_engines_json": json.dumps(results, separators=(",", ":")),
        "app_approvals_json": json.dumps({
            k: {"version": v["version"], "binary_sha256": v["binary_sha256"]}
            for k, v in results.items()
        }, separators=(",", ":")),
        "assets_directory": str(target),
        "status": "staged_not_tested",
        "warning": "Build and test the worker in isolation. Do not enable app execution merely from a matching checksum.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", nargs=4, action="append", metavar=("ENGINE", "VERSION", "APPIMAGE", "SHA256"), required=True)
    parser.add_argument("--destination", default="slicer-engine-assets")
    args = parser.parse_args(argv)
    try:
        result = stage_engines(args.engine, args.destination)
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "rejected", "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
