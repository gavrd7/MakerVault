"""Provider-neutral, non-executable slicer engine catalogue.

This catalogue advertises *candidates* only. No binary is installed or
executable until an administrator configures and verifies an isolated worker.
CLI flags/profiles intentionally stay in worker-specific adapters.
"""
from dataclasses import dataclass

ENGINE_STATUSES = frozenset({"candidate", "experimental", "validated"})


@dataclass(frozen=True)
class SlicerEngine:
    key: str
    label: str
    upstream: str
    profile_format: str
    cli_reference: str
    status: str = "candidate"

    def as_public_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "profile_format": self.profile_format,
            "status": self.status,
            "available": False,
            "enabled": False,
        }


# A candidate is not an installed engine, an executable path or a promise
# of compatibility. Versions must be pinned and verified on the worker.
ENGINES = (
    SlicerEngine(
        key="orcaslicer",
        label="OrcaSlicer",
        upstream="https://github.com/OrcaSlicer/OrcaSlicer",
        profile_format="orca-json",
        cli_reference="https://github.com/OrcaSlicer/OrcaSlicer/wiki/cli_actions",
    ),
    SlicerEngine(
        key="crealityprint",
        label="Creality Print",
        upstream="https://github.com/CrealityOfficial/CrealityPrint",
        profile_format="creality-json",
        cli_reference="https://github.com/CrealityOfficial/CrealityPrint",
    ),
    SlicerEngine(
        key="bambustudio",
        label="Bambu Studio",
        upstream="https://github.com/bambulab/BambuStudio",
        profile_format="bambu-json",
        cli_reference="https://github.com/bambulab/BambuStudio/wiki/Command-Line-Usage",
    ),
    SlicerEngine(
        key="prusaslicer",
        label="PrusaSlicer",
        upstream="https://github.com/prusa3d/PrusaSlicer",
        profile_format="prusa-ini",
        cli_reference="https://github.com/prusa3d/PrusaSlicer/wiki/Command-Line-Interface",
    ),
    SlicerEngine(
        key="snapmakerorca",
        label="Snapmaker Orca",
        upstream="https://github.com/Snapmaker/OrcaSlicer",
        profile_format="snapmaker-orca-json",
        cli_reference="https://github.com/Snapmaker/OrcaSlicer",
    ),
    # Planned candidates only: these records do not enable execution or imply
    # binary, platform, profile, or headless-CLI compatibility.
    SlicerEngine(
        key="elegooslicer",
        label="ElegooSlicer",
        upstream="https://github.com/elegooofficial/ElegooSlicer",
        profile_format="elegoo-native-unverified",
        cli_reference="https://github.com/elegooofficial/ElegooSlicer",
    ),
    SlicerEngine(
        key="cura",
        label="UltiMaker Cura",
        upstream="https://github.com/Ultimaker/Cura",
        profile_format="cura-native-unverified",
        cli_reference="https://github.com/Ultimaker/CuraEngine",
    ),
    SlicerEngine(
        key="anycubicslicernext",
        label="Anycubic Slicer Next",
        upstream="https://github.com/ANYCUBIC-3D/AnycubicSlicerNext",
        profile_format="anycubic-next-native-unverified",
        cli_reference="https://github.com/ANYCUBIC-3D/AnycubicSlicerNext",
    ),
)


def engine_catalogue() -> list[dict]:
    """An informational catalogue only; no implicit host executable probing."""
    return [engine.as_public_dict() for engine in ENGINES]


def get_engine(key: str) -> SlicerEngine:
    """Look up by a fixed identifier; never interpret a client-supplied path."""
    for engine in ENGINES:
        if engine.key == key:
            return engine
    raise ValueError("Unsupported slicing engine.")


def validate_engine_selection(engine_key: str, engine_version: str, installed: dict) -> dict:
    """Require an explicitly administrator-approved pinned worker installation.

    *installed* is supplied by an authenticated worker-inventory layer in a
    future milestone, never by a request payload. No command is run here.
    """
    engine = get_engine(engine_key)
    if not isinstance(engine_version, str) or not engine_version or len(engine_version) > 80:
        raise ValueError("A pinned engine version is required.")
    if not isinstance(installed, dict):
        raise ValueError("Slicing service is not configured.")
    record = installed.get(engine.key)
    if not isinstance(record, dict):
        raise ValueError("Slicing engine is not installed on an approved worker.")
    if record.get("version") != engine_version:
        raise ValueError("Requested engine version is not installed.")
    if record.get("enabled") is not True or record.get("verified") is not True:
        raise ValueError("Slicing engine is not verified and enabled.")
    digest = record.get("image_digest")
    if not isinstance(digest, str) or not digest.startswith("sha256:") or len(digest) != 71:
        raise ValueError("Slicing engine image is not pinned by SHA-256 digest.")
    if not all(ch in "0123456789abcdef" for ch in digest[7:]):
        raise ValueError("Slicing engine image digest is invalid.")
    return {
        "engine": engine.key,
        "version": engine_version,
        "image_digest": digest,
        "profile_format": engine.profile_format,
    }
