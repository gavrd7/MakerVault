from __future__ import annotations

import io
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from django.core.cache import cache
from django.utils import timezone
from pypdf import PdfReader

from .importers import _host_is_public
from .model_values import fit_model_decimal


MAX_TECHNICAL_BYTES = 12 * 1024 * 1024
CACHE_SECONDS = 24 * 60 * 60
TECHNICAL_FIELDS = (
    "density_g_cm3",
    "nozzle_temp_min_c",
    "nozzle_temp_max_c",
    "bed_temp_min_c",
    "bed_temp_max_c",
    "drying_temp_c",
    "drying_time_hours",
)


class FilamentTechnicalSourceError(ValueError):
    """Raised when a trusted catalogue-linked technical source cannot be read safely."""


def _validate_source_url(raw_url: str) -> str:
    value = str(raw_url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme != "https":
        raise FilamentTechnicalSourceError("Filament technical sources must use HTTPS.")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or parsed.port not in (None, 443) or parsed.username or parsed.password:
        raise FilamentTechnicalSourceError("The filament technical source URL is not supported.")
    if not _host_is_public(host):
        raise FilamentTechnicalSourceError("The filament technical source resolved to a private or reserved address.")
    return value


def _fetch_source_bytes(raw_url: str) -> tuple[str, bytes, str]:
    current = _validate_source_url(raw_url)
    headers = {
        "User-Agent": "MakerVault/1.0 (+self-hosted filament technical enrichment)",
        "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.5",
        "Accept-Language": "en-GB,en;q=0.9",
    }
    for _ in range(5):
        current = _validate_source_url(current)
        try:
            response = requests.get(
                current,
                headers=headers,
                timeout=(5, 20),
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as exc:
            raise FilamentTechnicalSourceError("MakerVault could not retrieve the filament technical source.") from exc

        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise FilamentTechnicalSourceError("The filament technical source returned an invalid redirect.")
            current = urljoin(current, location)
            continue

        if response.status_code != 200:
            status = response.status_code
            response.close()
            raise FilamentTechnicalSourceError(f"The filament technical source returned HTTP {status}.")

        declared = response.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > MAX_TECHNICAL_BYTES:
            response.close()
            raise FilamentTechnicalSourceError("The filament technical source is larger than MakerVault's safety limit.")

        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_TECHNICAL_BYTES:
                response.close()
                raise FilamentTechnicalSourceError("The filament technical source is larger than MakerVault's safety limit.")
            chunks.append(chunk)
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        response.close()
        return current, b"".join(chunks), content_type
    raise FilamentTechnicalSourceError("The filament technical source redirected too many times.")


def _number(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _temperature_range(text: str, labels: str):
    # Keep the match close to the label so unrelated mechanical/thermal values
    # elsewhere in a TDS cannot be mistaken for print settings.
    pattern = re.compile(
        rf"(?:{labels})\s*(?:temperature|temp)?[^0-9]{{0,48}}"
        rf"(\d{{2,3}}(?:\.\d+)?)\s*(?:°?\s*c)?"
        rf"(?:\s*(?:-|–|—|~|to|/|;)+\s*(\d{{2,3}}(?:\.\d+)?)\s*(?:°?\s*c)?)?",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return None, None
    first = _number(match.group(1))
    second = _number(match.group(2)) if match.group(2) else first
    if first is None or second is None:
        return None, None
    low, high = sorted((int(round(float(first))), int(round(float(second)))))
    if not (20 <= low <= 400 and 20 <= high <= 400):
        return None, None
    return low, high


def parse_filament_technical_text(text: str) -> dict:
    flat = re.sub(r"\s+", " ", str(text or "")).strip()
    if not flat:
        return {}

    nozzle_min, nozzle_max = _temperature_range(
        flat,
        r"extruder|nozzle|printing\s+temperature|print\s+temperature",
    )
    bed_min, bed_max = _temperature_range(
        flat,
        r"bed|build\s+platform|build\s+plate|hotbed",
    )

    density = None
    density_match = re.search(
        r"density\s*(?:\([^)]*\))?[^0-9]{0,32}(\d(?:\.\d{1,4})?)\s*(?:g\s*/\s*cm(?:3|³))?",
        flat,
        re.IGNORECASE,
    )
    if density_match:
        candidate = _number(density_match.group(1))
        if candidate is not None and Decimal("0.5") <= candidate <= Decimal("3.0"):
            density = candidate

    drying_temp = None
    drying_time = None
    drying_block = re.search(
        r"(?:drying(?:\s+(?:settings?|recommendations?|condition))?|dry\s+at)[^.;]{0,140}",
        flat,
        re.IGNORECASE,
    )
    if drying_block:
        block = drying_block.group(0)
        temp_match = re.search(r"(\d{2,3})\s*°?\s*c", block, re.IGNORECASE)
        time_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hours?)\b", block, re.IGNORECASE)
        if temp_match:
            value = int(temp_match.group(1))
            if 20 <= value <= 150:
                drying_temp = value
        if time_match:
            value = _number(time_match.group(1))
            if value is not None and Decimal("0.25") <= value <= Decimal("72"):
                drying_time = value

    result = {
        "density_g_cm3": density,
        "nozzle_temp_min_c": nozzle_min,
        "nozzle_temp_max_c": nozzle_max,
        "bed_temp_min_c": bed_min,
        "bed_temp_max_c": bed_max,
        "drying_temp_c": drying_temp,
        "drying_time_hours": drying_time,
    }
    return {key: value for key, value in result.items() if value is not None}


def _pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
    except Exception as exc:
        raise FilamentTechnicalSourceError("The filament data sheet could not be parsed.") from exc
    pages = []
    for page in reader.pages[:30]:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(pages)


def fetch_filament_technical_source(raw_url: str) -> tuple[str, dict]:
    key = "makervault:filament-technical:" + __import__("hashlib").sha256(str(raw_url).encode("utf-8")).hexdigest()[:24]
    cached = cache.get(key)
    if isinstance(cached, dict):
        return str(cached.get("url") or raw_url), dict(cached.get("data") or {})

    final_url, payload, content_type = _fetch_source_bytes(raw_url)
    is_pdf = content_type == "application/pdf" or payload[:5] == b"%PDF-"
    if is_pdf:
        text = _pdf_text(payload)
    elif content_type in {"text/html", "application/xhtml+xml", ""}:
        text = BeautifulSoup(payload.decode("utf-8", errors="replace"), "html.parser").get_text(" ", strip=True)
    else:
        raise FilamentTechnicalSourceError("The filament technical source was not HTML or PDF.")

    data = parse_filament_technical_text(text)
    cache.set(key, {"url": final_url, "data": data}, CACHE_SECONDS)
    return final_url, data


def _source_priority(kind: str) -> int:
    return {"tds": 10, "product": 20}.get(kind, 90)


def enrich_filament_from_authoritative_sources(filament, upstream_row: dict) -> dict:
    profile = dict(filament.profile_data or {})
    field_sources = dict(profile.get("technical_field_sources") or {})
    trace = list(profile.get("technical_source_trace") or [])
    manufacturer = (
        filament.filament_manufacturer.name
        if filament.filament_manufacturer_id
        else filament.manufacturer.name if filament.manufacturer_id else upstream_row.get("manufacturer") or "Manufacturer"
    )

    candidates = []
    for kind, url in (
        ("tds", upstream_row.get("tds_url")),
        ("product", upstream_row.get("product_url")),
    ):
        value = str(url or "").strip()
        if value and value not in [row[1] for row in candidates]:
            candidates.append((kind, value))

    changed_fields = []
    checked = 0
    errors = 0
    for kind, url in candidates:
        checked += 1
        try:
            final_url, parsed = fetch_filament_technical_source(url)
        except FilamentTechnicalSourceError as exc:
            errors += 1
            trace.append({
                "provider": manufacturer,
                "kind": kind,
                "url": url,
                "result": "error",
                "error": str(exc)[:240],
                "checked_at": timezone.now().isoformat(),
            })
            continue

        applied = []
        incoming_priority = _source_priority(kind)
        for field in TECHNICAL_FIELDS:
            incoming = parsed.get(field)
            if incoming is None:
                continue
            current = getattr(filament, field)
            source_info = field_sources.get(field) if isinstance(field_sources.get(field), dict) else {}
            current_priority = int(source_info.get("priority", 100))
            upstream_value = upstream_row.get(field)
            looks_upstream = (
                filament.source_id
                and getattr(filament.source, "source_type", "") == "spoolmandb"
                and upstream_value is not None
                and str(current) == str(upstream_value)
            )
            user_owned = bool(source_info.get("source") == "user")
            may_replace = (
                current in (None, "")
                or (not user_owned and incoming_priority < current_priority)
                or (not user_owned and not source_info and looks_upstream)
            )
            if not may_replace:
                continue
            setattr(filament, field, fit_model_decimal(filament, field, incoming))
            field_sources[field] = {
                "source": "manufacturer",
                "provider": manufacturer,
                "kind": kind,
                "url": final_url,
                "priority": incoming_priority,
                "checked_at": timezone.now().isoformat(),
            }
            applied.append(field)
            changed_fields.append(field)

        trace.append({
            "provider": manufacturer,
            "kind": kind,
            "url": final_url,
            "result": "applied" if applied else ("read-no-values" if not parsed else "checked-no-change"),
            "fields": applied,
            "checked_at": timezone.now().isoformat(),
        })

    profile["technical_field_sources"] = field_sources
    profile["technical_source_trace"] = trace[-24:]
    profile["technical_last_checked_at"] = timezone.now().isoformat()
    filament.profile_data = profile
    if changed_fields or candidates:
        filament.save(update_fields=list(dict.fromkeys(changed_fields + ["profile_data", "updated_at"])))

    return {
        "checked_sources": checked,
        "changed_fields": sorted(set(changed_fields)),
        "errors": errors,
    }
