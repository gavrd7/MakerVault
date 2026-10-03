from __future__ import annotations

import hashlib
import ipaddress
import io
import re
import socket
import warnings
from urllib.parse import urljoin, urlparse

import requests
from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener


register_heif_opener()

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
MAX_IMAGE_DIMENSION = 1800
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
ALLOWED_PIL_FORMATS = {"JPEG", "MPO", "PNG", "WEBP", "HEIF", "HEIC"}


class CatalogueImageError(ValueError):
    """Raised when a catalogue image cannot be safely accepted or cached."""


def _host_is_public(host: str) -> bool:
    try:
        answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise CatalogueImageError("The image host could not be resolved.") from exc
    if not answers:
        raise CatalogueImageError("The image host did not resolve to an address.")
    for answer in answers:
        address = answer[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
    return True


def validate_public_image_url(raw_url: str) -> str:
    value = (raw_url or "").strip()
    if not value:
        raise CatalogueImageError("Enter an image URL.")
    parsed = urlparse(value)
    if parsed.scheme != "https":
        raise CatalogueImageError("Catalogue image URLs must use HTTPS.")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise CatalogueImageError("The image URL does not contain a valid host.")
    if parsed.port not in (None, 443):
        raise CatalogueImageError("Non-standard ports are not permitted for catalogue images.")
    if parsed.username or parsed.password:
        raise CatalogueImageError("Credentials in image URLs are not permitted.")
    if not _host_is_public(host):
        raise CatalogueImageError("The image URL resolved to a private or reserved address.")
    return value


def _sanitise_image(data: bytes, stem: str = "catalogue-image") -> tuple[ContentFile, str]:
    if not data:
        raise CatalogueImageError("The image was empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise CatalogueImageError("The image exceeds MakerVault's 8 MiB image limit.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
            probe = Image.open(io.BytesIO(data))
            probe.verify()
            fmt = (probe.format or "").upper()
            if fmt not in ALLOWED_PIL_FORMATS:
                raise CatalogueImageError("Only JPEG/JPG, PNG, WebP, HEIF and HEIC images are supported.")

            image = Image.open(io.BytesIO(data))
            image.load()
            image = ImageOps.exif_transpose(image)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise CatalogueImageError("The supplied file is not a safe supported image.") from exc

    if image.width * image.height > MAX_IMAGE_PIXELS:
        raise CatalogueImageError("The image dimensions are too large.")

    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    image.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.Resampling.LANCZOS)

    safe_stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", stem).strip("-._")[:80] or "catalogue-image"
    digest = hashlib.sha256(data).hexdigest()[:12]
    filename = f"{safe_stem}-{digest}.webp"
    output = io.BytesIO()
    if image.mode == "RGBA":
        image.save(output, format="WEBP", quality=88, method=6, lossless=True)
    else:
        image.save(output, format="WEBP", quality=88, method=6)
    return ContentFile(output.getvalue()), filename


def sanitise_uploaded_image(uploaded_file, stem: str) -> tuple[ContentFile, str]:
    if getattr(uploaded_file, "size", 0) > MAX_IMAGE_BYTES:
        raise CatalogueImageError("The image exceeds MakerVault's 8 MiB image limit.")
    data = uploaded_file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise CatalogueImageError("The image exceeds MakerVault's 8 MiB image limit.")
    return _sanitise_image(data, stem)


def fetch_public_image(raw_url: str, stem: str) -> tuple[ContentFile, str, str]:
    current = validate_public_image_url(raw_url)
    headers = {
        "User-Agent": "MakerVault/0.2.1 (+self-hosted catalogue image cache)",
        "Accept": "image/webp,image/png,image/jpeg;q=0.9,*/*;q=0.2",
    }

    for _ in range(5):
        safe_url = validate_public_image_url(current)
        try:
            response = requests.get(
                safe_url,
                headers=headers,
                timeout=(5, 20),
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as exc:
            raise CatalogueImageError("MakerVault could not retrieve that image.") from exc

        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise CatalogueImageError("The image source returned an invalid redirect.")
            current = urljoin(safe_url, location)
            continue

        if response.status_code != 200:
            response.close()
            raise CatalogueImageError(f"The image source returned HTTP {response.status_code}.")

        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type not in ALLOWED_CONTENT_TYPES:
            response.close()
            raise CatalogueImageError("The URL did not return a supported JPEG/JPG, PNG, WebP, HEIF or HEIC image.")

        declared = response.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > MAX_IMAGE_BYTES:
            response.close()
            raise CatalogueImageError("The image exceeds MakerVault's 8 MiB image limit.")

        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_IMAGE_BYTES:
                response.close()
                raise CatalogueImageError("The image exceeds MakerVault's 8 MiB image limit.")
            chunks.append(chunk)
        response.close()
        content, filename = _sanitise_image(b"".join(chunks), stem)
        return content, filename, safe_url

    raise CatalogueImageError("The image source redirected too many times.")


def catalogue_image_metadata(obj, variant: str = "base") -> tuple[dict, str]:
    """Return mutable image provenance metadata and its model field."""
    if variant == "multi_material" and hasattr(obj, "image_multi_material_metadata"):
        return (
            dict(getattr(obj, "image_multi_material_metadata", {}) or {}),
            "image_multi_material_metadata",
        )
    if hasattr(obj, "specifications"):
        return dict(getattr(obj, "specifications", {}) or {}), "specifications"
    if hasattr(obj, "image_metadata"):
        return dict(getattr(obj, "image_metadata", {}) or {}), "image_metadata"
    return {}, ""


def set_catalogue_image_metadata(obj, metadata: dict, variant: str = "base"):
    _, field = catalogue_image_metadata(obj, variant=variant)
    if field:
        setattr(obj, field, metadata)
    return field


def apply_catalogue_image(
    obj,
    content: ContentFile,
    filename: str,
    source_url: str = "",
    source_type: str = "upload",
    variant: str = "base",
):
    image_field = "image_multi_material" if variant == "multi_material" else "image"
    image = getattr(obj, image_field)
    if image:
        try:
            image.delete(save=False)
        except OSError:
            pass
    getattr(obj, image_field).save(filename, content, save=False)
    metadata, _ = catalogue_image_metadata(obj, variant=variant)
    metadata["image_source_type"] = source_type
    if source_url:
        metadata["image_source_url"] = source_url
        metadata["external_image_url"] = source_url
    elif source_type == "upload":
        metadata.pop("external_image_url", None)
        metadata.pop("image_source_url", None)
    metadata["image_cached_at"] = timezone.now().isoformat()
    set_catalogue_image_metadata(obj, metadata, variant=variant)
    obj.save()
    return obj


def cache_catalogue_image_from_url(obj, raw_url: str):
    stem = getattr(obj, "slug", "") or getattr(obj, "name", "") or str(obj.pk)
    content, filename, final_url = fetch_public_image(raw_url, stem)
    return apply_catalogue_image(obj, content, filename, final_url, "remote")
