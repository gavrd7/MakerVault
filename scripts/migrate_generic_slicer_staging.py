"""Explicit, reversible staging migration to the generic ONE-worker image.

This tool runs only on the host (with Docker access), not in MakerVault.
It preserves the existing staging engine, project data and original image.
It never touches printers or installs additional long-running containers.

  sudo python3 scripts/migrate_generic_slicer_staging.py preflight
  sudo python3 scripts/migrate_generic_slicer_staging.py migrate
  sudo python3 scripts/migrate_generic_slicer_staging.py rollback

Stop or finish any active slicing jobs BEFORE 'migrate' or 'rollback'.
The migration is NOT an application engine-update feature.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

# Direct script execution puts scripts/ (rather than the checkout) on sys.path.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import install_slicer_staging as staging

IMAGE = ("ghcr.io/gavrd7/makervault-slicer@sha256:"
         "3071c79f10ed50e8ecc9a1e6f576be8aa402ca6067682315cf1ed44a4fa45cce")
ENGINE_SHA = "b30b0ae933e653692cf85a493287a949215ae4c14d547a00203d16dfcadb8054"
BACKUP = staging.ROOT / ".slicer-staging.env.pre-generic"
VOLUME = "makervault_makervault_slicer_engines"
HEX = re.compile(r"^sha256:[a-f0-9]{64}$")


def _settings(raw):
    values = {}
    for line in raw.splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.startswith("#"):
            values[key] = value.strip().strip("'").strip('"')
    return values


def _verified_old_configuration():
    raw = staging._read_env()
    config = _settings(raw)
    worker = config.get("MAKERVAULT_SLICER_WORKER_IMAGE", "")
    digest = config.get("MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST", "")
    if not HEX.fullmatch(worker) or worker != digest:
        raise ValueError("Existing staging worker must use an immutable local image ID.")
    entry = json.loads(config.get("SLICER_ENGINES_JSON", "{}")).get("orcaslicer", {})
    approved = json.loads(config.get("MAKERVAULT_SLICER_ENGINES_JSON", "{}")).get("orcaslicer", {})
    if (entry.get("binary_sha256") != ENGINE_SHA or
            entry.get("version") != "2.5.0" or
            entry.get("binary") != "/opt/engines/orcaslicer.AppImage" or
            approved != {"version": "2.5.0", "binary_sha256": ENGINE_SHA}):
        raise ValueError("Existing engine is not the independently reviewed patched 2.5.0.")
    if config.get("MAKERVAULT_SLICER_EXECUTION_ENABLED") != "1":
        raise ValueError("Expected enabled staging worker; inspect staging before migration.")
    return raw, config


def _safe_run(args, *, capture=False):
    return staging._run(args, capture=capture)


def _candidate_image():
    _safe_run(["docker", "pull", IMAGE])
    image_id = _safe_run(["docker", "image", "inspect",
                          "--format", "{{.Id}}", IMAGE], capture=True)
    if not HEX.fullmatch(image_id):
        raise ValueError("Generic worker image has no immutable Docker image ID.")
    return image_id


def _container_check(image_id):
    # A separate disposable container validates the mounted persistent registry.
    code = (
        "import os; from slicer_worker.engine_registry import configured_engines; "
        "e=configured_engines(); assert 'orcaslicer' in e and "
        "e['orcaslicer']['version']=='2.5.0' and "
        "e['orcaslicer']['binary_sha256']==os.environ['EXPECTED_ENGINE_SHA']; "
        "print('PASS: persisted approved Orca engine')"
    )
    _safe_run(["docker", "run", "--rm", "--network", "none", "--read-only",
               "--user", "10001:10001", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges:true",
               "--mount", f"type=volume,src={VOLUME},dst=/opt/engine-store,readonly",
               "-e", "SLICER_WORKER_ENABLED=1",
               "-e", "SLICER_WORKER_TOKEN=" + "x" * 48,
               "-e", "EXPECTED_ENGINE_SHA=" + ENGINE_SHA,
               "--entrypoint", "python3", image_id, "-c", code])


def _seed_engine(image_id):
    _safe_run(["docker", "volume", "create", VOLUME])
    # A one-shot maintenance container writes the engine store. This is not
    # the live worker and exposes no network, ports, host credentials or socket.
    common = ["docker", "run", "--rm", "--network", "none",
              "--user", "0:0", "--cap-drop", "ALL",
              "--security-opt", "no-new-privileges:true",
              "--mount", f"type=volume,src={VOLUME},dst=/opt/engine-store",
              "--entrypoint", "python3", image_id,
              "-m", "slicer_worker.engine_store_admin"]
    # If a previous attempt installed the version but not its active manifest,
    # leave it intact and only activate after direct checksum verification.
    check = ("import json,pathlib; r=pathlib.Path('/opt/engine-store'); "
             "print(json.dumps({'seeded':(r/'versions/orcaslicer/2.5.0/orcaslicer.AppImage').exists(),"
             "'active':(r/'active.json').exists()}))")
    state = json.loads(_safe_run(["docker", "run", "--rm", "--network", "none",
                                  "--user", "0:0",
                                  "--mount", f"type=volume,src={VOLUME},dst=/opt/engine-store",
                                  "--entrypoint", "python3", image_id, "-c", check], capture=True))
    if state["active"]:
        # Never overwrite a pre-existing active engine selection.
        _container_check(image_id)
        return
    if not state["seeded"]:
        _safe_run(common + ["seed-bundled-orca"])
    _safe_run(common + ["activate", "--engine", "orcaslicer",
                        "--version", "2.5.0", "--sha256", ENGINE_SHA])
    _container_check(image_id)


def _replace_approval(raw, image_id):
    old = _settings(raw)["MAKERVAULT_SLICER_WORKER_IMAGE"]
    result = raw.replace("MAKERVAULT_SLICER_WORKER_IMAGE=" + old,
                         "MAKERVAULT_SLICER_WORKER_IMAGE=" + image_id)
    result = result.replace("MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST=" + old,
                            "MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST=" + image_id)
    if result == raw or _settings(result).get("MAKERVAULT_SLICER_WORKER_IMAGE") != image_id or (
            _settings(result).get("MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST") != image_id):
        raise ValueError("Could not safely replace pinned staging image identity.")
    return result


def _health():
    name = _safe_run(staging._compose_args() + ["ps", "-q", "slicer-worker"], capture=True)
    if not name:
        raise ValueError("Staging worker did not start.")
    for _ in range(15):
        state = _safe_run(["docker", "inspect", "--format",
                           "{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}",
                           name], capture=True)
        if state == "healthy":
            return
        if state in ("unhealthy", "missing"):
            raise ValueError("Staging worker health check failed: " + state)
        time.sleep(3)
    raise ValueError("Staging worker did not become healthy after migration.")


def _restart():
    args = staging._compose_args()
    _safe_run(args + ["config", "--quiet"])
    _safe_run(args + ["up", "-d", "--no-build", "--force-recreate",
                      "slicer-worker", "makervault"])
    _health()


def preflight():
    raw, config = _verified_old_configuration()
    if BACKUP.exists() or BACKUP.is_symlink():
        raise ValueError("Existing generic migration backup. Use rollback or inspect it.")
    if not staging.OVERLAY.is_file() or "makervault_slicer_engines:" not in staging.OVERLAY.read_text():
        raise ValueError("Update slicer staging branch; persistent engine volume is missing.")
    _safe_run(staging._compose_args() + ["config", "--quiet"])
    # Rollback must remain possible even if the registry becomes unavailable.
    _safe_run(["docker", "image", "inspect", config["MAKERVAULT_SLICER_WORKER_IMAGE"]], capture=True)
    print("PASS: reviewed source worker, current Compose and backup path verified.")
    print("Existing pinned image ID:", config["MAKERVAULT_SLICER_WORKER_IMAGE"])
    print("New generic registry image:", IMAGE)
    print("STOP active slicing jobs before executing migrate.")
    return raw


def migrate():
    raw = preflight()
    image_id = _candidate_image()
    _seed_engine(image_id)
    # A separate migration-specific backup; never touch earlier Orca backups.
    fd = os.open(BACKUP, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(raw)
    try:
        staging._save_env(_replace_approval(raw, image_id))
        _restart()
    except Exception:
        print("Migration failed; attempting automatic restoration.", file=sys.stderr)
        staging._save_env(raw)
        try:
            _restart()
        except Exception:
            print("Restore failed; use rollback manually. Backup retained.", file=sys.stderr)
        raise
    print("PASS: Generic one-container worker is healthy on staging.")
    print("Previous image and private configuration preserved in", BACKUP.name)
    print("Next: verify MakerVault engine installation and slice a Benchy in the UI.")


def rollback():
    if not BACKUP.is_file() or BACKUP.is_symlink() or BACKUP.stat().st_mode & 0o077:
        raise ValueError("Private original migration backup is missing or unsafe.")
    original = BACKUP.read_text(encoding="utf-8")
    if not HEX.fullmatch(_settings(original).get("MAKERVAULT_SLICER_WORKER_IMAGE", "")):
        raise ValueError("Saved worker identity is invalid.")
    staging._save_env(original)
    _restart()
    print("PASS: Restored pre-migration staging worker; persistent volume retained.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "migrate", "rollback"))
    args = parser.parse_args()
    try:
        {"preflight": preflight, "migrate": migrate,
         "rollback": rollback}[args.action]()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError,
            json.JSONDecodeError) as exc:
        print("Generic slicer migration refused: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
