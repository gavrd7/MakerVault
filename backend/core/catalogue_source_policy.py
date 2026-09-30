"""Authority ordering for automated MakerVault catalogue enrichment.

Lower numeric priority means a more authoritative source. Automated enrichment
must never overwrite a populated user/manual value; lower-priority providers
only fill fields still unresolved after higher-priority providers have run.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class CatalogueSourceTier:
    key: str
    priority: int
    label: str
    description: str


SOURCE_TIERS = {
    "manual": CatalogueSourceTier(
        "manual", 0, "User / manual",
        "Explicit catalogue values entered or maintained by a user.",
    ),
    "manufacturer": CatalogueSourceTier(
        "manufacturer", 10, "Official manufacturer",
        "Manufacturer product pages, documentation, datasheets and official APIs.",
    ),
    "curated": CatalogueSourceTier(
        "curated", 20, "MakerVault curated",
        "Version-controlled MakerVault profiles backed by authoritative references.",
    ),
    "specialist": CatalogueSourceTier(
        "specialist", 30, "Specialist catalogue",
        "Domain-specific structured catalogues such as ESPBoards, OrcaSlicer and SpoolmanDB.",
    ),
    "community": CatalogueSourceTier(
        "community", 40, "Community / ecosystem",
        "Well-maintained ecosystem documentation and source repositories.",
    ),
    "open_media": CatalogueSourceTier(
        "open_media", 50, "Open media",
        "Openly licensed imagery from Wikimedia Commons and Openverse.",
    ),
    "generic": CatalogueSourceTier(
        "generic", 60, "Generic fallback",
        "Fallback source used only when stronger sources have no usable value.",
    ),
}


SPECIALIST_HOSTS = {
    "espboards.dev",
    "www.espboards.dev",
}

KNOWN_MANUFACTURER_HOST_SUFFIXES = {
    "adafruit.com",
    "arduino.cc",
    "espressif.com",
    "raspberrypi.com",
    "seeedstudio.com",
    "sparkfun.com",
    "dfrobot.com",
    "pimoroni.com",
    "waveshare.com",
    "pjrc.com",
    "microchip.com",
    "st.com",
    "ti.com",
    "nxp.com",
    "bosch-sensortec.com",
    "sensirion.com",
    "orangepi.org",
    "hardkernel.com",
    "radxa.com",
    "banana-pi.org",
    "beagleboard.org",
    "lattepanda.com",
    "nvidia.com",
    "khadas.com",
}


def source_tier(key: str) -> CatalogueSourceTier:
    return SOURCE_TIERS.get(str(key or "").strip().lower(), SOURCE_TIERS["generic"])


def classify_source_url(url: str, *, source_type: str = "") -> CatalogueSourceTier:
    source_type = str(source_type or "").strip().lower()
    if source_type == "manual":
        return SOURCE_TIERS["manual"]
    if source_type == "manufacturer":
        return SOURCE_TIERS["manufacturer"]
    if source_type in {"espboards", "spoolmandb", "filamentprofiles", "filamentsdb"}:
        return SOURCE_TIERS["specialist"]
    if source_type in {"github", "gitlab"}:
        return SOURCE_TIERS["community"]

    try:
        host = (urlparse(str(url or "")).hostname or "").lower()
    except ValueError:
        host = ""

    if any(host == suffix or host.endswith("." + suffix) for suffix in KNOWN_MANUFACTURER_HOST_SUFFIXES):
        return SOURCE_TIERS["manufacturer"]
    if host in SPECIALIST_HOSTS:
        return SOURCE_TIERS["specialist"]
    return SOURCE_TIERS["generic"]


def ordered_source_candidates(candidates: list[dict]) -> list[dict]:
    """Return source candidates ordered by authority, preserving stable order."""
    decorated = []
    for index, candidate in enumerate(candidates):
        tier = classify_source_url(
            candidate.get("url", ""),
            source_type=candidate.get("source_type", ""),
        )
        decorated.append((tier.priority, index, {**candidate, "tier": tier.key, "priority": tier.priority}))
    decorated.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in decorated]


def append_source_trace(metadata: dict, *, provider: str, url: str, tier: str, result: str) -> dict:
    """Append a bounded provenance/attempt record to catalogue JSON metadata."""
    out = dict(metadata or {})
    trace = list(out.get("source_trace") or [])
    entry = {
        "provider": str(provider or "")[:160],
        "url": str(url or "")[:1000],
        "tier": source_tier(tier).key,
        "priority": source_tier(tier).priority,
        "result": str(result or "")[:80],
    }
    if entry not in trace:
        trace.append(entry)
    out["source_trace"] = trace[-20:]
    return out
