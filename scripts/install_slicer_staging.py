"""Install/enable a pinned OrcaSlicer worker on MakerVault staging.

This is an explicitly invoked DEVELOPMENT installer, not an auto-installer and
not a production release. It never grants an engine permission to print.
A separate real native-profile test slice is still needed in MakerVault GUI.

  python3 scripts/install_slicer_staging.py prepare-orca
  python3 scripts/install_slicer_staging.py enable
  python3 scripts/install_slicer_staging.py status
  python3 scripts/install_slicer_staging.py update
  python3 scripts/install_slicer_staging.py refresh-worker
  python3 scripts/install_slicer_staging.py upgrade-orca --version 2.5.0
  python3 scripts/install_slicer_staging.py disable

Requires Docker access, internet access for the prepare step, and a valid
MakerVault .env with staging configuration. No extra pip packages.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
# Direct `python3 scripts/...` execution otherwise puts only scripts/ on sys.path.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DOTENV = ROOT / ".slicer-staging.env"
BUNDLE = ROOT / "slicer-engine-assets"
OVERLAY = ROOT / "compose.slicer.staging.yaml"
# Official upstream assets are pinned by version AND audited asset digest.
# Staging can select an approved release independently of MakerVault app code.
# New versions must first have an accepted digest and pass pinned-binary CI.
APPROVED_ORCA_RELEASES = {
    "2.4.2": "d12fb8c8eac1aecd2dfb6377acd48f994f8fa439ed5292fa532dd82880f029fd",
    "2.5.0": "d13eb0a9cd618ed080ab6b82c64c0a60c4501aac91e88d5ac2c3b526fb141a7c",
}
VERSION = "2.5.0"
TAG = "v" + VERSION
ASSET = f"OrcaSlicer_Linux_AppImage_Ubuntu2404_V{VERSION}.AppImage"
RELEASE_API = "https://api.github.com/repos/OrcaSlicer/OrcaSlicer/releases/tags/" + TAG


def _release_spec(version):
    if version not in APPROVED_ORCA_RELEASES:
        raise ValueError("Orca release must be reviewed and SHA-256 pinned before staging.")
    tag = "v" + version
    asset = f"OrcaSlicer_Linux_AppImage_Ubuntu2404_V{version}.AppImage"
    return (tag, asset,
            "https://api.github.com/repos/OrcaSlicer/OrcaSlicer/releases/tags/" + tag,
            APPROVED_ORCA_RELEASES[version])
MAX_DOWNLOAD = 1024 * 1024 * 1024


def _github_asset(version=VERSION):
    tag, asset, release_api, pinned_sha = _release_spec(version)
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "MakerVault-Staging-Slicer-Installer",
    }
    # CI's short-lived token avoids the unauthenticated GitHub API rate limit.
    # The request URL is the fixed official release endpoint, never user input.
    token = os.environ.get("GH_TOKEN", "")
    if token:
        headers["Authorization"] = "Bearer " + token
    request = Request(release_api, headers=headers)
    with urlopen(request, timeout=25) as response:
        if response.status != 200 or len(str(response.headers)) > 16384:
            raise ValueError("Official GitHub release metadata is unavailable.")
        payload = response.read(2 * 1024 * 1024 + 1)
    if len(payload) > 2 * 1024 * 1024:
        raise ValueError("Release metadata exceeds the allowed size.")
    release = json.loads(payload)
    matches = [a for a in release.get("assets", []) if a.get("name") == asset]
    if len(matches) != 1:
        raise ValueError("The exact pinned OrcaSlicer Linux AppImage is missing from the upstream release.")
    item = matches[0]
    digest = item.get("digest", "")
    url = item.get("browser_download_url", "")
    allowed_url = "https://github.com/OrcaSlicer/OrcaSlicer/releases/download/" + tag + "/" + asset
    if url != allowed_url:
        raise ValueError("Official release asset URL does not match the pinned path.")
    if not isinstance(digest, str) or not digest.startswith("sha256:") or len(digest) != 71:
        raise ValueError("Official release metadata has no SHA-256 digest; refusing unverified download.")
    if any(ch not in "0123456789abcdef" for ch in digest[7:]):
        raise ValueError("Official release digest is invalid.")
    if digest[7:] != pinned_sha:
        raise ValueError("Official release SHA-256 differs from the independently approved pinned digest.")
    return url, pinned_sha


def _download_verified(url, digest, dest):
    request = Request(url, headers={"User-Agent": "MakerVault-Staging-Slicer-Installer"})
    actual_hash = hashlib.sha256()
    downloaded = 0
    with urlopen(request, timeout=90) as response:
        final = urlsplit(response.geturl())
        if final.scheme != "https" or final.hostname not in {
            "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"
        }:
            raise ValueError("Untrusted redirect in official engine download.")
        with dest.open("xb") as output:
            while chunk := response.read(1024 * 1024):
                downloaded += len(chunk)
                if downloaded > MAX_DOWNLOAD:
                    raise ValueError("Official AppImage exceeds the download limit.")
                actual_hash.update(chunk)
                output.write(chunk)
    if not downloaded or actual_hash.hexdigest() != digest:
        raise ValueError("Downloaded OrcaSlicer SHA-256 does not match official release metadata.")
    dest.chmod(0o500)


def _run(args, env=None, capture=False):
    result = subprocess.run(args, cwd=ROOT, env=env, check=True,
                            text=True, capture_output=capture)
    return result.stdout.strip() if capture else ""


def _compose_args():
    files = ["compose.yaml", "compose.build.yaml"]
    if (ROOT / "compose.staging.yaml").exists():
        files.append("compose.staging.yaml")
    files.append("compose.slicer.staging.yaml")
    options = ["docker", "compose", "--env-file", ".env",
               "--env-file", DOTENV.name]
    for path in files:
        options.extend(["-f", path])
    return options


def _read_env():
    if not DOTENV.is_file() or DOTENV.is_symlink():
        raise ValueError("No prepared slicer environment exists. Run prepare-orca first.")
    if DOTENV.stat().st_mode & 0o077:
        raise ValueError("Slicer environment permissions are insecure; expected mode 0600.")
    return DOTENV.read_text(encoding="utf-8")


def _save_env(text):
    # Never leave a partial .env or print the worker's access token.
    temp = DOTENV.with_suffix(".env.pending")
    if temp.exists():
        raise ValueError("A previous temporary slicer configuration exists.")
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(text)
        os.replace(temp, DOTENV)
    finally:
        if temp.exists():
            temp.unlink()


def _resume_staged_bundle(expected_version=None):
    """Resume only an intact, digest-verified staging bundle after a failed build."""
    path = BUNDLE / "manifest.json"
    binary = BUNDLE / "orcaslicer.AppImage"
    if (BUNDLE.is_symlink() or path.is_symlink() or binary.is_symlink()
            or not path.is_file() or not binary.is_file()):
        raise ValueError("Existing engine assets are incomplete; inspect staging before retrying.")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    entries = manifest.get("engines", {})
    if not isinstance(entries, dict) or set(entries) != {"orcaslicer"}:
        raise ValueError("The staged bundle is not an isolated OrcaSlicer installation.")
    entry = entries["orcaslicer"]
    digest = hashlib.sha256()
    if not 0 < binary.stat().st_size <= MAX_DOWNLOAD:
        raise ValueError("Staged OrcaSlicer AppImage size is invalid.")
    with binary.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    if (entry.get("version") not in APPROVED_ORCA_RELEASES or
            (expected_version is not None and entry.get("version") != expected_version) or
            entry.get("binary") != "/opt/engines/orcaslicer.AppImage" or
            entry.get("binary_sha256") != digest.hexdigest()):
        raise ValueError("Staged engine identity or SHA-256 has changed; refusing reuse.")
    return {
        "app_approvals_json": json.dumps({
            "orcaslicer": {"version": entry["version"], "binary_sha256": digest.hexdigest()}
        }, separators=(",", ":")),
        "worker_engines_json": json.dumps(entries, separators=(",", ":")),
    }


def prepare_orca(version=VERSION):
    tag, asset, _api, _sha = _release_spec(version)
    if not (ROOT / ".env").is_file() or not OVERLAY.is_file():
        raise ValueError("Run from a MakerVault staging checkout with a configured .env.")
    if DOTENV.exists():
        raise ValueError("Slicer already configured. Use enable, disable or status.")
    if BUNDLE.exists():
        print("Resuming a staged binary after verifying its original SHA-256…")
        prepared = _resume_staged_bundle(expected_version=version)
    else:
        url, expected_sha = _github_asset(version)
        with tempfile.TemporaryDirectory(prefix="makervault-orca-") as tmp:
            appimage = Path(tmp) / asset
            print("Downloading pinned official OrcaSlicer " + version + " (SHA-256 verified)…")
            _download_verified(url, expected_sha, appimage)
            from slicer_worker.stage_engines import stage_engines
            prepared = stage_engines(
                [("orcaslicer", version, str(appimage), expected_sha)], BUNDLE
            )
    print("Building isolated candidate slicer image (without running the engine)…")
    _run(["docker", "build", "-f", "slicer_worker/Dockerfile.bundle",
          "-t", "makervault-slicer-worker:staging", "."])
    image = _run(["docker", "image", "inspect", "--format", "{{.Id}}",
                  "makervault-slicer-worker:staging"], capture=True)
    if not image.startswith("sha256:") or len(image) != 71 or any(c not in "0123456789abcdef" for c in image[7:]):
        raise ValueError("Built Docker image has no valid immutable image ID.")
    token = secrets.token_urlsafe(48)
    env = "\n".join([
        "# Generated by scripts/install_slicer_staging.py; staging only, keep private.",
        "MAKERVAULT_SLICER_EXECUTION_ENABLED=0",
        "MAKERVAULT_SLICER_WORKER_TOKEN=" + token,
        "MAKERVAULT_SLICER_WORKER_IMAGE=" + image,
        "MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST=" + image,
        "MAKERVAULT_SLICER_ENGINES_JSON='" + prepared["app_approvals_json"] + "'",
        "SLICER_ENGINES_JSON='" + prepared["worker_engines_json"] + "'",
        "",
    ])
    _save_env(env)
    print("Candidate OrcaSlicer image staged with pinned image ID and binary digest.")
    print("Run: python3 scripts/install_slicer_staging.py enable")
    print("Engine health alone does not validate real slicing; select native profiles and run a test slice.")


def refresh_worker():
    """Rebuild only the wrapper over the same checksum-verified engine bundle.

    Preserve the authentication token and exact official binary hashes.
    Never start an image until the new immutable image ID is recorded.
    """
    envtext = _read_env()
    _resume_staged_bundle()
    def installed(key):
        for line in envtext.splitlines():
            if line.startswith(key + "="):
                return line.partition("=")[2]
        raise ValueError("Missing prepared slicer setting: " + key)

    old_image = installed("MAKERVAULT_SLICER_WORKER_IMAGE")
    old_digest = installed("MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST")
    if old_image != old_digest or not old_image.startswith("sha256:"):
        raise ValueError("Existing worker image identity does not match its digest.")
    print("Rebuilding isolated worker with existing pinned OrcaSlicer binary…")
    _run(["docker", "build", "-f", "slicer_worker/Dockerfile.bundle",
          "-t", "makervault-slicer-worker:staging", "."])
    new_image = _run(["docker", "image", "inspect", "--format", "{{.Id}}",
                      "makervault-slicer-worker:staging"], capture=True)
    if (not new_image.startswith("sha256:") or len(new_image) != 71
            or any(ch not in "0123456789abcdef" for ch in new_image[7:])):
        raise ValueError("Rebuilt worker has no valid immutable image ID.")
    if new_image != old_image:
        updated = envtext.replace(
            "MAKERVAULT_SLICER_WORKER_IMAGE=" + old_image,
            "MAKERVAULT_SLICER_WORKER_IMAGE=" + new_image
        ).replace(
            "MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST=" + old_digest,
            "MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST=" + new_image
        )
        _save_env(updated)
    _run(_compose_args() + ["config", "--quiet"])
    _run(_compose_args() + ["up", "-d", "--build", "--force-recreate"])
    _run(_compose_args() + ["ps", "makervault", "slicer-worker"])
    print("Refreshed staging worker; engine binary hash and token preserved.")


def upgrade_orca(version=VERSION):
    """Replace the staging engine safely, preserving credentials and rollback assets.

    Requires a stopped/idle slicer queue. Refuses to overwrite a previous
    rollback snapshot. Both identity-locked configurations are recoverable.
    """
    _release_spec(version)
    current_env = _read_env()
    current = _resume_staged_bundle()
    installed = json.loads(current["worker_engines_json"]).get("orcaslicer")
    if not installed:
        raise ValueError("Installed staging worker has no OrcaSlicer engine.")
    if installed["version"] == version:
        print("OrcaSlicer " + version + " is already staged; no upgrade required.")
        return
    env_backup = ROOT / ".slicer-staging.env.pre-upgrade"
    bundle_backup = ROOT / "slicer-engine-assets.pre-upgrade"
    if env_backup.exists() or bundle_backup.exists():
        raise ValueError("Previous upgrade backup exists. Preserve or inspect it before upgrading.")
    # Do not replace a live binary while a slicer operation is in progress.
    print("Ensure no slicing jobs are queued or running before proceeding.")
    url, expected_sha = _github_asset(version)
    with tempfile.TemporaryDirectory(prefix=".orca-upgrade-", dir=ROOT) as directory:
        directory = Path(directory)
        appimage = directory / _release_spec(version)[1]
        print("Downloading and verifying pinned OrcaSlicer " + version + "…")
        _download_verified(url, expected_sha, appimage)
        from slicer_worker.stage_engines import stage_engines
        candidate = directory / "bundle"
        staged = stage_engines(
            [("orcaslicer", version, str(appimage), expected_sha)], candidate)
        # Back up the original secret env without displaying its token.
        with env_backup.open("xb") as saved:
            os.chmod(env_backup, 0o600)
            saved.write(current_env.encode("utf-8"))
        moved_old = False
        try:
            BUNDLE.rename(bundle_backup)
            moved_old = True
            candidate.rename(BUNDLE)
            _resume_staged_bundle(expected_version=version)
            print("Building checksum-pinned replacement worker…")
            _run(["docker", "build", "-f", "slicer_worker/Dockerfile.bundle",
                  "-t", "makervault-slicer-worker:staging", "."])
            new_image = _run(["docker", "image", "inspect", "--format", "{{.Id}}",
                             "makervault-slicer-worker:staging"], capture=True)
            if (not new_image.startswith("sha256:") or len(new_image) != 71 or
                    any(ch not in "0123456789abcdef" for ch in new_image[7:])):
                raise ValueError("New engine image has no immutable identity.")
            previous_image = next((line.partition("=")[2] for line in
                current_env.splitlines() if line.startswith(
                    "MAKERVAULT_SLICER_WORKER_IMAGE=")), None)
            previous_digest = next((line.partition("=")[2] for line in
                current_env.splitlines() if line.startswith(
                    "MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST=")), None)
            if not previous_image or previous_image != previous_digest:
                raise ValueError("Previously approved image identity is inconsistent.")
            updates = {
                "MAKERVAULT_SLICER_WORKER_IMAGE": new_image,
                "MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST": new_image,
                "MAKERVAULT_SLICER_ENGINES_JSON": "'" + staged["app_approvals_json"] + "'",
                "SLICER_ENGINES_JSON": "'" + staged["worker_engines_json"] + "'",
            }
            updated_lines, seen = [], set()
            for line in current_env.splitlines():
                key, sep, _value = line.partition("=")
                if sep and key in updates:
                    updated_lines.append(key + "=" + updates[key])
                    seen.add(key)
                else:
                    updated_lines.append(line)
            if seen != set(updates):
                raise ValueError("Existing slicer environment is missing a required approval.")
            _save_env("\n".join(updated_lines) + "\n")
            _run(_compose_args() + ["config", "--quiet"])
            _run(_compose_args() + ["up", "-d", "--build", "--force-recreate",
                                    "makervault", "slicer-worker"])
            _run(_compose_args() + ["ps", "makervault", "slicer-worker"])
        except Exception:
            # Restore credentials, image approval and old binary together.
            # Retain backups if rollback itself fails so recovery is possible.
            print("Upgrade failed: restoring original staging engine configuration…",
                  file=sys.stderr)
            if moved_old:
                if BUNDLE.exists():
                    if BUNDLE.is_symlink() or not BUNDLE.is_dir():
                        raise ValueError("Unexpected engine bundle; manual rollback required.")
                    shutil.rmtree(BUNDLE)
                bundle_backup.rename(BUNDLE)
            _save_env(current_env)
            try:
                _run(_compose_args() + ["up", "-d", "--no-build", "--force-recreate",
                                        "makervault", "slicer-worker"])
            except Exception:
                print("Automatic container rollback failed; inspect staging backups.",
                      file=sys.stderr)
            raise
    print("Upgraded OrcaSlicer to " + version + ". Old env and binary preserved as *.pre-upgrade.")
    print("Reverify the engine and native profiles in MakerVault before slicing.")


def update():
    """Update the application with the already-installed slicer worker attached.

    Unlike refresh-worker, this only rebuilds the main app; the worker's
    immutable image ID, approved engine binary digests and token stay intact.
    Using the standard three-file Compose command after slicer installation
    would omit the optional worker link, so use this action for staging.
    """
    _read_env()  # Enforce an existing private installer configuration.
    if not OVERLAY.is_file():
        raise ValueError("Slicer staging Compose overlay is missing.")
    args = _compose_args()
    print("Checking the full MakerVault + slicer staging Compose configuration…")
    _run(args + ["config", "--quiet"])
    print("Rebuilding MakerVault while retaining the pinned slicer worker…")
    _run(args + ["up", "-d", "--build", "makervault"])
    _run(args + ["ps", "makervault", "slicer-worker"])
    print("MakerVault updated. The isolated slicer image and approved engine hashes were not changed.")


def enable():
    envtext = _read_env()
    if not BUNDLE.is_dir():
        raise ValueError("The staged engine binaries are missing.")
    if "MAKERVAULT_SLICER_EXECUTION_ENABLED=0" in envtext:
        envtext = envtext.replace(
            "MAKERVAULT_SLICER_EXECUTION_ENABLED=0",
            "MAKERVAULT_SLICER_EXECUTION_ENABLED=1",
        )
        _save_env(envtext)
    print("Checking staging configuration and starting the isolated worker…")
    _run(_compose_args() + ["config", "--quiet"])
    _run(_compose_args() + ["up", "-d", "--build"])
    _run(_compose_args() + ["ps", "makervault", "slicer-worker"])
    print("Verified worker identity gate enabled; slicing requires compatible native")
    print("printer, filament and process profiles with intact parent dependencies.")


def disable():
    text = _read_env().replace(
        "MAKERVAULT_SLICER_EXECUTION_ENABLED=1",
        "MAKERVAULT_SLICER_EXECUTION_ENABLED=0",
    )
    _save_env(text)
    _run(_compose_args() + ["up", "-d", "--no-deps", "makervault"])
    _run(_compose_args() + ["stop", "slicer-worker"])
    print("Staging slicer engine execution disabled. No staged binaries were removed.")


def status():
    text = _read_env()
    enabled = "MAKERVAULT_SLICER_EXECUTION_ENABLED=1" in text
    print("Slicing execution: " + ("enabled, subject to native profile integrity checks" if enabled else "disabled"))
    _run(_compose_args() + ["ps", "makervault", "slicer-worker"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare-orca", "enable", "disable", "status", "refresh-worker", "upgrade-orca", "update"])
    parser.add_argument("--version", default=VERSION,
                        help="Approved Orca release for prepare-orca and upgrade-orca (default: 2.5.0)")
    args = parser.parse_args(argv)
    try:
        if args.action == "prepare-orca":
            prepare_orca(version=args.version)
            return 0
        if args.action == "upgrade-orca":
            upgrade_orca(version=args.version)
            return 0
        if args.version != VERSION:
            raise ValueError("--version applies only to prepare-orca or upgrade-orca.")
        {"enable": enable,
         "disable": disable, "status": status,
         "refresh-worker": refresh_worker, "update": update}[args.action]()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print("Slicer staging installation failed: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
