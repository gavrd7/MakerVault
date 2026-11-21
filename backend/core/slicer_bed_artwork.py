"""Bounded, same-origin native build-plate artwork from official Orca presets.

A machine preset can declare bed_texture, but it is not a trusted URL.
Only an asset basename from a hash-checked owned machine preset, under
MakerVault's pinned upstream official profile source, is eligible.
No external URLs from imported profiles are followed.
"""
import hashlib
import json
import re
from configparser import ConfigParser, Error as ConfigError
from functools import lru_cache
from defusedxml import ElementTree

import requests
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from .slicer_official_profiles import VENDORS as ORCA_VENDORS
from .slicer_creality_official_profiles import VENDORS as CREALITY_VENDORS
from .slicer_mesh import inspect_stl, MeshInspectionError
from .slicer_profile_lineage import _inspect_source
from .slicer_native_resolution import resolved_native_profile
from .slicer_profiles import SlicerProfileError, _check_orca_json
from .slicer_official_profiles import _get_json, OfficialProfileError


MAX_ARTWORK_BYTES = 256 * 1024
MAX_BED_MODEL_BYTES = 4 * 1024 * 1024
# Only fixed, audited upstream owners and version-tagged profiles are eligible.
# The user's own profile provenance cannot supply a hostname or URL.
SOURCES = {
    "orcaslicer": ("OrcaSlicer/OrcaSlicer", ORCA_VENDORS),
    "crealityprint": ("CrealityOfficial/CrealityPrint", CREALITY_VENDORS),
    "bambustudio": ("bambulab/BambuStudio", ("BBL",)),
    "prusaslicer": ("prusa3d/PrusaSlicer", ("PrusaResearch",)),
    "snapmakerorca": ("Snapmaker/OrcaSlicer", ("Snapmaker",)),
}
_VERSION = re.compile(r"^v?([0-9]+(?:\.[0-9]+){1,3})$")
_ASSET_PATH = re.compile(r"^(?:[A-Za-z0-9_-]+/){0,2}[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")
_XML_SVG = "{http://www.w3.org/2000/svg}"


def _owned_profile_data(profile):
    """Read the selected user's registered and hash-checked native source."""
    if (not profile.file_asset.file or
            profile.file_asset.owner_id != profile.owner_id):
        raise SlicerProfileError("Native source file is not owned.")
    with profile.file_asset.file.open("rb") as stream:
        raw = stream.read(1024 * 1024 + 1)
    if not raw or len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != profile.content_sha256:
        raise SlicerProfileError("Native source does not match its registration.")
    if profile.engine == "prusaslicer":
        parser = ConfigParser(interpolation=None, strict=False, delimiters=("=",))
        parser.optionxform = str.lower
        try:
            parser.read_string(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, ConfigError):
            raise SlicerProfileError("Prusa vendor bundle cannot be inspected.") from None
        matches = []
        for section in parser.sections():
            if not section.startswith("printer_model:"):
                continue
            model = section.split(":", 1)[1]
            label = parser.get(section, "name", fallback=model)
            if profile.name.casefold() in (model.casefold(), label.casefold()):
                matches.append(dict(parser.items(section)))
        if len(matches) != 1:
            raise SlicerProfileError("Choose an unambiguous printer model in the Prusa vendor bundle.")
        return matches[0]
    try:
        data = _check_orca_json(raw.decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise SlicerProfileError("Native JSON is not UTF-8.") from None
    if profile.engine == "bambustudio" and data.get("type") != "machine_model":
        raise SlicerProfileError("A Bambu vendor machine-model record is required.")
    return data


@lru_cache(maxsize=64)
def _official_machine_model(source, ref, vendor, model):
    """Inspect the exact upstream model entry indexed by a versioned vendor manifest."""
    root = f"https://raw.githubusercontent.com/{source}/{ref}/resources/profiles"
    try:
        index, _ = _get_json(f"{root}/{vendor}.json", 1024 * 1024)
    except OfficialProfileError:
        return None
    records = index.get("machine_model_list")
    if not isinstance(records, list) or len(records) > 5000:
        return None
    matches = [
        row["sub_path"] for row in records
        if isinstance(row, dict) and row.get("name") == model
        and isinstance(row.get("sub_path"), str)
        and re.fullmatch(r"machine/[A-Za-z0-9_. -]+\.json", row["sub_path"])
    ]
    if len(matches) != 1:
        return None
    try:
        data, _ = _get_json(f"{root}/{vendor}/{matches[0]}", 1024 * 1024)
    except OfficialProfileError:
        return None
    if data.get("type") != "machine_model" or data.get("name") != model:
        return None
    return data


def official_asset_source(profile, kind="texture"):
    """Resolve version-aware, owner-checked profile metadata to a fixed host.

    No profile may supply a URL. Future source adapters must be explicitly
    registered and audited; newer engine versions work without a code release
    only when a registered profile has a validated version tag/provenance.
    """
    if profile.kind != "printer" or kind not in ("texture", "model"):
        return None
    provider = SOURCES.get(profile.engine)
    if provider is None:
        return None
    source, vendors = provider
    match = _VERSION.fullmatch(str(profile.engine_version or ""))
    if not match:
        return None
    version = match.group(1)
    ref = ("version_" if profile.engine == "prusaslicer" else "v") + version
    if profile.engine == "prusaslicer":
        provenance = re.fullmatch(
            re.escape(source) + "@" + re.escape(ref) +
            r"/([A-Za-z0-9_-]+)/([A-Za-z0-9_.-]+\.ini)",
            str(profile.provenance or ""),
        )
    else:
        provenance = re.fullmatch(
            re.escape(source) + "@" + re.escape(ref) +
            r"/([A-Za-z0-9_-]+)/machine/([A-Za-z0-9_. -]+\.json)",
            str(profile.provenance or ""),
        )
    if not provenance or provenance.group(1) not in vendors:
        return None
    try:
        if profile.engine == "orcaslicer":
            data = _inspect_source(profile)
        elif profile.engine == "crealityprint":
            data = json.loads(resolved_native_profile(profile))
        else:
            data = _owned_profile_data(profile)
    except (SlicerProfileError, ValueError, UnicodeDecodeError, OSError, AttributeError):
        return None
    key = "bed_texture" if kind == "texture" else "bed_model"
    filename = data.get(key)
    if not filename and data.get("inherits") and profile.engine == "orcaslicer":
        try:
            filename = json.loads(resolved_native_profile(profile)).get(key)
        except (SlicerProfileError, ValueError, UnicodeDecodeError, OSError):
            return None
    if not filename and profile.engine in ("orcaslicer", "crealityprint", "bambustudio"):
        model = data.get("printer_model")
        if isinstance(model, str) and 0 < len(model) <= 200:
            model_data = _official_machine_model(source, ref, provenance.group(1), model)
            if model_data is not None:
                filename = model_data.get(key)
    extension = ".svg" if kind == "texture" else ".stl"
    if not isinstance(filename, str) or not _ASSET_PATH.fullmatch(filename) or not filename.lower().endswith(extension):
        return None
    # No file paths, percent escapes, query strings, or user-provided hosts.
    vendor = provenance.group(1)
    url = f"https://raw.githubusercontent.com/{source}/{ref}/resources/profiles/{vendor}/{filename}"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return url, f"slicer-reviewed-native-artwork/{digest}{extension}"


def official_artwork_source(profile):
    return official_asset_source(profile, "texture")


def official_bed_model_source(profile):
    return official_asset_source(profile, "model")


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


def _verify_stl(raw):
    if not raw or len(raw) > MAX_BED_MODEL_BYTES:
        raise ValueError("Bed-model STL is empty or exceeds the size limit.")
    try:
        geometry = inspect_stl(raw)
    except MeshInspectionError:
        raise ValueError("Bed-model STL is invalid.") from None
    if geometry["triangles"] > 100000:
        raise ValueError("Bed-model STL exceeds the triangle limit.")
    return raw


def cached_official_asset(profile, kind="texture"):
    """Cache bounded official SVG/STL assets. Never fetch supplied external URLs."""
    source = official_asset_source(profile, kind)
    if source is None:
        return None
    url, name = source
    limit = MAX_ARTWORK_BYTES if kind == "texture" else MAX_BED_MODEL_BYTES
    verify = _verify_svg if kind == "texture" else _verify_stl
    if default_storage.exists(name):
        with default_storage.open(name, "rb") as stream:
            raw = stream.read(limit + 1)
        try:
            return verify(raw)
        except ValueError:
            default_storage.delete(name)
    try:
        response = requests.get(
            url, timeout=(3, 12), stream=True, allow_redirects=False,
            headers={"Accept": "image/svg+xml" if kind == "texture" else "model/stl",
                     "User-Agent": "MakerVault-BedArtwork/1"},
        )
        try:
            if response.status_code != 200:
                return None
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > limit:
                return None
            chunks = bytearray()
            for chunk in response.iter_content(32768):
                chunks.extend(chunk)
                if len(chunks) > limit:
                    return None
            raw = verify(bytes(chunks))
        finally:
            response.close()
    except (requests.RequestException, ValueError, OSError):
        return None
    default_storage.save(name, ContentFile(raw))
    return raw


def cached_official_artwork(profile):
    return cached_official_asset(profile, "texture")


def cached_official_bed_model(profile):
    return cached_official_asset(profile, "model")
