from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.text import slugify

from .catalogue_images import CatalogueImageError, apply_catalogue_image, fetch_public_image
from .importers import ImporterError, fetch_import_html


COMMONS_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "MakerVault/0.2.2 (+self-hosted catalogue image seeder)"
ALLOWED_COMMONS_LICENSE_PREFIXES = (
    "CC BY",
    "CC0",
    "PUBLIC DOMAIN",
    "PDM",
)

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
        if not license_name.upper().startswith(ALLOWED_COMMONS_LICENSE_PREFIXES):
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
            query=board.name,
        )
    return None


def resolve_catalogue_image(obj) -> ImageCandidate | None:
    from .models import BoardModel, ComponentModel

    if isinstance(obj, BoardModel):
        if settings.CATALOGUE_IMAGE_PREFER_ESPBOARDS:
            candidate = find_espboards_image(obj)
            if candidate:
                return candidate
        if settings.CATALOGUE_IMAGE_WIKIMEDIA:
            return search_wikimedia_commons(_commons_query_for_board(obj), minimum_score=0.16)
        return None

    if isinstance(obj, ComponentModel) and settings.CATALOGUE_IMAGE_WIKIMEDIA:
        query = _commons_query_for_component(obj)
        candidate = search_wikimedia_commons(query, minimum_score=0.16)
        if candidate:
            return candidate
        # Generic components benefit from a broader type-level fallback.
        item_type = str((obj.specifications or {}).get("type") or "")
        fallback = GENERIC_COMPONENT_QUERY_BY_TYPE.get(item_type)
        if fallback and fallback != query:
            return search_wikimedia_commons(fallback, minimum_score=0.12)
    return None


def cache_candidate(obj, candidate: ImageCandidate):
    stem = getattr(obj, "slug", "") or getattr(obj, "name", "") or str(obj.pk)
    content, filename, final_image_url = fetch_public_image(candidate.image_url, stem)
    apply_catalogue_image(
        obj,
        content,
        filename,
        source_url=final_image_url,
        source_type=f"auto-{candidate.provider.lower().replace(' ', '-').replace('.', '')}",
    )
    specs = dict(obj.specifications or {})
    specs.update({
        "image_source_provider": candidate.provider,
        "image_source_page": candidate.source_page_url,
        "image_source_query": candidate.query,
        "image_license": candidate.license_name,
        "image_author": candidate.author,
        "auto_image_seeded": True,
        "auto_image_seeded_at": timezone.now().isoformat(),
    })
    obj.specifications = specs
    obj.save(update_fields=["specifications", "updated_at"])


def _recent_attempt(specs: dict, retry_days: int) -> bool:
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


def run_catalogue_image_seed(*, limit: int | None = None, force_retry: bool = False) -> dict:
    from .models import BoardModel, ComponentModel

    limit = settings.CATALOGUE_IMAGE_MAX_PER_RUN if limit is None else max(int(limit), 0)
    retry_days = max(int(settings.CATALOGUE_IMAGE_RETRY_DAYS), 1)
    lock_key = "makervault:catalogue-image-seed:v0.2.2"
    if not cache.add(lock_key, "running", timeout=60 * 60):
        return {"status": "already-running", "processed": 0, "cached": 0, "failed": 0, "skipped": 0}

    processed = cached = failed = skipped = 0
    try:
        querysets = [
            BoardModel.objects.select_related("manufacturer").order_by("manufacturer__name", "name"),
            ComponentModel.objects.select_related("manufacturer", "category").order_by("category__name", "name"),
        ]
        for queryset in querysets:
            for obj in queryset.iterator():
                if limit and processed >= limit:
                    return {"status": "limit-reached", "processed": processed, "cached": cached, "failed": failed, "skipped": skipped}
                if obj.image:
                    skipped += 1
                    continue
                specs = dict(obj.specifications or {})
                if specs.get("auto_image_opt_out"):
                    skipped += 1
                    continue
                if not force_retry and _recent_attempt(specs, retry_days):
                    skipped += 1
                    continue

                processed += 1
                specs["auto_image_last_attempt"] = timezone.now().isoformat()
                obj.specifications = specs
                obj.save(update_fields=["specifications", "updated_at"])

                try:
                    candidate = resolve_catalogue_image(obj)
                    if not candidate:
                        failed += 1
                        continue
                    cache_candidate(obj, candidate)
                    cached += 1
                except (CatalogueImageError, requests.RequestException, ValueError):
                    failed += 1

        return {"status": "complete", "processed": processed, "cached": cached, "failed": failed, "skipped": skipped}
    finally:
        cache.delete(lock_key)
