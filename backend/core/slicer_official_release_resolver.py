"""Fail-closed official catalogue release selection.

Only explicitly supported immutable upstream release refs may be fetched.
The native worker's selected exact engine version is the lookup key;
profile imports never silently use a nearby release or rewrite old assets.
This is source identity, not execution approval.
"""
from dataclasses import dataclass

from .slicer_official_profiles import OfficialProfileError

@dataclass(frozen=True)
class CatalogueRelease:
    engine: str
    version: str
    source: str
    ref: str

# The providers themselves own the upstream layout and index parsers.
# Every new slicer engine release needs its own reviewed source mapping.
_RELEASES = {
    "orcaslicer": {
        "2.4.2": ("OrcaSlicer/OrcaSlicer", "v2.4.2"),
        "2.5.0": ("OrcaSlicer/OrcaSlicer", "v2.5.0"),
    },
    "crealityprint": {
        "7.3.1": ("CrealityOfficial/CrealityPrint", "v7.3.1"),
    },
    "bambustudio": {
        "02.09.01.70": ("bambulab/BambuStudio", "v02.09.01.70"),
    },
    "prusaslicer": {
        "2.9.7": ("prusa3d/PrusaSlicer", "version_2.9.7"),
    },
    "snapmakerorca": {
        "2.4.1": ("Snapmaker/OrcaSlicer", "v2.4.1"),
    },
}


def approved_catalogue_versions(engine):
    return tuple(_RELEASES.get(engine, ()))


def resolve_official_release(engine, version):
    """Resolve only an exact approved engine/version pair, never a fallback."""
    if not isinstance(engine, str) or not isinstance(version, str):
        raise OfficialProfileError("Select an exact slicer engine and release.")
    source_ref = _RELEASES.get(engine, {}).get(version)
    if source_ref is None:
        supported = ", ".join(approved_catalogue_versions(engine)) or "none"
        raise OfficialProfileError(
            "No approved official profile catalogue matches "
            + engine[:48] + " " + version[:48]
            + ". Approved releases: " + supported
            + ". Select a supported engine release or import a "
            "separately reviewed native preset.")
    return CatalogueRelease(engine, version, *source_ref)


def default_catalogue_version(engine):
    """Legacy requests with no version must not invent a different release."""
    values = approved_catalogue_versions(engine)
    if len(values) == 1:
        return values[0]
    if engine == "orcaslicer":
        # Preserve old Orca endpoint default; UI always sends a chosen version.
        return "2.4.2"
    raise OfficialProfileError("Select an exact supported catalogue version.")
