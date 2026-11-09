"""Bounded, same-origin native build-plate artwork from official Orca presets.

A machine preset can declare bed_texture, but it is not a trusted URL.
Only an asset basename from a hash-checked owned machine preset, under
MakerVault's pinned upstream official profile source, is eligible.
No external URLs from imported profiles are followed.
"""
import hashlib
import re
from xml.etree import ElementTree

import requests
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from .slicer_official_profiles import REF, BASE, VENDORS
from .slicer_profile_lineage import _inspect_source
from .slicer_profiles import SlicerProfileError


MAX_ARTWORK_BYTES = 256 * 1024
_PROVENANCE = re.compile(
    r"^OrcaSlicer/OrcaSlicer@" + re.escape(REF) +
    r"/([A-Za-z0-9_-]+)/machine/[^/]+\.json$"
)
_BASENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}\.svg$", re.I)
_XML_SVG = "{http://www.w3.org/2000/svg}"


def official_artwork_source(profile):
    """Return a fixed upstream asset URL and cache key, or None.

    This does not imply slicing or printer compatibility.
    """
    if profile.engine != "orcaslicer" or profile.kind != "printer":
        return None
    match = _PROVENANCE.fullmatch(str(profile.provenance or ""))
    if not match or match.group(1) not in VENDORS:
        return None
    try:
        data = _inspect_source(profile)
    except SlicerProfileError:
        return None
    filename = data.get("bed_texture")
    if not isinstance(filename, str) or not _BASENAME.fullmatch(filename):
        return None
    vendor = match.group(1)
    url = f"{BASE}/{vendor}/{filename}"
    cache_key = hashlib.sha256(url.encode("utf-8")).hexdigest() + ".svg"
    return url, "slicer-reviewed-native-artwork/" + cache_key


def _verify_svg(raw):
    if not raw or len(raw) > MAX_ARTWORK_BYTES:
        raise ValueError("Native SVG artwork has an invalid size.")
    lower = raw.lower()
    # No active content, external loads, DTDs, referenced resources, or CSS URLs.
    if any(token in lower for token in (
        b"<!doctype", b"<!entity", b"<script", b"foreignobject",
        b"href=", b"url(", b"@import", b"javascript:", b"<animate",
        b"<set", b"<style",
    )):
        raise ValueError("Native SVG artwork contains unsupported content.")
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        raise ValueError("Native SVG artwork is malformed.") from None
    if root.tag != _XML_SVG + "svg":
        raise ValueError("Native artwork is not SVG.")
    allowed_tags = {
        "svg", "g", "path", "rect", "circle", "ellipse", "line",
        "polyline", "polygon", "defs", "clipPath", "linearGradient",
        "radialGradient", "stop", "text", "tspan",
    }
    for element in root.iter():
        if not isinstance(element.tag, str) or not element.tag.startswith(_XML_SVG):
            raise ValueError("Native SVG contains unsupported elements.")
        if element.tag[len(_XML_SVG):] not in allowed_tags:
            raise ValueError("Native SVG contains unsupported elements.")
        for key in element.attrib:
            if not key.startswith(_XML_SVG) and "}" in key:
                raise ValueError("Native SVG contains a foreign attribute.")
            local = key.rsplit("}", 1)[-1].lower()
            if local.startswith("on") or local in ("href", "src"):
                raise ValueError("Native SVG contains an unsafe attribute.")
    return raw


def cached_official_artwork(profile):
    """Cache a bounded, vetted official asset locally for subsequent offline use."""
    source = official_artwork_source(profile)
    if source is None:
        return None
    url, name = source
    if default_storage.exists(name):
        with default_storage.open(name, "rb") as stream:
            raw = stream.read(MAX_ARTWORK_BYTES + 1)
        try:
            return _verify_svg(raw)
        except ValueError:
            default_storage.delete(name)
    try:
        response = requests.get(
            url, timeout=(3, 12), stream=True, allow_redirects=False,
            headers={"Accept": "image/svg+xml", "User-Agent": "MakerVault-BedArtwork/1"},
        )
        try:
            if response.status_code != 200:
                return None
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > MAX_ARTWORK_BYTES:
                return None
            chunks = bytearray()
            for chunk in response.iter_content(32768):
                chunks.extend(chunk)
                if len(chunks) > MAX_ARTWORK_BYTES:
                    return None
            raw = _verify_svg(bytes(chunks))
        finally:
            response.close()
    except (requests.RequestException, ValueError, OSError):
        return None
    default_storage.save(name, ContentFile(raw))
    return raw
