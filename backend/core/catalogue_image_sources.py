from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.text import slugify

from .catalogue_source_policy import (
    append_source_trace,
    classify_source_url,
    ordered_source_candidates,
)
from .catalogue_images import (
    CatalogueImageError,
    apply_catalogue_image,
    catalogue_image_metadata,
    fetch_public_image,
    set_catalogue_image_metadata,
)
from .importers import ImporterError, fetch_import_html


COMMONS_API = "https://commons.wikimedia.org/w/api.php"
OPENVERSE_API = "https://api.openverse.org/v1/images/"
IMAGE_SEED_VERSION = "0.7.1-board-component-sources-1"
USER_AGENT = f"MakerVault/{getattr(settings, 'MAKERVAULT_VERSION', 'dev')} (+self-hosted catalogue image seeder)"
def _commons_license_allowed(license_name: str) -> bool:
    """Allow only licences suitable for normal open redistribution."""
    value = " ".join((license_name or "").strip().upper().split())
    if not value:
        return False
    if "NC" in value or "ND" in value:
        return False
    if value.startswith("CC0") or value.startswith("PUBLIC DOMAIN") or value.startswith("PDM"):
        return True
    return value == "CC BY" or value.startswith("CC BY ") or value == "CC BY-SA" or value.startswith("CC BY-SA ")


OPENVERSE_LICENSES = {
    "cc0": "CC0",
    "pdm": "Public Domain",
    "by": "CC BY",
    "by-sa": "CC BY-SA",
}


def _openverse_license_name(code: str, version: str = "") -> str:
    base = OPENVERSE_LICENSES.get((code or "").strip().lower(), "")
    if not base:
        return ""
    version = (version or "").strip()
    return f"{base} {version}".strip()


GENERIC_COMPONENT_QUERY_BY_TYPE = {
    "resistor": "electronic resistor component",
    "capacitor": "electrolytic capacitor electronic component",
    "diode": "electronic diode component",
    "transistor": "transistor electronic component",
    "mosfet": "MOSFET transistor electronic component",
    "optocoupler": "optocoupler electronic component",
    "regulator": "voltage regulator electronic component",
    "led": "LED electronic component",
    "rgb-led": "RGB LED electronic component",
    "addressable-led": "WS2812 LED",
    "led-ring": "NeoPixel LED ring",
    "led-matrix": "LED matrix module",
    "led-strip": "addressable LED strip",
    "breadboard": "solderless breadboard electronics",
    "perfboard": "perfboard electronics",
    "header": "pin header electronics",
    "jumper-wire": "Dupont jumper wires",
    "connector": "electrical connector electronics",
    "terminal-block": "terminal block connector",
    "power-connector": "DC power connector electronics",
    "button": "tactile push button electronics",
    "switch": "toggle switch electronics",
    "potentiometer": "potentiometer electronic component",
    "rotary-encoder": "rotary encoder electronic component",
    "joystick": "joystick module Arduino",
    "fan": "40mm computer fan",
    "magnet": "neodymium magnets",
    "fastener": "machine screws assortment",
    "heat-set-insert": "heat set threaded inserts",
    "speaker": "small loudspeaker electronic component",
    "buzzer": "piezo buzzer electronic component",
    "load-cell": "load cell sensor",
}


@dataclass
class ImageCandidate:
    image_url: str
    source_page_url: str
    provider: str
    license_name: str = ""
    author: str = ""
    query: str = ""


def _plain_html(value: str) -> str:
    return BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)


def _normalise_tokens(value: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (value or "").lower())
    stop = {
        "board", "module", "sensor", "electronic", "component", "generic", "style",
        "mini", "development", "dev", "the", "and", "with", "for", "of",
    }
    return {word for word in words if len(word) > 1 and word not in stop}


def _title_score(title: str, query: str) -> float:
    wanted = _normalise_tokens(query)
    found = _normalise_tokens(title.replace("File:", ""))
    if not wanted:
        return 0.0
    overlap = wanted & found
    return len(overlap) / len(wanted)


def _commons_query_for_component(component) -> str:
    specs = component.specifications or {}
    part = (component.part_number or "").strip()
    if part:
        return f"{part} {component.name}"
    item_type = str(specs.get("type") or "").strip()
    return GENERIC_COMPONENT_QUERY_BY_TYPE.get(item_type, component.name)


def _commons_query_for_board(board) -> str:
    maker = board.manufacturer.name if board.manufacturer else ""
    return f"{maker} {board.name} microcontroller board".strip()


def _printer_image_queries(printer_model) -> list[str]:
    maker = re.sub(r"\s+", " ", printer_model.manufacturer.name if printer_model.manufacturer else "").strip()
    name = re.sub(r"\s+", " ", printer_model.name or "").strip()
    # Exact manufacturer + model terms are intentionally first. Generic words
    # such as "3D printer" dilute the token score for short model names (K2,
    # M5, A1, etc.) and previously caused good open-media results to miss the
    # confidence threshold.
    queries = [
        f"{maker} {name}".strip(),
        f"{maker} {name} 3D printer".strip(),
        f"{maker} {name} printer".strip(),
    ]
    # Orca/manual imports occasionally retain bracketed variant suffixes. A
    # stripped fallback helps find the underlying product without accepting a
    # different manufacturer.
    stripped = re.sub(r"\s*[\[(][^\])]*[\])]\s*$", "", name).strip()
    if stripped and stripped != name:
        queries.append(f"{maker} {stripped}".strip())
    out = []
    for query in queries:
        query = re.sub(r"\s+", " ", query).strip()
        if query and query not in out:
            out.append(query)
    return out[:4]


def _printer_multi_material_image_queries(printer_model) -> list[str]:
    maker = printer_model.manufacturer.name if printer_model.manufacturer else ""
    name = re.sub(r"\s+", " ", printer_model.name or "").strip()
    system_label = dict(printer_model.MULTI_MATERIAL_SYSTEMS).get(
        printer_model.multi_material_system,
        printer_model.multi_material_system,
    )
    queries = [
        f"{maker} {name} Combo 3D printer".strip(),
        f"{maker} {name} {system_label} 3D printer".strip(),
        f"{maker} {name} with {system_label}".strip(),
    ]
    out = []
    for query in queries:
        query = re.sub(r"\s+", " ", query).strip()
        if query and query not in out:
            out.append(query)
    return out


def search_wikimedia_commons(query: str, *, minimum_score: float = 0.18) -> ImageCandidate | None:
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": 6,
        "gsrlimit": 10,
        "prop": "imageinfo",
        "iiprop": "url|mime|extmetadata",
        "iiurlwidth": 1400,
    }
    try:
        response = requests.get(
            COMMONS_API,
            params=params,
            timeout=(5, 20),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return None

    ranked = []
    for page in payload.get("query", {}).get("pages", []):
        info_list = page.get("imageinfo") or []
        if not info_list:
            continue
        info = info_list[0]
        if info.get("mime") not in {"image/jpeg", "image/png", "image/webp"}:
            continue
        metadata = info.get("extmetadata") or {}
        license_name = _plain_html((metadata.get("LicenseShortName") or {}).get("value", ""))
        if not _commons_license_allowed(license_name):
            continue
        image_url = info.get("thumburl") or info.get("url")
        source_page = info.get("descriptionurl") or ""
        if not image_url or not source_page:
            continue
        author = _plain_html((metadata.get("Artist") or {}).get("value", ""))
        title = page.get("title", "")
        score = _title_score(title, query)
        ranked.append((score, title, ImageCandidate(
            image_url=image_url,
            source_page_url=source_page,
            provider="Wikimedia Commons",
            license_name=license_name,
            author=author[:500],
            query=query,
        )))

    if not ranked:
        return None
    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    best_score, _, candidate = ranked[0]
    if best_score < minimum_score:
        return None
    return candidate


def search_openverse(query: str, *, minimum_score: float = 0.18) -> ImageCandidate | None:
    """Search Openverse for a confidently matching, openly licensed image."""
    try:
        response = requests.get(
            OPENVERSE_API,
            params={"q": query, "page_size": 20},
            timeout=(5, 20),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return None

    ranked = []
    for item in payload.get("results", []):
        license_name = _openverse_license_name(
            str(item.get("license") or ""),
            str(item.get("license_version") or ""),
        )
        if not license_name:
            continue
        image_url = item.get("thumbnail") or item.get("url") or ""
        source_page = item.get("foreign_landing_url") or item.get("detail_url") or ""
        if not image_url or not source_page:
            continue
        title = str(item.get("title") or "")
        score = _title_score(title, query)
        if not score:
            tags = " ".join(
                str(tag.get("name") or "")
                for tag in (item.get("tags") or [])
                if isinstance(tag, dict)
            )
            score = _title_score(tags, query) * 0.75
        provider = str(item.get("source") or item.get("provider") or "Openverse")
        creator = str(item.get("creator") or "")[:500]
        ranked.append((score, title, ImageCandidate(
            image_url=image_url,
            source_page_url=source_page,
            provider=f"Openverse / {provider}",
            license_name=license_name,
            author=creator,
            query=query,
        )))

    if not ranked:
        return None
    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    best_score, _, candidate = ranked[0]
    if best_score < minimum_score:
        return None
    return candidate


def _board_image_queries(board) -> list[str]:
    maker = board.manufacturer.name if board.manufacturer else ""
    name = re.sub(r"\s+", " ", (board.name or "").replace(" style", "")).strip()
    queries = []
    if maker and maker.lower() != "generic":
        queries.append(f"{maker} {name}")
    queries.append(name)
    if board.mcu and _normalise_tokens(board.mcu) - _normalise_tokens(name):
        queries.append(f"{board.mcu} {name}")
    out = []
    for query in queries:
        query = query.strip()
        if query and query not in out:
            out.append(query)
    return out[:3]


def _component_image_queries(component) -> list[str]:
    specs = component.specifications or {}
    part = (component.part_number or "").strip()
    item_type = str(specs.get("type") or "").strip().lower()
    name = re.sub(r"\s+", " ", component.name or "").strip()
    name_lower = name.lower()
    queries = []

    # Preserve shape/form-factor words early: these are often more important
    # than the electrical value for visually generic components.
    if "slide potentiometer" in name_lower or "slider potentiometer" in name_lower:
        queries.extend([name, f"{name} linear slider", "slide potentiometer electronics"])
    elif "trimmer" in name_lower:
        queries.extend([name, "trimmer potentiometer electronics"])
    elif "rotary encoder" in name_lower:
        queries.extend([name, "rotary encoder module"])
    elif "reed switch" in name_lower:
        queries.extend([name, "magnetic reed switch electronics"])
    elif "tactile" in name_lower and "button" in name_lower:
        queries.extend([name, "tactile push button electronics"])
    elif "relay module" in name_lower:
        queries.extend([name, f"{part} relay module".strip()])
    else:
        if part:
            if item_type not in {"resistor", "capacitor", "diode", "transistor", "mosfet", "regulator"}:
                queries.append(f"{part} module")
            queries.append(part)
        queries.append(name)

    fallback = GENERIC_COMPONENT_QUERY_BY_TYPE.get(item_type)
    if fallback:
        queries.append(fallback)

    out = []
    for query in queries:
        query = re.sub(r"\s+", " ", query).strip()
        if query and query not in out:
            out.append(query)
    return out[:5]


def _search_open_media_with_diagnostics(
    queries: list[str],
    *,
    minimum_score: float = 0.16,
) -> tuple[ImageCandidate | None, dict]:
    attempts = []
    for query in queries:
        if settings.CATALOGUE_IMAGE_WIKIMEDIA:
            candidate = search_wikimedia_commons(query, minimum_score=minimum_score)
            attempts.append({"provider": "Wikimedia Commons", "query": query, "matched": bool(candidate)})
            if candidate:
                return candidate, {"attempts": attempts, "provider": candidate.provider, "query": candidate.query}
        if getattr(settings, "CATALOGUE_IMAGE_OPENVERSE", True):
            candidate = search_openverse(query, minimum_score=minimum_score)
            attempts.append({"provider": "Openverse", "query": query, "matched": bool(candidate)})
            if candidate:
                return candidate, {"attempts": attempts, "provider": candidate.provider, "query": candidate.query}
    return None, {"attempts": attempts, "provider": "", "query": ""}


def _search_open_media(queries: list[str], *, minimum_score: float = 0.16) -> ImageCandidate | None:
    candidate, _ = _search_open_media_with_diagnostics(
        queries,
        minimum_score=minimum_score,
    )
    return candidate


def _espboards_slug_candidates(board) -> list[str]:
    name = board.name
    manufacturer = board.manufacturer.name if board.manufacturer else ""
    variants = [name]
    if manufacturer and name.lower().startswith(manufacturer.lower() + " "):
        variants.append(name[len(manufacturer):].strip())
    variants.append(re.sub(r"\([^)]*\)", "", name).strip())
    # Common naming differences on ESPBoards.
    variants.append(name.replace("Seeed Studio ", ""))
    variants.append(name.replace("Adafruit ", ""))

    slugs = []
    for variant in variants:
        slug = slugify(variant)
        if slug and slug not in slugs:
            slugs.append(slug)
    return slugs[:5]


def find_espboards_image(board) -> ImageCandidate | None:
    family_text = " ".join([board.family or "", board.mcu or "", board.name or ""]).upper()
    if "ESP32" not in family_text:
        return None

    wanted = _normalise_tokens(f"{board.manufacturer.name if board.manufacturer else ''} {board.name}")
    for slug in _espboards_slug_candidates(board):
        page_url = f"https://www.espboards.dev/esp32/{quote(slug)}/"
        try:
            final_url, html = fetch_import_html(page_url)
        except ImporterError:
            continue
        soup = BeautifulSoup(html, "html.parser")
        heading = soup.find("h1")
        if not heading:
            continue
        heading_text = " ".join(heading.stripped_strings)
        found = _normalise_tokens(heading_text)
        if wanted and len(wanted & found) / len(wanted) < 0.45:
            continue
        og_image = soup.find("meta", attrs={"property": "og:image"})
        image_url = (og_image.get("content") or "").strip() if og_image else ""
        if not image_url:
            continue
        if image_url.startswith("/"):
            image_url = f"https://www.espboards.dev{image_url}"
        return ImageCandidate(
            image_url=image_url,
            source_page_url=final_url,
            provider="ESPBoards.dev",
            license_name="CC BY-NC 4.0",
            author="espboards.dev",
            query=board.name,
        )
    return None


def _candidate_source_pages(obj) -> list[dict]:
    specs = getattr(obj, "specifications", None) or {}
    candidates = []
    seen = set()
    for key in (
        "reference_url",
        "technical_source_url",
        "product_url",
        "datasheet_url",
        "pinout_url",
    ):
        value = str(specs.get(key) or "").strip()
        if value.startswith("https://") and not value.lower().endswith(".pdf") and value not in seen:
            candidates.append({
                "url": value,
                "source_type": "",
                "provider": str(specs.get("reference_provider") or "").strip(),
            })
            seen.add(value)

    source = getattr(obj, "source", None)
    source_url = str(getattr(source, "url", "") or "").strip()
    if source_url.startswith("https://") and not source_url.lower().endswith(".pdf") and source_url not in seen:
        candidates.append({
            "url": source_url,
            "source_type": str(getattr(source, "source_type", "") or ""),
            "provider": str(getattr(source, "name", "") or ""),
        })

    return ordered_source_candidates(candidates)[:6]


def find_source_page_image(obj) -> dict | None:
    """Find a remote product image from an already-known catalogue source page.

    These images are referenced remotely rather than cached because MakerVault
    does not assume redistribution rights merely because a source page exposes
    an OpenGraph image.
    """
    for source in _candidate_source_pages(obj):
        page_url = source["url"]
        try:
            final_url, html = fetch_import_html(page_url)
        except ImporterError:
            continue
        soup = BeautifulSoup(html, "html.parser")
        image_url = ""
        for attrs in (
            {"property": "og:image"},
            {"name": "twitter:image"},
            {"property": "twitter:image"},
        ):
            tag = soup.find("meta", attrs=attrs)
            if tag and str(tag.get("content") or "").strip():
                image_url = str(tag.get("content") or "").strip()
                break
        if not image_url:
            continue
        image_url = urljoin(final_url, image_url)
        parsed = urlparse(image_url)
        if parsed.scheme != "https" or not parsed.netloc:
            continue
        tier = classify_source_url(final_url, source_type=source.get("source_type", ""))
        return {
            "external_image_url": image_url,
            "image_source_page": final_url,
            "image_source_provider": source.get("provider") or urlparse(final_url).netloc.removeprefix("www."),
            "image_source_type": "source-page-remote",
            "image_source_tier": tier.key,
            "image_source_priority": tier.priority,
            "image_license": "",
            "image_author": "",
        }
    return None


def resolve_catalogue_image(obj, variant: str = "base") -> ImageCandidate | None:
    from .models import BoardModel, ComponentModel, PrinterCatalogModel

    if isinstance(obj, BoardModel):
        if settings.CATALOGUE_IMAGE_PREFER_ESPBOARDS:
            candidate = find_espboards_image(obj)
            if candidate:
                return candidate
        return _search_open_media(_board_image_queries(obj), minimum_score=0.16)

    if isinstance(obj, ComponentModel):
        queries = _component_image_queries(obj)
        candidate = _search_open_media(queries[:3], minimum_score=0.16)
        if candidate:
            return candidate
        if len(queries) > 3:
            return _search_open_media(queries[3:], minimum_score=0.12)

    if isinstance(obj, PrinterCatalogModel):
        if variant == "multi_material":
            if not obj.multi_material_system:
                return None
            return _search_open_media(
                _printer_multi_material_image_queries(obj),
                minimum_score=0.50,
            )
        return _search_open_media(_printer_image_queries(obj), minimum_score=0.45)
    return None


def cache_candidate(obj, candidate: ImageCandidate, variant: str = "base"):
    suffix = "-combo" if variant == "multi_material" else ""
    stem = (getattr(obj, "slug", "") or getattr(obj, "name", "") or str(obj.pk)) + suffix
    content, filename, final_image_url = fetch_public_image(candidate.image_url, stem)
    apply_catalogue_image(
        obj,
        content,
        filename,
        source_url=final_image_url,
        source_type=f"auto-{candidate.provider.lower().replace(' ', '-').replace('.', '')}",
        variant=variant,
    )
    metadata, _ = catalogue_image_metadata(obj, variant=variant)
    metadata.update({
        "image_source_provider": candidate.provider,
        "image_source_page": candidate.source_page_url,
        "image_source_query": candidate.query,
        "image_license": candidate.license_name,
        "image_author": candidate.author,
        "auto_image_seeded": True,
        "auto_image_seeded_at": timezone.now().isoformat(),
        "image_variant": variant,
    })
    field = set_catalogue_image_metadata(obj, metadata, variant=variant)
    obj.save(update_fields=[field, "updated_at"] if field else ["updated_at"])


def _recent_attempt(specs: dict, retry_days: int) -> bool:
    # A new image-search generation gets one fresh attempt even if the previous
    # release tried the record recently.
    if specs.get("auto_image_attempt_version") != IMAGE_SEED_VERSION:
        return False
    raw = specs.get("auto_image_last_attempt")
    if not raw:
        return False
    try:
        attempted = datetime.fromisoformat(raw)
        if timezone.is_naive(attempted):
            attempted = timezone.make_aware(attempted)
    except (TypeError, ValueError):
        return False
    return attempted >= timezone.now() - timedelta(days=retry_days)


def run_catalogue_image_seed(
    *,
    limit: int | None = None,
    force_retry: bool = False,
    kinds: list[str] | tuple[str, ...] | None = None,
) -> dict:
    from .models import BoardModel, ComponentModel, PrinterCatalogModel

    limit = settings.CATALOGUE_IMAGE_MAX_PER_RUN if limit is None else max(int(limit), 0)
    retry_days = max(int(settings.CATALOGUE_IMAGE_RETRY_DAYS), 1)
    allowed_kinds = {"printers", "boards", "components"}
    requested = [str(item).strip().lower() for item in (kinds or []) if str(item).strip()]
    invalid = [item for item in requested if item not in allowed_kinds]
    if invalid:
        raise ValueError(f"Unknown catalogue image kind(s): {', '.join(sorted(set(invalid)))}")

    lock_key = f"makervault:catalogue-image-seed:{IMAGE_SEED_VERSION}"
    if not cache.add(lock_key, "running", timeout=60 * 60):
        return {
            "status": "already-running",
            "processed": 0,
            "cached": 0,
            "failed": 0,
            "skipped": 0,
            "by_kind": {},
            "by_provider": {},
            "remote": 0,
            "failures": [],
        }

    def missing_ratio(queryset, image_field="image"):
        total = queryset.count()
        if not total:
            return 0.0
        missing = queryset.filter(**{f"{image_field}__isnull": True}).count()
        # ImageField blank values can be stored as an empty string rather than
        # SQL NULL, so include them in the live priority calculation.
        missing += queryset.filter(**{image_field: ""}).count()
        return missing / total

    boards = BoardModel.objects.select_related("manufacturer", "source").order_by("manufacturer__name", "name")
    components = ComponentModel.objects.select_related("category", "source").order_by("category__name", "name")
    printers = PrinterCatalogModel.objects.select_related("manufacturer").order_by("manufacturer__name", "name")

    sources = {
        "boards": boards,
        "components": components,
        "printers": printers,
    }
    if requested:
        order = requested
    else:
        # Work on the least-complete catalogue first so a per-run cap cannot
        # indefinitely starve the largest gap.
        order = sorted(
            sources,
            key=lambda key: missing_ratio(sources[key]),
            reverse=True,
        )

    processed = cached = failed = skipped = remote = 0
    by_kind = {
        key: {"processed": 0, "cached": 0, "remote": 0, "failed": 0, "skipped": 0}
        for key in order
    }
    by_provider = {}
    failures = []

    try:
        for kind in order:
            queryset = sources[kind]
            for obj in queryset.iterator():
                variants = ["base"]
                if isinstance(obj, PrinterCatalogModel) and obj.multi_material_system:
                    variants.append("multi_material")

                for variant in variants:
                    if limit and processed >= limit:
                        return {
                            "status": "limit-reached",
                            "processed": processed,
                            "cached": cached,
                            "failed": failed,
                            "skipped": skipped,
                            "by_kind": by_kind,
                            "by_provider": by_provider,
                            "remote": remote,
                            "failures": failures,
                            "order": order,
                        }

                    image_field = "image_multi_material" if variant == "multi_material" else "image"
                    metadata, _ = catalogue_image_metadata(obj, variant=variant)
                    if getattr(obj, image_field, None) or (
                        variant == "base" and str(metadata.get("external_image_url") or "").startswith("https://")
                    ):
                        skipped += 1
                        by_kind[kind]["skipped"] += 1
                        continue

                    if metadata.get("auto_image_opt_out"):
                        skipped += 1
                        by_kind[kind]["skipped"] += 1
                        continue
                    if not force_retry and _recent_attempt(metadata, retry_days):
                        skipped += 1
                        by_kind[kind]["skipped"] += 1
                        continue

                    processed += 1
                    by_kind[kind]["processed"] += 1
                    metadata["auto_image_last_attempt"] = timezone.now().isoformat()
                    metadata["auto_image_attempt_version"] = IMAGE_SEED_VERSION
                    metadata["image_variant"] = variant

                    source_fallback = None
                    try:
                        if isinstance(obj, PrinterCatalogModel):
                            queries = (
                                _printer_multi_material_image_queries(obj)
                                if variant == "multi_material"
                                else _printer_image_queries(obj)
                            )
                            threshold = 0.50 if variant == "multi_material" else 0.45
                            candidate, diagnostic = _search_open_media_with_diagnostics(
                                queries,
                                minimum_score=threshold,
                            )
                            metadata["auto_image_search_attempts"] = diagnostic.get("attempts", [])[-12:]
                        else:
                            source_fallback = find_source_page_image(obj) if variant == "base" else None
                            # Manufacturer, specialist and maintained ecosystem
                            # source pages outrank generic open-media discovery.
                            if source_fallback and int(source_fallback.get("image_source_priority", 999)) < 50:
                                metadata.update(source_fallback)
                                metadata = append_source_trace(
                                    metadata,
                                    provider=source_fallback.get("image_source_provider", ""),
                                    url=source_fallback.get("image_source_page", ""),
                                    tier=source_fallback.get("image_source_tier", "generic"),
                                    result="selected-remote-image",
                                )
                                metadata["auto_image_last_result"] = "remote-source-selected"
                                field = set_catalogue_image_metadata(obj, metadata, variant=variant)
                                obj.save(update_fields=[field, "updated_at"] if field else ["updated_at"])
                                remote += 1
                                by_kind[kind]["remote"] += 1
                                provider_key = source_fallback["image_source_provider"] or "source page"
                                by_provider[provider_key] = by_provider.get(provider_key, 0) + 1
                                continue

                            candidate = resolve_catalogue_image(obj, variant=variant)
                            diagnostic = {
                                "provider": candidate.provider if candidate else "",
                                "query": candidate.query if candidate else "",
                            }

                        if not candidate:
                            if not isinstance(obj, PrinterCatalogModel) and variant == "base":
                                source_fallback = source_fallback or find_source_page_image(obj)
                            else:
                                source_fallback = None
                            if source_fallback:
                                metadata.update(source_fallback)
                                metadata = append_source_trace(
                                    metadata,
                                    provider=source_fallback.get("image_source_provider", ""),
                                    url=source_fallback.get("image_source_page", ""),
                                    tier=source_fallback.get("image_source_tier", "generic"),
                                    result="selected-remote-image",
                                )
                                metadata["auto_image_last_result"] = "remote-source-fallback"
                                field = set_catalogue_image_metadata(obj, metadata, variant=variant)
                                obj.save(update_fields=[field, "updated_at"] if field else ["updated_at"])
                                remote += 1
                                by_kind[kind]["remote"] += 1
                                provider_key = source_fallback["image_source_provider"] or "source page"
                                by_provider[provider_key] = by_provider.get(provider_key, 0) + 1
                                continue

                            failed += 1
                            by_kind[kind]["failed"] += 1
                            metadata["auto_image_last_result"] = "no-confident-match"
                            field = set_catalogue_image_metadata(obj, metadata, variant=variant)
                            obj.save(update_fields=[field, "updated_at"] if field else ["updated_at"])
                            if len(failures) < 30:
                                failures.append({
                                    "kind": kind,
                                    "id": str(obj.pk),
                                    "name": str(obj),
                                    "variant": variant,
                                    "reason": "no-confident-match",
                                })
                            continue

                        cache_candidate(obj, candidate, variant=variant)
                        metadata, _ = catalogue_image_metadata(obj, variant=variant)
                        metadata = append_source_trace(
                            metadata,
                            provider=candidate.provider,
                            url=candidate.source_page_url,
                            tier="open_media",
                            result="selected-cached-image",
                        )
                        field = set_catalogue_image_metadata(obj, metadata, variant=variant)
                        obj.save(update_fields=[field, "updated_at"] if field else ["updated_at"])
                        cached += 1
                        by_kind[kind]["cached"] += 1
                        provider_key = candidate.provider or "unknown"
                        by_provider[provider_key] = by_provider.get(provider_key, 0) + 1
                    except (CatalogueImageError, requests.RequestException, ValueError) as exc:
                        failed += 1
                        by_kind[kind]["failed"] += 1
                        metadata["auto_image_last_result"] = "error"
                        metadata["auto_image_last_error"] = str(exc)[:300]
                        field = set_catalogue_image_metadata(obj, metadata, variant=variant)
                        obj.save(update_fields=[field, "updated_at"] if field else ["updated_at"])
                        if len(failures) < 30:
                            failures.append({
                                "kind": kind,
                                "id": str(obj.pk),
                                "name": str(obj),
                                "variant": variant,
                                "reason": str(exc)[:200],
                            })

        return {
            "status": "complete",
            "processed": processed,
            "cached": cached,
            "failed": failed,
            "skipped": skipped,
            "by_kind": by_kind,
            "by_provider": by_provider,
            "remote": remote,
            "failures": failures,
            "order": order,
        }
    finally:
        cache.delete(lock_key)
