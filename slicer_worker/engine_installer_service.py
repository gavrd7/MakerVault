"""Restricted, opt-in multi-engine installation service.

Not part of Django or the slice worker. Runs in an isolated container with a
single writable engine-store volume, no Docker socket, no app database/media,
and bounded CPU/RAM/PIDs. Only predeclared official GitHub repositories are
queried, and the GitHub release API SHA-256 digest is mandatory.

No arbitrary paths, URLs, archives, commands or arguments come from clients.
"""
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
from threading import Lock, Thread
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .engine_store_admin import (
    _manifest, _write, _sha256, seed_bundled_orca, activate,
    EXPECTED_ORCA_SHA, APPROVAL_VERSION, rollback as rollback_store,
)
from .engine_store_lifecycle import installed_versions, activate_installed, uninstall_engine, preserve_active_identities, IDENTITY
from .engine_registry import SUPPORTED as INSTALLED_ENGINE_TYPES, BAMBU_VERSION, BAMBU_RUNTIME_SHA256
from .engine_store_permissions import make_runtime_worker_readable
from .prusa_runtime_install import (
    VERSION as PRUSA_VERSION, RELEASE_TAG as PRUSA_RELEASE_TAG,
    ASSET_NAME as PRUSA_ASSET, ARCHIVE_SHA256 as PRUSA_ARCHIVE_SHA256,
    ASSET_SIZE as PRUSA_ASSET_SIZE, BINARY_SHA256 as PRUSA_BINARY_SHA256,
    sha256 as prusa_sha256, unpack_reviewed_prusa,
)

STORE = Path(os.environ.get("SLICER_ENGINE_STORE", "/opt/engine-store"))
TOKEN = os.environ.get("SLICER_INSTALLER_TOKEN", "")
SUPPORTED = {"crealityprint": "CrealityOfficial/CrealityPrint",
             "orcaslicer": "OrcaSlicer/OrcaSlicer"}
SUPPORTED["bambustudio"] = "bambulab/BambuStudio"
# Prusa is separately packaged by MakerVault from the exact tagged upstream
# source. Only an immutable, SHA-pinned MakerVault release asset is admitted.
SUPPORTED["prusaslicer"] = "gavrd7/MakerVault"
BAMBU_APPIMAGE_SHA256 = "668dabb1be53c758189ed6bc89935285dea5e0af46216546b1bafd6882e9aff0"
BAMBU_ASSET = "BambuStudio_ubu24-v02.09.01.70-20261103183404.AppImage"

# Orca 2.5.0 is NOT compatible with the native Creality K2 profile as
# published upstream: the profile asks for 30 mm cut retraction while the
# official executable caps it at 18 mm. Never substitute the stock AppImage
# for the independently reviewed, source-patched MakerVault build.
# 2.4.2 is an upstream-only version, with NO K2 compatibility approval.
APPROVED_ORCA = {
    "2.4.2": "d12fb8c8eac1aecd2dfb6377acd48f994f8fa439ed5292fa532dd82880f029fd",
}
REVIEWED_ORCA_VERSION = "2.5.0"
REVIEWED_ORCA_SHA256 = EXPECTED_ORCA_SHA
# Dockerfile.generic is based on the exact approved, immutable reviewed
# Orca bootstrap image. The installer runs from that image too: reinstallation
# copies its own bundled AppImage after checking the audited checksum.
# Do not depend on expiring Actions artifacts or an unneeded Github release.
REVIEWED_ORCA_SOURCE = Path("/opt/engines/orcaslicer.AppImage")
REVIEWED_ORCA_APPDIR = Path("/opt/engines/squashfs-root")


def _reviewed_orca_release():
    """Offer reviewed 2.5.0 only when the embedded source passes SHA-256."""
    if (REVIEWED_ORCA_SOURCE.is_symlink() or not REVIEWED_ORCA_SOURCE.is_file()
            or REVIEWED_ORCA_APPDIR.is_symlink()
            or not (REVIEWED_ORCA_APPDIR / "AppRun").is_file()):
        return None
    try:
        if _sha256(REVIEWED_ORCA_SOURCE) != REVIEWED_ORCA_SHA256:
            return None
    except OSError:
        return None
    return {
        "engine": "orcaslicer", "version": REVIEWED_ORCA_VERSION,
        "bundle_sha256": REVIEWED_ORCA_SHA256,
        "bundle_url": None, "binary_sha256": REVIEWED_ORCA_SHA256,
        "architecture": "linux/amd64",
        "notes": "MakerVault-reviewed OrcaSlicer 2.5.0 (K2 30 mm compatible)",
        "asset_size": REVIEWED_ORCA_SOURCE.stat().st_size,
        "source": "bundled-reviewed-image",
    }

MAX_BYTES = 650 * 1024 * 1024
VERSION = re.compile(r"^v?(\d+\.\d+\.\d+)$")
HEX = re.compile(r"^[a-f0-9]{64}$")
OPERATIONS = {}
LOCK = Lock()
MAX_OPERATIONS = 50
RELEASE_CACHE = {"time": 0.0, "items": []}
RELEASE_CACHE_SECONDS = 600
OPERATION_FILE = STORE / "installer-operations.json"
LOGGER = logging.getLogger("makervault.slicer.installer")


def _persist_operations():
    """Atomic restart-safe status journal, accessible to installer only."""
    temp = OPERATION_FILE.parent / (".operations-" + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("x", encoding="utf-8") as handle:
            json.dump(list(OPERATIONS.values())[-MAX_OPERATIONS:], handle,
                      separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, OPERATION_FILE)
    finally:
        if temp.exists():
            temp.unlink()


def _restore_operations():
    if OPERATION_FILE.is_symlink() or not OPERATION_FILE.exists():
        return
    if OPERATION_FILE.stat().st_size > 128000:
        raise ValueError("Installer operation journal is oversized.")
    records = json.loads(OPERATION_FILE.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("Invalid installer operation journal.")
    with LOCK:
        for row in records[-MAX_OPERATIONS:]:
            try:
                operation_id = str(uuid.UUID(row["id"]))
            except (KeyError, ValueError, TypeError):
                continue
            if row.get("engine") not in SUPPORTED or not isinstance(row.get("version"), str):
                continue
            restored = {key: row.get(key) for key in (
                "id", "engine", "version", "action", "status",
                "progress", "message", "binary_sha256",
            ) if key in row}
            if restored.get("status") not in {"completed", "failed"}:
                restored.update(status="failed", progress=0,
                                message="Installer restarted before completion; retry installation.")
            OPERATIONS[operation_id] = restored
        _persist_operations()
ALLOWED_DOWNLOAD_HOSTS = {"github.com", "release-assets.githubusercontent.com",
                          "objects.githubusercontent.com"}


def _request(url, *, timeout=12):
    req = urllib.request.Request(url, headers={
        "User-Agent": "MakerVault-Slicer-Installer/1",
        "Accept": "application/vnd.github+json",
    })
    return urllib.request.urlopen(req, timeout=timeout)


def release_catalogue():
    """Return only official, digest-bearing Linux x86_64 AppImages."""
    if platform.machine() not in {"x86_64", "AMD64"}:
        return []
    with LOCK:
        if RELEASE_CACHE["items"] and time.monotonic() - RELEASE_CACHE["time"] < RELEASE_CACHE_SECONDS:
            return list(RELEASE_CACHE["items"])
    releases = []
    for engine, repo in SUPPORTED.items():
        if engine == "prusaslicer":
            # The temporary Actions artifact is deliberately NOT an install
            # source. A separately approved permanent GitHub release must
            # exist, contain exactly the reviewed tar SHA, and have the
            # expected asset name/size/URL before the UI offers Prusa.
            url = f"https://api.github.com/repos/{repo}/releases/tags/{PRUSA_RELEASE_TAG}"
            try:
                with _request(url) as response:
                    raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    continue
                doc = json.loads(raw)
            except (OSError, ValueError, urllib.error.URLError):
                continue
            if (not isinstance(doc, dict) or doc.get("draft") or doc.get("prerelease")
                    or doc.get("tag_name") != PRUSA_RELEASE_TAG):
                continue
            expected_url = (f"https://github.com/{repo}/releases/download/"
                            f"{PRUSA_RELEASE_TAG}/{PRUSA_ASSET}")
            assets = [a for a in doc.get("assets", [])
                      if isinstance(a, dict) and a.get("name") == PRUSA_ASSET]
            if len(assets) != 1:
                continue
            asset = assets[0]
            if (asset.get("digest") != "sha256:" + PRUSA_ARCHIVE_SHA256
                    or asset.get("browser_download_url") != expected_url
                    or type(asset.get("size")) is not int
                    or asset["size"] != PRUSA_ASSET_SIZE):
                continue
            releases.append({
                "engine": "prusaslicer", "version": PRUSA_VERSION,
                "bundle_sha256": PRUSA_ARCHIVE_SHA256,
                "bundle_url": expected_url,
                "binary_sha256": PRUSA_BINARY_SHA256,
                "architecture": "linux/amd64",
                "notes": "MakerVault-verified source-pinned PrusaSlicer 2.9.7",
                "asset_size": PRUSA_ASSET_SIZE,
            })
            continue
        if engine == "bambustudio":
            tag = "v" + BAMBU_VERSION
            url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
            try:
                with _request(url) as response:
                    raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    continue
                release = json.loads(raw)
            except (OSError, ValueError, urllib.error.URLError):
                continue
            if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
                continue
            expected_url = (
                f"https://github.com/{repo}/releases/download/{tag}/{BAMBU_ASSET}")
            matches = [item for item in release.get("assets", [])
                       if isinstance(item, dict) and item.get("name") == BAMBU_ASSET]
            if len(matches) != 1:
                continue
            item = matches[0]
            if (item.get("digest") != "sha256:" + BAMBU_APPIMAGE_SHA256
                    or item.get("browser_download_url") != expected_url
                    or type(item.get("size")) is not int
                    or not 10_000_000 <= item["size"] <= MAX_BYTES):
                continue
            releases.append({
                "engine": engine, "version": BAMBU_VERSION,
                "bundle_sha256": BAMBU_APPIMAGE_SHA256,
                "bundle_url": expected_url,
                "binary_sha256": BAMBU_RUNTIME_SHA256,
                "architecture": "linux/amd64",
                "notes": "Bambu Studio 2.9.1",
                "asset_size": item["size"],
            })
            continue
        if engine == "orcaslicer":
            reviewed = _reviewed_orca_release()
            if reviewed is not None:
                releases.append(reviewed)
            for version, approved_digest in APPROVED_ORCA.items():
                tag = "v" + version
                asset_name = f"OrcaSlicer_Linux_AppImage_Ubuntu2404_V{version}.AppImage"
                url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
                try:
                    with _request(url) as response:
                        release = json.load(response)
                except (OSError, ValueError, urllib.error.URLError):
                    continue
                if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
                    continue
                expected_url = f"https://github.com/{repo}/releases/download/{tag}/{asset_name}"
                matches = [item for item in release.get("assets", []) if isinstance(item, dict)
                           and item.get("name") == asset_name]
                if len(matches) != 1:
                    continue
                item = matches[0]
                if (item.get("digest") != "sha256:" + approved_digest
                        or item.get("browser_download_url") != expected_url
                        or type(item.get("size")) is not int
                        or not 10_000_000 <= item["size"] <= MAX_BYTES):
                    continue
                releases.append({
                    "engine": engine, "version": version,
                    "bundle_sha256": approved_digest, "bundle_url": expected_url,
                    "binary_sha256": approved_digest, "architecture": "linux/amd64",
                    "notes": "OrcaSlicer " + version, "asset_size": item["size"],
                })
            continue
        url = "https://api.github.com/repos/" + repo + "/releases?per_page=10"
        with _request(url) as response:
            data = json.load(response)
        if not isinstance(data, list):
            raise ValueError("Invalid upstream release catalogue.")
        for release in data:
            if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
                continue
            tag = release.get("tag_name", "")
            version_match = VERSION.fullmatch(tag)
            if not version_match:
                continue
            for asset in release.get("assets", []):
                name = asset.get("name", "")
                digest = asset.get("digest", "")
                download = asset.get("browser_download_url", "")
                if (not name.startswith("CrealityPrint-") or not name.endswith("-x86_64-Release.AppImage")
                        or not isinstance(digest, str) or not digest.startswith("sha256:")
                        or not HEX.fullmatch(digest[7:])
                        or not isinstance(asset.get("size"), int)
                        or not 10_000_000 <= asset["size"] <= MAX_BYTES
                        or not isinstance(download, str)
                        or not download.startswith("https://github.com/" + repo + "/releases/download/")):
                    continue
                releases.append({
                    "engine": engine, "version": version_match.group(1),
                    "bundle_sha256": digest[7:], "bundle_url": download,
                    "binary_sha256": digest[7:], "architecture": "linux/amd64",
                    "notes": str(release.get("name", ""))[:160],
                    "asset_size": asset["size"],
                })
                break
    with LOCK:
        RELEASE_CACHE["items"] = list(releases)
        RELEASE_CACHE["time"] = time.monotonic()
    return releases


def _download(release, destination, progress):
    """Stream exact official asset; check every redirect and its signed digest."""
    class SafeRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            parsed = urllib.parse.urlsplit(newurl)
            if parsed.scheme != "https" or parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS:
                raise ValueError("Download redirected outside approved hosts.")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    opener = urllib.request.build_opener(SafeRedirect)
    req = urllib.request.Request(release["bundle_url"], headers={
        "User-Agent": "MakerVault-Slicer-Installer/1"
    })
    sha = hashlib.sha256()
    total = 0
    with opener.open(req, timeout=35) as response, destination.open("xb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_BYTES or total > release["asset_size"]:
                raise ValueError("Release exceeded its published size.")
            sha.update(chunk)
            output.write(chunk)
            progress(min(65, int(total * 65 / release["asset_size"])))
    if total != release["asset_size"] or sha.hexdigest() != release["bundle_sha256"]:
        raise ValueError("Official release download failed SHA-256 verification.")


def _write_operation(op_id, **changes):
    with LOCK:
        if op_id not in OPERATIONS:
            return
        OPERATIONS[op_id].update(changes)
        _persist_operations()


def _install(op_id, release):
    engine, version = release["engine"], release["version"]
    if engine == "prusaslicer":
        # Separate, tar-verified native CLI path. Existing AppImage engines
        # never enter this branch and retain their exact original code.
        return _install_reviewed_prusa(op_id, release)
    base = STORE / "versions" / engine
    target = base / version
    stage = None
    try:
        bundled_orca = (engine == "orcaslicer" and version == REVIEWED_ORCA_VERSION)
        _write_operation(op_id, status="verifying" if bundled_orca else "downloading",
                         progress=2, message=("Checking bundled MakerVault-reviewed Orca"
                                              if bundled_orca else "Downloading official release"))
        base.mkdir(parents=True, exist_ok=True)
        if STORE.is_symlink() or base.is_symlink() or target.is_symlink():
            raise ValueError("Unsafe engine store path.")
        if target.exists():
            raise ValueError("This engine version is already installed.")
        stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=base))
        image = stage / (engine + ".AppImage")
        if bundled_orca:
            # Source is inside the immutable GHCR bootstrap image (not a user
            # path or an upstream official AppImage). Check the actual bytes
            # before copying, then verify the copy again before extraction.
            if (release.get("source") != "bundled-reviewed-image"
                    or release.get("bundle_sha256") != REVIEWED_ORCA_SHA256
                    or release.get("bundle_url") is not None
                    or REVIEWED_ORCA_SOURCE.is_symlink()
                    or _sha256(REVIEWED_ORCA_SOURCE) != REVIEWED_ORCA_SHA256):
                raise ValueError("MakerVault-reviewed Orca 2.5.0 source is unavailable or modified.")
            shutil.copyfile(REVIEWED_ORCA_SOURCE, image)
            if _sha256(image) != REVIEWED_ORCA_SHA256:
                raise ValueError("Copied Orca 2.5.0 does not match the reviewed build.")
        else:
            _download(release, image, lambda n: _write_operation(op_id, progress=n))
        _write_operation(op_id, status="verifying", progress=70,
                         message="Checking downloaded binary")
        with image.open("rb") as source:
            magic = source.read(4)
        if magic != b"\x7fELF":
            raise ValueError("Official release is not an ELF AppImage.")
        image.chmod(0o555)
        # The AppImage runtime extracts its payload without requiring FUSE.
        # This is restricted to the installer sandbox and a bounded scratch.
        try:
            if bundled_orca:
                # The same immutable image already contains the extracted
                # approved runtime. Copy it, avoiding a second extraction
                # and refusing symlinks escaping the source bundle.
                if REVIEWED_ORCA_APPDIR.is_symlink() or not REVIEWED_ORCA_APPDIR.is_dir():
                    raise ValueError("Bundled reviewed Orca runtime is unavailable.")
                shutil.copytree(REVIEWED_ORCA_APPDIR, stage / "squashfs-root", symlinks=True)
                extracted = subprocess.CompletedProcess([], 0)
            else:
                extracted = subprocess.run([str(image), "--appimage-extract"],
                    cwd=stage, env={"HOME": str(stage), "TMPDIR": str(stage),
                                    "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE, timeout=180, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("AppImage extraction timed out after 180 seconds.") from exc
        except OSError as exc:
            raise ValueError(
                f"AppImage extraction could not start ({type(exc).__name__}, errno {exc.errno})."
            ) from exc
        app_run = stage / "squashfs-root" / "AppRun"
        if extracted.returncode != 0 or not app_run.exists():
            raise ValueError(
                f"AppImage extraction failed (exit {extracted.returncode}, "
                f"AppRun present: {app_run.exists()})."
            )
        runtime = app_run.resolve(strict=True)
        if not runtime.is_relative_to((stage / "squashfs-root").resolve(strict=True)):
            raise ValueError("Engine runtime escapes its extracted directory.")
        if not runtime.is_file() or not os.access(runtime, os.X_OK):
            raise ValueError("Engine runtime is not executable.")
        runtime_relative = runtime.relative_to(stage)
        _write_operation(op_id, status="staged", progress=85,
                         message="Testing Linux CLI compatibility")
        # Never mark a release available solely because it downloaded.
        # Known Creality builds can hang by opening the GUI instead of slicing.
        try:
            probe_args = ([str(app_run), "--cli", "--help"] if engine == "crealityprint"
                          else [str(app_run), "--help"])
            probe = subprocess.run(probe_args, cwd=stage,
                env={"HOME": str(stage), "TMPDIR": str(stage),
                     "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
                     "DISPLAY": "", "QT_QPA_PLATFORM": "offscreen",
                     "SSL_CERT_FILE": "/etc/ssl/certs/ca-certificates.crt"},
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=45 if engine == "bambustudio" else 18, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Engine CLI headless check timed out.") from exc
        except OSError as exc:
            raise ValueError(
                f"Engine CLI could not start ({type(exc).__name__}, errno {exc.errno})."
            ) from exc
        if probe.returncode != 0:
            raise ValueError(f"Engine CLI check exited with status {probe.returncode}.")
        # Stage a complete version before publishing it; preserve all older
        # engines and use a single atomic manifest rename for activation.
        binary_hash = _sha256(runtime)
        if engine == "bambustudio" and binary_hash != BAMBU_RUNTIME_SHA256:
            raise ValueError("Bambu native runtime differs from the reviewed exact release.")
        if not HEX.fullmatch(binary_hash):
            raise ValueError("Engine runtime digest unavailable.")
        (stage / IDENTITY).write_text(json.dumps({
            "engine": engine, "version": version,
            "binary": str(target / "squashfs-root" / "AppRun"),
            "binary_sha256": binary_hash,
        }, separators=(",", ":")), encoding="utf-8")
        # mkdtemp creates a 0700 staging root. The installer (UID 10002)
        # can inspect it, but the worker (UID 10001) cannot traverse a
        # published version directory unless the root is made searchable.
        # Only expose traversal/read; retain installer-only write access.
        make_runtime_worker_readable(
            stage / "squashfs-root",
            required_executables=("bin/bambu-studio",)
            if engine == "bambustudio" else (),
        )
        stage.chmod(0o755)
        os.rename(stage, target)
        stage = None
        _write_operation(op_id, status="activating", progress=94,
                         message="Activating installed version")
        current = _manifest(STORE)
        existing = current["engines"]
        new_record = {
            "binary": str(target / "squashfs-root" / "AppRun"),
            "version": version, "binary_sha256": binary_hash,
        }
        # Keep other engines, including the existing Orca runtime, untouched.
        new_manifest = {"schema_version": 1,
                        "engines": {**existing, engine: new_record}}
        if existing:
            preserve_active_identities(STORE)
            _write(STORE, current)  # Ensure manifest formatting is consistent.
            previous = STORE / "previous.json"
            previous.write_text(json.dumps(current, separators=(",", ":")), encoding="utf-8")
        _write(STORE, new_manifest)
        _write_operation(op_id, status="completed", progress=100,
                         message="Installed and activated", binary_sha256=binary_hash)
    except Exception as exc:
        # No raw paths, URLs, command output or credentials in the UI.
        reason = str(exc) if isinstance(exc, ValueError) else (
            f"Installer failed during {OPERATIONS.get(op_id, {}).get('status', 'unknown')} "
            f"({type(exc).__name__})."
        )
        LOGGER.error("Engine installation %s %s failed: %s", engine, version, reason[:180])
        _write_operation(op_id, status="failed", message=reason[:180], progress=0)
    finally:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)


def _install_reviewed_prusa(op_id, release):
    """Install the exact reviewed Prusa source artifact, preserving other engines."""
    engine, version = "prusaslicer", PRUSA_VERSION
    base = STORE / "versions" / engine
    target = base / version
    stage = None
    archive_path = None
    try:
        if (release.get("version") != version
                or release.get("bundle_sha256") != PRUSA_ARCHIVE_SHA256
                or release.get("binary_sha256") != PRUSA_BINARY_SHA256
                or release.get("asset_size") != PRUSA_ASSET_SIZE
                or release.get("bundle_url") != (
                    "https://github.com/gavrd7/MakerVault/releases/download/"
                    + PRUSA_RELEASE_TAG + "/" + PRUSA_ASSET)):
            raise ValueError("Prusa release identity is not approved.")
        _write_operation(op_id, status="downloading", progress=2,
                         message="Downloading approved Prusa native runtime")
        if any(p.is_symlink() for p in (STORE, STORE / "versions", base, target)):
            raise ValueError("Unsafe Prusa engine store path.")
        base.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise ValueError("PrusaSlicer version is already installed.")
        # Keep downloaded tar outside the extracted stage, so every staged
        # file is subject to the manifest's exact-content verification.
        with tempfile.NamedTemporaryFile(prefix=".prusa-source-", suffix=".tar.gz",
                                         dir=base, delete=False) as temporary:
            archive_path = Path(temporary.name)
        archive_path.unlink()
        _download(release, archive_path, lambda n: _write_operation(op_id, progress=n))
        _write_operation(op_id, status="verifying", progress=70,
                         message="Checking Prusa native package and profile checksums")
        stage = Path(tempfile.mkdtemp(prefix=".prusa-stage-", dir=base))
        binary = unpack_reviewed_prusa(archive_path, stage)
        _write_operation(op_id, status="staged", progress=85,
                         message="Checking isolated Prusa CLI compatibility")
        # The exact binary already passed an authentic 3,737-extrusion cube
        # in the pinned GitHub acceptance run. Probe packaged CLI here without
        # a UI, network, shell, arbitrary input or developer-supplied script.
        try:
            probe = subprocess.run([str(binary), "--help"], cwd=stage,
                env={"HOME": str(stage), "TMPDIR": str(stage),
                     "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError("Prusa native CLI could not complete its headless check.") from exc
        if probe.returncode != 0:
            raise ValueError("Prusa native CLI failed its headless check.")
        binary_hash = prusa_sha256(binary)
        if binary_hash != PRUSA_BINARY_SHA256:
            raise ValueError("Prusa native runtime digest changed after verification.")
        (stage / IDENTITY).write_text(json.dumps({
            "engine": engine, "version": version,
            "binary": str(target / "bin" / "prusa-slicer"),
            "binary_sha256": binary_hash,
        }, separators=(",", ":")), encoding="utf-8")
        make_runtime_worker_readable(stage, required_executables=("bin/prusa-slicer",))
        stage.chmod(0o755)
        os.rename(stage, target)
        stage = None
        _write_operation(op_id, status="activating", progress=94,
                         message="Activating verified Prusa runtime")
        current = _manifest(STORE)
        if current["engines"]:
            preserve_active_identities(STORE)
            (STORE / "previous.json").write_text(
                json.dumps(current, separators=(",", ":")), encoding="utf-8")
        _write(STORE, {"schema_version": 1, "engines": {
            **current["engines"], engine: {
                "binary": str(target / "bin" / "prusa-slicer"),
                "version": version, "binary_sha256": binary_hash,
            },
        }})
        _write_operation(op_id, status="completed", progress=100,
                         message="PrusaSlicer installed and activated",
                         binary_sha256=binary_hash)
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ValueError) else (
            "Prusa installation could not complete safely (" + type(exc).__name__ + ").")
        LOGGER.error("Prusa runtime installation failed: %s", reason[:180])
        _write_operation(op_id, status="failed", progress=0, message=reason[:180])
    finally:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)
        if archive_path is not None:
            archive_path.unlink(missing_ok=True)


def start_install(engine, version, digest):
    version_ok = (version == BAMBU_VERSION if engine == "bambustudio"
                  else version == PRUSA_VERSION if engine == "prusaslicer"
                  else isinstance(version, str) and bool(VERSION.fullmatch(version)))
    if engine not in SUPPORTED or not version_ok or not isinstance(digest, str) or not HEX.fullmatch(digest):
        raise ValueError("Unknown engine release.")
    with LOCK:
        if any(op["status"] not in {"completed", "failed"} for op in OPERATIONS.values()):
            raise ValueError("Another engine install is running.")
    releases = release_catalogue()
    release = next((row for row in releases if row["engine"] == engine and
                    row["version"] == version and row["bundle_sha256"] == digest), None)
    if not release:
        raise ValueError("This engine version is not in the approved release catalogue.")
    op_id = str(uuid.uuid4())
    with LOCK:
        OPERATIONS[op_id] = {"id": op_id, "engine": engine, "version": version,
                             "action": "install", "status": "queued", "progress": 0,
                             "message": "Waiting to download"}
        while len(OPERATIONS) > MAX_OPERATIONS:
            key = next(iter(OPERATIONS))
            if OPERATIONS[key]["status"] not in {"completed", "failed"}:
                break
            OPERATIONS.pop(key)
        _persist_operations()
    Thread(target=_install, args=(op_id, release), daemon=True).start()
    return dict(OPERATIONS[op_id])


def _rollback_operation(op_id):
    try:
        _write_operation(op_id, status="verifying", progress=30,
                         message="Checking previous engine versions")
        rollback_store(STORE)
        _write_operation(op_id, status="completed", progress=100,
                         message="Previous engine selection restored")
    except Exception:
        _write_operation(op_id, status="failed", progress=0,
                         message="Previous versions could not be restored safely")


def start_rollback():
    previous = STORE / "previous.json"
    if previous.is_symlink() or not previous.is_file():
        raise ValueError("No previous engine selection.")
    with LOCK:
        if any(op["status"] not in {"completed", "failed"} for op in OPERATIONS.values()):
            raise ValueError("Another engine change is running.")
        op_id = str(uuid.uuid4())
        OPERATIONS[op_id] = {
            "id": op_id, "engine": "crealityprint", "version": "previous",
            "action": "rollback", "status": "queued", "progress": 0,
            "message": "Restoring previous engine selection",
        }
        _persist_operations()
    Thread(target=_rollback_operation, args=(op_id,), daemon=True).start()
    return dict(OPERATIONS[op_id])



def _lifecycle_operation(op_id, engine, version, action):
    try:
        _write_operation(op_id, status="verifying", progress=30,
                         message="Checking installed engine versions")
        if action == "activate":
            activate_installed(STORE, engine, version)
            message = "Installed version activated"
        elif action == "uninstall":
            uninstall_engine(STORE, engine)
            message = "Engine uninstalled; other engines preserved"
        else:
            raise ValueError("Unsupported engine operation.")
        _write_operation(op_id, status="completed", progress=100, message=message)
    except Exception as exc:
        LOGGER.warning("Engine %s %s failed: %s", action, engine, type(exc).__name__)
        _write_operation(op_id, status="failed", progress=0,
                         message="Engine operation refused; check the installed version and active jobs.")


def start_lifecycle(engine, version, action):
    if action not in {"activate", "uninstall"} or engine not in INSTALLED_ENGINE_TYPES:
        raise ValueError("Unsupported engine operation.")
    if not isinstance(version, str) or (action == "activate" and not VERSION.fullmatch(version)):
        raise ValueError("Invalid installed engine version.")
    if action == "uninstall" and version != "all":
        raise ValueError("Uninstall requires an explicit all-versions selection.")
    choices = installed_versions(STORE).get(engine, [])
    if not choices or (action == "activate" and version not in {
            entry["version"] for entry in choices if not entry["active"]}):
        raise ValueError("Installed version is unavailable.")
    with LOCK:
        if any(op["status"] not in {"completed", "failed"} for op in OPERATIONS.values()):
            raise ValueError("Another engine change is running.")
        op_id = str(uuid.uuid4())
        OPERATIONS[op_id] = {
            "id": op_id, "engine": engine, "version": version,
            "action": action, "status": "queued", "progress": 0,
            "message": "Waiting for engine change",
        }
        _persist_operations()
    Thread(target=_lifecycle_operation,
           args=(op_id, engine, version, action), daemon=True).start()
    return dict(OPERATIONS[op_id])


class Handler(BaseHTTPRequestHandler):
    server_version = "MakerVaultEngineInstaller/1"
    def log_message(self, *args):
        pass
    def respond(self, code, data):
        raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    def authenticated(self):
        return (len(TOKEN) >= 32 and hmac.compare_digest(
            self.headers.get("Authorization", ""), "Bearer " + TOKEN))
    def do_GET(self):
        if not self.authenticated():
            return self.respond(403, {"error": "Unauthorized"})
        if self.path == "/catalog":
            try:
                return self.respond(200, {"releases": release_catalogue()})
            except Exception:
                return self.respond(503, {"error": "Official engine releases are unavailable."})
        if self.path == "/status":
            with LOCK:
                return self.respond(200, {"operations": list(OPERATIONS.values())[-30:],
                                          "installed_versions": installed_versions(STORE),
                                          "rollback_available": (STORE / "previous.json").is_file()})
        return self.respond(404, {"error": "Not found"})
    def do_POST(self):
        if self.path not in {"/install", "/rollback", "/activate", "/uninstall"} or not self.authenticated():
            return self.respond(403, {"error": "Unauthorized"})
        if self.path == "/rollback":
            try:
                return self.respond(202, {"operation": start_rollback()})
            except ValueError:
                return self.respond(409, {"error": "Rollback is not available."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2048:
                return self.respond(413, {"error": "Invalid request size"})
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Invalid engine selection.")
            if self.path == "/install":
                if set(data) != {"engine", "version", "bundle_sha256"}:
                    raise ValueError("Invalid release selection.")
                result = start_install(data["engine"], data["version"], data["bundle_sha256"])
            else:
                if set(data) != {"engine", "version"}:
                    raise ValueError("Invalid installed engine selection.")
                result = start_lifecycle(data["engine"], data["version"],
                                         self.path.removeprefix("/"))
        except (ValueError, KeyError, TypeError):
            return self.respond(400, {"error": "Requested version is not available or another update is running."})
        except Exception:
            return self.respond(503, {"error": "Official release service is unavailable."})
        return self.respond(202, {"operation": result})


def bootstrap_existing_orca():
    """Import the exact staging Orca binary rather than a different bundled one.

    Its staging manifest provides the originally validated SHA-256. Only the
    already-configured local AppImage is read, never a user-supplied path.
    """
    staging = Path("/opt/staging-orca")
    manifest = staging / "manifest.json"
    binary = staging / "orcaslicer.AppImage"
    if not manifest.exists():
        root = STORE / "versions" / "orcaslicer" / APPROVAL_VERSION
        if not root.exists():
            seed_bundled_orca(store=STORE)
        activate(STORE, engine="orcaslicer", version=APPROVAL_VERSION,
                 sha256=EXPECTED_ORCA_SHA)
        return
    if (staging.is_symlink() or binary.is_symlink() or manifest.is_symlink()
            or not binary.is_file() or not manifest.is_file()):
        raise ValueError("Existing Orca stage is unsafe.")
    if manifest.stat().st_size > 16384:
        raise ValueError("Existing Orca stage manifest is oversized.")
    entries = json.loads(manifest.read_text(encoding="utf-8")).get("engines", {})
    item = entries.get("orcaslicer")
    if not isinstance(item, dict):
        raise ValueError("No existing staged Orca engine.")
    version = item.get("version")
    digest = item.get("binary_sha256")
    if (not isinstance(version, str) or not VERSION.fullmatch(version)
            or not isinstance(digest, str) or not HEX.fullmatch(digest)
            or item.get("binary") != "/opt/engines/orcaslicer.AppImage"
            or _sha256(binary) != digest):
        raise ValueError("Existing Orca SHA-256 does not match staged identity.")
    target = STORE / "versions" / "orcaslicer" / version
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        stage = Path(tempfile.mkdtemp(prefix=".orca-", dir=target.parent))
        try:
            shutil.copy2(binary, stage / "orcaslicer.AppImage")
            (stage / "orcaslicer.AppImage").chmod(0o555)
            result = subprocess.run([str(stage / "orcaslicer.AppImage"),
                                     "--appimage-extract"], cwd=stage,
                env={"HOME": str(stage), "TMPDIR": str(stage),
                     "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL, timeout=240, check=False)
            if result.returncode != 0 or not (stage / "squashfs-root" / "AppRun").exists():
                raise ValueError("Existing Orca AppImage extraction failed.")
            os.rename(stage, target)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    activate(STORE, engine="orcaslicer", version=version, sha256=digest)


def repair_active_bambu_runtime_permissions():
    """Repair legacy Bambu AppImage directories as installer UID, not worker.

    Previously published extracted trees could retain 0700 directories and
    appear healthy despite failing native slicing for worker UID 10001.
    Reapply the read-only publication policy only to an exact, pinned active
    Bambu installation. No reinstallation or engine manifest rewrite.
    """
    active = STORE / "active.json"
    if active.is_symlink() or not active.is_file():
        return
    manifest = _manifest(STORE)
    record = manifest.get("engines", {}).get("bambustudio")
    if not isinstance(record, dict) or record.get("version") != BAMBU_VERSION:
        return
    root = STORE / "versions" / "bambustudio" / BAMBU_VERSION / "squashfs-root"
    binary = root / "bin" / "bambu-studio"
    if (record.get("binary") != str(root / "AppRun")
            or record.get("binary_sha256") != BAMBU_RUNTIME_SHA256
            or root.is_symlink() or not root.is_dir()
            or binary.is_symlink() or not binary.is_file()
            or _sha256(binary) != BAMBU_RUNTIME_SHA256):
        # Repair is best-effort maintenance, not an installation admission
        # gate. An older active manifest may identify a different pinned
        # launcher, or its runtime may be unavailable. Leave the store
        # untouched and allow the already-installed other engines to start.
        # The worker independently verifies active runtime identities.
        LOGGER.warning(
            "Skipping Bambu runtime permissions repair: pinned identity is not verified.")
        return
    make_runtime_worker_readable(
        root, required_executables=("bin/bambu-studio",))
    LOGGER.info("Verified Bambu runtime subtree traversal for the unprivileged worker.")


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if len(TOKEN) < 32 or STORE.is_symlink() or not STORE.is_dir():
        raise SystemExit("Installer requires a restricted engine volume and a strong token.")
    if not os.access(STORE, os.W_OK):
        raise SystemExit("Engine-store volume is not writable by installer user.")
    # Preserve the already-working OrcaSlicer installation when an additional
    # engine is first installed; otherwise the new active manifest would
    # accidentally hide Orca. Bootstrap once from the pinned bundle.
    if not (STORE / "active.json").exists():
        bootstrap_existing_orca()
    repair_active_bambu_runtime_permissions()
    _restore_operations()
    server = ThreadingHTTPServer(("0.0.0.0", 8091), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
