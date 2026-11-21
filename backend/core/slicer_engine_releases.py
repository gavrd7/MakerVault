"""Curated engine release catalogue for the isolated host-updater workflow.

Never derive a download URL or executable path from an HTTP request. Releases
are opt-in and must be reviewed before being shipped with the application.
An empty catalogue is deliberate: no additional engine binaries have passed
the MakerVault integration gates yet.

A future signed release feed may populate entries via a separately reviewed
administrative update, but not an arbitrary user-supplied feed URL.
"""
import re
from .slicer_engines import get_engine

HEX64 = re.compile(r"^[0-9a-f]{64}$")
VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,79}$")
# Entries approved by an administrator following isolated engine fixture tests.
# The updater MUST independently verify all checksums before activation.
APPROVED_RELEASES = ()


def validated_releases():
    result = []
    for item in APPROVED_RELEASES:
        if not isinstance(item, dict) or set(item) != {
            "engine", "version", "binary_sha256", "bundle_sha256",
            "bundle_url", "architecture", "notes", "adapter_validated"
        }:
            raise ValueError("Malformed curated engine release.")
        engine = get_engine(item["engine"])
        if (not VERSION.fullmatch(item["version"])
                or not HEX64.fullmatch(item["binary_sha256"])
                or not HEX64.fullmatch(item["bundle_sha256"])
                or item["architecture"] not in {"linux/amd64", "linux/arm64"}
                or item["adapter_validated"] is not True
                or not item["bundle_url"].startswith("https://")
                or len(item["bundle_url"]) > 1024):
            raise ValueError("Unapproved engine release metadata.")
        result.append({
            "engine": engine.key, "version": item["version"],
            "binary_sha256": item["binary_sha256"],
            "bundle_sha256": item["bundle_sha256"],
            "architecture": item["architecture"],
            "notes": str(item["notes"])[:500],
            "adapter_validated": True,
        })
    return result


def approved_release(engine, version, bundle_sha256):
    for item in validated_releases():
        if (item["engine"] == engine and item["version"] == version
                and item["bundle_sha256"] == bundle_sha256):
            return item
    raise ValueError("This engine version is not in the approved release catalogue.")
