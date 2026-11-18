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
    EXPECTED_ORCA_SHA, APPROVAL_VERSION,
)

STORE = Path(os.environ.get("SLICER_ENGINE_STORE", "/opt/engine-store"))
TOKEN = os.environ.get("SLICER_INSTALLER_TOKEN", "")
SUPPORTED = {"crealityprint": "CrealityOfficial/CrealityPrint"}
MAX_BYTES = 650 * 1024 * 1024
VERSION = re.compile(r"^v?(\d+\.\d+\.\d+)$")
HEX = re.compile(r"^[a-f0-9]{64}$")
OPERATIONS = {}
LOCK = Lock()
MAX_OPERATIONS = 50
RELEASE_CACHE = {"time": 0.0, "items": []}
RELEASE_CACHE_SECONDS = 600
OPERATION_FILE = STORE / "installer-operations.json"


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
    base = STORE / "versions" / engine
    target = base / version
    stage = None
    try:
        _write_operation(op_id, status="downloading", progress=2, message="Downloading official release")
        base.mkdir(parents=True, exist_ok=True)
        if STORE.is_symlink() or base.is_symlink() or target.is_symlink():
            raise ValueError("Unsafe engine store path.")
        if target.exists():
            raise ValueError("This engine version is already installed.")
        stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=base))
        image = stage / (engine + ".AppImage")
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
        extracted = subprocess.run([str(image), "--appimage-extract"],
            cwd=stage, env={"HOME": str(stage), "TMPDIR": str(stage),
                            "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=90, check=False)
        app_run = stage / "squashfs-root" / "AppRun"
        if extracted.returncode != 0 or not app_run.exists():
            raise ValueError("Engine extraction failed compatibility check.")
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
            probe = subprocess.run([str(app_run), "--help"], cwd=stage,
                env={"HOME": str(stage), "TMPDIR": str(stage),
                     "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
                     "DISPLAY": "", "QT_QPA_PLATFORM": "offscreen"},
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=18, check=False)
        except (subprocess.TimeoutExpired, OSError):
            raise ValueError("Creality Print CLI could not run headlessly.")
        if probe.returncode != 0:
            raise ValueError("Creality Print CLI compatibility check failed.")
        # Stage a complete version before publishing it; preserve all older
        # engines and use a single atomic manifest rename for activation.
        binary_hash = _sha256(runtime)
        if not HEX.fullmatch(binary_hash):
            raise ValueError("Engine runtime digest unavailable.")
        os.rename(stage, target)
        stage = None
        _write_operation(op_id, status="activating", progress=94,
                         message="Activating installed version")
        current = _manifest(STORE)
        existing = current["engines"]
        new_record = {
            "binary": str(target / runtime_relative),
            "version": version, "binary_sha256": binary_hash,
        }
        # Keep other engines, including the existing Orca runtime, untouched.
        new_manifest = {"schema_version": 1,
                        "engines": {**existing, engine: new_record}}
        if existing:
            _write(STORE, current)  # Ensure manifest formatting is consistent.
            previous = STORE / "previous.json"
            previous.write_text(json.dumps(current, separators=(",", ":")), encoding="utf-8")
        _write(STORE, new_manifest)
        _write_operation(op_id, status="completed", progress=100,
                         message="Installed and activated", binary_sha256=binary_hash)
    except Exception as exc:
        # No raw paths, URLs, command output or credentials in the UI.
        reason = str(exc) if isinstance(exc, ValueError) else "Installer could not complete this release."
        _write_operation(op_id, status="failed", message=reason[:180], progress=0)
    finally:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)


def start_install(engine, version, digest):
    if engine not in SUPPORTED or not VERSION.fullmatch(version) or not HEX.fullmatch(digest):
        raise ValueError("Unknown engine release.")
    with LOCK:
        if any(op["status"] not in {"completed", "failed"} for op in OPERATIONS.values()):
            raise ValueError("Another engine install is running.")
    releases = release_catalogue()
    release = next((row for row in releases if row["engine"] == engine and
                    row["version"] == version and row["bundle_sha256"] == digest), None)
    if not release:
        raise ValueError("This version is not in the official release catalogue.")
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
                return self.respond(200, {"operations": list(OPERATIONS.values())[-30:]})
        return self.respond(404, {"error": "Not found"})
    def do_POST(self):
        if self.path != "/install" or not self.authenticated():
            return self.respond(403, {"error": "Unauthorized"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2048:
                return self.respond(413, {"error": "Invalid request size"})
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict) or set(data) != {"engine", "version", "bundle_sha256"}:
                raise ValueError("Invalid release selection.")
            result = start_install(data["engine"], data["version"], data["bundle_sha256"])
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
                stdin=subprocess.DEVNULL, timeout=120, check=False)
            if result.returncode != 0 or not (stage / "squashfs-root" / "AppRun").exists():
                raise ValueError("Existing Orca AppImage extraction failed.")
            os.rename(stage, target)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    activate(STORE, engine="orcaslicer", version=version, sha256=digest)


def main():
    if len(TOKEN) < 32 or STORE.is_symlink() or not STORE.is_dir():
        raise SystemExit("Installer requires a restricted engine volume and a strong token.")
    if not os.access(STORE, os.W_OK):
        raise SystemExit("Engine-store volume is not writable by installer user.")
    # Preserve the already-working OrcaSlicer installation when an additional
    # engine is first installed; otherwise the new active manifest would
    # accidentally hide Orca. Bootstrap once from the pinned bundle.
    if not (STORE / "active.json").exists():
        bootstrap_existing_orca()
    _restore_operations()
    server = ThreadingHTTPServer(("0.0.0.0", 8091), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
