"""Install/enable a pinned OrcaSlicer worker on MakerVault staging.

This is an explicitly invoked DEVELOPMENT installer, not an auto-installer and
not a production release. It never grants an engine permission to print.
A separate real native-profile test slice is still needed in MakerVault GUI.

  python3 scripts/install_slicer_staging.py prepare-orca
  python3 scripts/install_slicer_staging.py enable
  python3 scripts/install_slicer_staging.py status
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
TAG = "v2.4.2"
VERSION = "2.4.2"
ASSET = "OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.2.AppImage"
RELEASE_API = "https://api.github.com/repos/OrcaSlicer/OrcaSlicer/releases/tags/" + TAG
MAX_DOWNLOAD = 1024 * 1024 * 1024


def _github_asset():
    request = Request(RELEASE_API, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "MakerVault-Staging-Slicer-Installer",
    })
    with urlopen(request, timeout=25) as response:
        if response.status != 200 or len(str(response.headers)) > 16384:
            raise ValueError("Official GitHub release metadata is unavailable.")
        payload = response.read(2 * 1024 * 1024 + 1)
    if len(payload) > 2 * 1024 * 1024:
        raise ValueError("Release metadata exceeds the allowed size.")
    release = json.loads(payload)
    matches = [a for a in release.get("assets", []) if a.get("name") == ASSET]
    if len(matches) != 1:
        raise ValueError("The exact pinned OrcaSlicer Linux AppImage is missing from the upstream release.")
    item = matches[0]
    digest = item.get("digest", "")
    url = item.get("browser_download_url", "")
    allowed_url = "https://github.com/OrcaSlicer/OrcaSlicer/releases/download/" + TAG + "/" + ASSET
    if url != allowed_url:
        raise ValueError("Official release asset URL does not match the pinned path.")
    if not isinstance(digest, str) or not digest.startswith("sha256:") or len(digest) != 71:
        raise ValueError("Official release metadata has no SHA-256 digest; refusing unverified download.")
    if any(ch not in "0123456789abcdef" for ch in digest[7:]):
        raise ValueError("Official release digest is invalid.")
    return url, digest[7:]


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


def _resume_staged_bundle():
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
    if (entry.get("version") != VERSION or
            entry.get("binary") != "/opt/engines/orcaslicer.AppImage" or
            entry.get("binary_sha256") != digest.hexdigest()):
        raise ValueError("Staged engine identity or SHA-256 has changed; refusing reuse.")
    return {
        "app_approvals_json": json.dumps({
            "orcaslicer": {"version": VERSION, "binary_sha256": digest.hexdigest()}
        }, separators=(",", ":")),
        "worker_engines_json": json.dumps(entries, separators=(",", ":")),
    }


def prepare_orca():
    if not (ROOT / ".env").is_file() or not OVERLAY.is_file():
        raise ValueError("Run from a MakerVault staging checkout with a configured .env.")
    if DOTENV.exists():
        raise ValueError("Slicer already configured. Use enable, disable or status.")
    if BUNDLE.exists():
        print("Resuming a staged binary after verifying its original SHA-256…")
        prepared = _resume_staged_bundle()
    else:
        url, expected_sha = _github_asset()
        with tempfile.TemporaryDirectory(prefix="makervault-orca-") as tmp:
            appimage = Path(tmp) / ASSET
            print("Downloading pinned official OrcaSlicer " + VERSION + " (SHA-256 verified)…")
            _download_verified(url, expected_sha, appimage)
            from slicer_worker.stage_engines import stage_engines
            prepared = stage_engines(
                [("orcaslicer", VERSION, str(appimage), expected_sha)], BUNDLE
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
    parser.add_argument("action", choices=["prepare-orca", "enable", "disable", "status"])
    args = parser.parse_args(argv)
    try:
        {"prepare-orca": prepare_orca, "enable": enable,
         "disable": disable, "status": status}[args.action]()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print("Slicer staging installation failed: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
