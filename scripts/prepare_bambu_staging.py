"""Opt-in, checksum-pinned Bambu Studio 2.9.1 Linux AppImage staging.

This fetches the official upstream executable into an EMPTY local ignored
slicer-engine-assets directory. It never enables a worker or printer command.
Run only in a disposable test checkout, not over an existing Orca/Creality
bundle. Requires internet access on the host and no additional Python packages.

  python3 scripts/prepare_bambu_staging.py
  docker build -f slicer_worker/Dockerfile.bundle -t makervault-bambu-candidate:local .

Before enabling Bambu in MakerVault, run genuine pinned CLI/native profile
fixtures in an isolated worker and review the resulting G-code.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VERSION = "02.09.01.70"
TAG = "v" + VERSION
ASSET = "BambuStudio_ubu24-v02.09.01.70-20261103183404.AppImage"
# Official GitHub release-asset digest, cross-checked against independent
# publisher-release metadata. Fail closed if GitHub changes asset content.
SHA256 = "668dabb1be53c758189ed6bc89935285dea5e0af46216546b1bafd6882e9aff0"
API_URL = "https://api.github.com/repos/bambulab/BambuStudio/releases/tags/" + TAG
ASSET_URL = "https://github.com/bambulab/BambuStudio/releases/download/" + TAG + "/" + ASSET
MAX_METADATA = 2 * 1024 * 1024
MAX_ASSET = 512 * 1024 * 1024
ALLOWED_DOWNLOAD_HOSTS = frozenset({
    "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com",
})


def _request(url):
    headers = {"User-Agent": "MakerVault-Bambu-Candidate-Installer",
               "Accept": "application/vnd.github+json"}
    token = os.environ.get("GH_TOKEN", "")
    if token and url == API_URL:
        headers["Authorization"] = "Bearer " + token
    return Request(url, headers=headers)


def official_asset():
    """Check official release API metadata before accepting fixed asset URL."""
    with urlopen(_request(API_URL), timeout=25) as response:
        if response.status != 200 or response.geturl() != API_URL:
            raise ValueError("Official Bambu Studio release metadata was redirected or unavailable.")
        data = response.read(MAX_METADATA + 1)
    if len(data) > MAX_METADATA:
        raise ValueError("Bambu release metadata exceeds the limit.")
    payload = json.loads(data)
    matches = [entry for entry in payload.get("assets", [])
               if isinstance(entry, dict) and entry.get("name") == ASSET]
    if len(matches) != 1:
        raise ValueError("Pinned Bambu Studio Linux release asset is missing.")
    item = matches[0]
    if item.get("browser_download_url") != ASSET_URL:
        raise ValueError("Pinned Bambu release URL does not match the official URL.")
    if item.get("digest") != "sha256:" + SHA256:
        raise ValueError("Official Bambu release SHA-256 differs from the audited digest.")
    if not isinstance(item.get("size"), int) or not 0 < item["size"] <= MAX_ASSET:
        raise ValueError("Pinned Bambu release size is invalid.")
    return ASSET_URL


def fetch_candidate(destination):
    """Stream, verify, and stage without replacing any existing engine."""
    target = Path(destination).resolve()
    if target.exists() and (target.is_symlink() or not target.is_dir() or any(target.iterdir())):
        raise ValueError("Refusing to replace an existing slicer engine bundle.")
    url = official_asset()
    with tempfile.TemporaryDirectory(prefix="makervault-bambu-download-") as scratch:
        asset = Path(scratch) / ASSET
        digest = hashlib.sha256()
        count = 0
        with urlopen(_request(url), timeout=90) as response:
            redirect = urlsplit(response.geturl())
            if redirect.scheme != "https" or redirect.hostname not in ALLOWED_DOWNLOAD_HOSTS:
                raise ValueError("Untrusted redirect in Bambu Studio download.")
            with asset.open("xb") as output:
                while data := response.read(1024 * 1024):
                    count += len(data)
                    if count > MAX_ASSET:
                        raise ValueError("Bambu Studio AppImage exceeds the download limit.")
                    digest.update(data)
                    output.write(data)
        if not count or digest.hexdigest() != SHA256:
            raise ValueError("Bambu Studio AppImage SHA-256 verification failed.")
        # Official AppImage magic: ELF; checksum remains authoritative.
        if asset.open("rb").read(4) != b"\\x7fELF":
            raise ValueError("Pinned Bambu Studio asset is not an ELF AppImage.")
        from slicer_worker.stage_engines import stage_engines
        return stage_engines([("bambustudio", VERSION, str(asset), SHA256)], target)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", default=str(ROOT / "slicer-engine-assets"),
                        help="Empty local bundle directory for an isolated candidate build")
    args = parser.parse_args()
    try:
        result = fetch_candidate(args.destination)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print("Bambu Studio candidate preparation refused: " + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    print("Bambu AppImage staged and checksum-verified; the engine is NOT enabled.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
