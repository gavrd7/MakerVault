from __future__ import annotations

import json
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
from .importers import ImporterError, fetch_catalogue_source_html, fetch_import_html


COMMONS_API = "https://commons.wikimedia.org/w/api.php"
OPENVERSE_API = "https://api.openverse.org/v1/images/"
IMAGE_SEED_VERSION = "1.0.1-filament-images-1"
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


def _strip_catalogue_marketing_suffix(value: str) -> str:
    """Remove lookup-only catalogue/marketing noise without changing display text."""
    value = str(value or "").strip()
    # Internal/importer qualifiers are useful as provenance but are not part of
    # the manufacturer's product identity and make external matching worse.
    value = re.sub(r"\s*[\[(]\s*base\s*[\])]\s*$", "", value, flags=re.I)
    # Product feeds often append compatibility/SEO copy to the real model name.
    # Keep meaningful variants (Sense, Plus, Pro, Zero, etc.) intact.
    value = re.sub(
        r"\s*[-|,:;]?\s+(?:supports?|compatible\s+with|works\s+with)\s+"
        r"(?:arduino|micropython|circuitpython|platformio|esphome)"
        r".*$",
        "",
        value,
        flags=re.I,
    )
    return value.strip(" -|,:;")


def _normalise_catalogue_identity(value: str) -> str:
    """Normalise manufacturer/model labels for exact curated-source matching."""
    value = _strip_catalogue_marketing_suffix(value)
    value = value.replace("®", "").replace("™", "").replace("©", "")
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _normalise_search_label(value: str) -> str:
    """Remove trademark and marketing noise while preserving readable spacing."""
    value = _strip_catalogue_marketing_suffix(value)
    value = value.replace("®", "").replace("™", "").replace("©", "")
    return re.sub(r"\s+", " ", value).strip()


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
    maker = _normalise_search_label(board.manufacturer.name) if board.manufacturer else ""
    model = _normalise_search_label(board.name)
    board_type = str((board.specifications or {}).get("board_type") or "microcontroller")
    suffix = {
        "sbc": "single board computer",
        "compute_module": "compute module",
        "microcontroller": "microcontroller board",
    }.get(board_type, "development board")
    return f"{maker} {model} {suffix}".strip()


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


def _filament_image_queries(filament) -> list[str]:
    maker_obj = getattr(filament, "filament_manufacturer", None) or getattr(filament, "manufacturer", None)
    maker = _normalise_search_label(str(getattr(maker_obj, "name", "") or ""))
    name = _normalise_search_label(str(getattr(filament, "name", "") or ""))
    material = _normalise_search_label(str(getattr(filament, "material", "") or ""))
    colour = _normalise_search_label(str(getattr(filament, "color_name", "") or ""))
    queries = [
        " ".join(part for part in [maker, name, material, colour, "filament"] if part),
        " ".join(part for part in [maker, name, material, "filament spool"] if part),
    ]
    out = []
    for query in queries:
        query = re.sub(r"\s+", " ", query).strip()
        if query and query not in out:
            out.append(query)
    return out[:2]


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
    maker = _normalise_search_label(board.manufacturer.name) if board.manufacturer else ""
    name = _normalise_search_label((board.name or "").replace(" style", ""))
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
    name = _normalise_search_label(board.name)
    manufacturer = _normalise_search_label(board.manufacturer.name) if board.manufacturer else ""
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
            final_url, html = fetch_catalogue_source_html(page_url)
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


CURATED_SBC_SOURCE_PAGES = {
    ("Banana Pi", "BPI-M5"): "https://docs.banana-pi.org/en/BPI-M5/Photo_BPI-M5",
    ("Banana Pi", "BPI-M7"): "https://docs.banana-pi.org/en/BPI-M7/Photo_BPI-M7",
    ("BeagleBoard.org", "BeagleBone Black"): "https://www.beagleboard.org/boards/beaglebone-black",
    ("BeagleBoard.org", "BeaglePlay"): "https://docs.beagleboard.org/latest/boards/beagleplay/index.html",
    ("BeagleBoard.org", "BeagleY-AI"): "https://docs.beagleboard.org/latest/boards/beagley/ai/01-introduction.html",
    ("Hardkernel", "ODROID-C5"): "https://www.hardkernel.com/shop/odroid-c5/",
    ("Hardkernel", "ODROID-H4"): "https://www.hardkernel.com/shop/odroid-h4/",
    ("Hardkernel", "ODROID-H4 Plus"): "https://www.hardkernel.com/shop/odroid-h4-plus/",
    ("Hardkernel", "ODROID-M1"): "https://www.hardkernel.com/shop/odroid-m1-with-8gbyte-ram/",
    ("Hardkernel", "ODROID-M1S"): "https://www.hardkernel.com/shop/odroid-m1s-with-8gbyte-ram/",
    ("Hardkernel", "ODROID-M2"): "https://www.hardkernel.com/shop/odroid-m2-with-16gbyte-ram/",
    ("Hardkernel", "ODROID-N2+"): "https://www.hardkernel.com/shop/odroid-n2-with-4gbyte-ram-2/",
    ("Khadas", "Edge2 Maker Kit"): "https://www.khadas.com/edge2",
    ("Khadas", "VIM4"): "https://www.khadas.com/vim4",
    ("LattePanda", "LattePanda 3 Delta"): "https://www.lattepanda.com/lattepanda-3-delta",
    ("LattePanda", "LattePanda Mu"): "https://www.lattepanda.com/lattepanda-mu",
    ("LattePanda", "LattePanda Sigma"): "https://www.lattepanda.com/lattepanda-sigma",
    ("NVIDIA", "Jetson Orin Nano Super Developer Kit"): "https://docs.nvidia.com/jetson/orin-nano-devkit/user-guide/latest/",
    ("NVIDIA", "Jetson AGX Orin Developer Kit"): "https://developer.nvidia.com/embedded/jetson-agx-orin-developer-kit",
    ("NVIDIA", "Jetson Orin Nano 8GB"): "https://developer.nvidia.com/embedded/jetson-modules",
    ("NVIDIA", "Jetson Orin Nano 4GB"): "https://developer.nvidia.com/embedded/jetson-modules",
    ("NVIDIA", "Jetson Orin NX 8GB"): "https://developer.nvidia.com/embedded/jetson-modules",
    ("NVIDIA", "Jetson Orin NX 16GB"): "https://developer.nvidia.com/embedded/jetson-modules",
    ("NVIDIA", "Jetson AGX Orin 32GB"): "https://developer.nvidia.com/embedded/jetson-modules",
    ("NVIDIA", "Jetson AGX Orin 64GB"): "https://developer.nvidia.com/embedded/jetson-modules",
    ("Radxa", "ROCK 3A"): "https://docs.radxa.com/en/rock3/rock3a",
    ("Radxa", "ROCK 4B+"): "https://docs.radxa.com/en/rock4/rock4b",
    ("Radxa", "ROCK 5A"): "https://docs.radxa.com/en/rock5/rock5a",
    ("Radxa", "ROCK 5B"): "https://docs.radxa.com/en/rock5/rock5b/getting-started/introduction",
    ("Radxa", "ROCK 5C"): "https://docs.radxa.com/en/rock5/rock5c",
    ("Radxa", "CM5"): "https://docs.radxa.com/en/compute-module/cm5",
    ("Orange Pi", "Orange Pi 5 Plus"): "https://www.orangepi.org/html/hardWare/computerAndMicrocontrollers/details/Orange-Pi-5-plus.html",
    ("Orange Pi", "Orange Pi 5 Pro"): "https://www.orangepi.org/html/hardWare/computerAndMicrocontrollers/details/Orange-Pi-5-Pro.html",
}


CURATED_MCU_SOURCE_PAGES = {
    ("Generic", "ESP32-2432S028R CYD"): "https://github.com/witnessmenow/ESP32-Cheap-Yellow-Display",
    ("Adafruit", "Feather ESP32-S3"): "https://learn.adafruit.com/adafruit-esp32-s3-feather",
    ("Adafruit", "Feather RP2040"): "https://learn.adafruit.com/adafruit-feather-rp2040-pico",
    ("Adafruit", "QT Py ESP32-C3"): "https://learn.adafruit.com/adafruit-qt-py-esp32-c3-wifi-dev-board/pinouts",
    ("Arduino", "Nano 33 IoT"): "https://docs.arduino.cc/hardware/nano-33-iot",
    ("Arduino", "Nano ESP32"): "https://docs.arduino.cc/hardware/nano-esp32",
    ("DFRobot", "FireBeetle 2 ESP32-E"): "https://www.dfrobot.com/product-2195.html",
    ("Elecrow", "CrowPanel ESP32 2.8in HMI"): "https://www.elecrow.com/wiki/esp32-display-282727-intelligent-touch-screen-wi-fi26ble-240320-hmi-display.html",
    ("Elecrow", "CrowPanel ESP32 3.5in HMI"): "https://elecrow.com/wiki/esp32-display-352727-intelligent-touch-screen-wi-fi26ble-320480-hmi-display.html",
    ("Espressif", "ESP32-P4-Function-EV-Board"): "https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32p4/esp32-p4-function-ev-board/user_guide.html",
    ("Heltec", "WiFi LoRa 32 V3"): "https://heltec.org/project/wifi-lora-32-v3/",
    ("Heltec", "Wireless Stick Lite V3"): "https://wiki.heltec.org/docs/devices/open-source-hardware/esp32-series/lora-32/wireless-stick-lite/",
    ("LilyGo", "T-Deck"): "https://wiki.lilygo.cc/products/t-deck-series/t-deck/",
    ("LilyGo", "T-Display-S3"): "https://wiki.lilygo.cc/products/t-display-series/t-display-s3/",
    ("M5Stack", "Atom Lite"): "https://docs.m5stack.com/en/core/ATOM%20Lite",
    ("M5Stack", "CoreS3"): "https://docs.m5stack.com/en/core/CoreS3",
    ("Seeed Studio", "XIAO RP2350"): "https://wiki.seeedstudio.com/xiao_rp2350_arduino/",
    ("Seeed Studio", "XIAO RP2040"): "https://wiki.seeedstudio.com/XIAO-RP2040/",
}


CURATED_SBC_SOURCE_FALLBACKS = {
    ("BeagleBoard.org", "BeaglePlay"): (
        "https://www.beagleboard.org/boards/beagleplay",
    ),
    ("Orange Pi", "Orange Pi 5 Plus"): (
        "https://www.orangepi.org/orangepiwiki/index.php/Orange_Pi_5_Plus",
        "https://www.orangepi.org/",
    ),
    ("Orange Pi", "Orange Pi 5 Pro"): (
        "https://www.orangepi.org/orangepiwiki/index.php/Orange_Pi_5_Pro",
        "https://www.orangepi.org/",
    ),
}


def _curated_sbc_source_pages(obj) -> list[str]:
    specs = getattr(obj, "specifications", None) or {}
    if str(specs.get("board_type") or "").strip().lower() not in {"sbc", "compute_module"}:
        return []
    manufacturer = str(getattr(getattr(obj, "manufacturer", None), "name", "") or "").strip()
    name = str(getattr(obj, "name", "") or "").strip()
    manufacturer_key = _normalise_catalogue_identity(manufacturer)
    name_key = _normalise_catalogue_identity(name)
    pages = []
    matched_key = None
    for key in CURATED_SBC_SOURCE_PAGES:
        if (
            _normalise_catalogue_identity(key[0]) == manufacturer_key
            and _normalise_catalogue_identity(key[1]) == name_key
        ):
            matched_key = key
            primary = CURATED_SBC_SOURCE_PAGES[key]
            if primary:
                pages.append(primary)
            break
    fallback_key = matched_key
    if fallback_key is None:
        for key in CURATED_SBC_SOURCE_FALLBACKS:
            if (
                _normalise_catalogue_identity(key[0]) == manufacturer_key
                and _normalise_catalogue_identity(key[1]) == name_key
            ):
                fallback_key = key
                break
    for url in CURATED_SBC_SOURCE_FALLBACKS.get(fallback_key, ()):
        if url and url not in pages:
            pages.append(url)
    return pages


def _curated_sbc_source_page(obj) -> str:
    pages = _curated_sbc_source_pages(obj)
    return pages[0] if pages else ""


def _curated_board_source_pages(obj) -> list[str]:
    specs = getattr(obj, "specifications", None) or {}
    board_type = str(specs.get("board_type") or "microcontroller").strip().lower()
    if board_type in {"sbc", "compute_module"}:
        return _curated_sbc_source_pages(obj)
    manufacturer = str(getattr(getattr(obj, "manufacturer", None), "name", "") or "").strip()
    name = str(getattr(obj, "name", "") or "").strip()
    manufacturer_key = _normalise_catalogue_identity(manufacturer)
    name_key = _normalise_catalogue_identity(name)
    for (mapped_manufacturer, mapped_name), url in CURATED_MCU_SOURCE_PAGES.items():
        if (
            _normalise_catalogue_identity(mapped_manufacturer) == manufacturer_key
            and _normalise_catalogue_identity(mapped_name) == name_key
        ):
            return [url]
    return []


def _candidate_source_pages(obj) -> list[dict]:
    """Return authoritative/source pages shared by boards, components and printers."""
    specs = getattr(obj, "specifications", None) or {}
    features = getattr(obj, "features", None) or {}
    profile_data = getattr(obj, "profile_data", None) or {}
    candidates = []
    seen = set()

    def add(url, *, source_type="", provider=""):
        value = str(url or "").strip()
        if not value.startswith("https://") or value.lower().endswith(".pdf") or value in seen:
            return
        candidates.append({
            "url": value,
            "source_type": source_type,
            "provider": provider,
        })
        seen.add(value)

    for curated_url in _curated_board_source_pages(obj):
        curated_host = (urlparse(curated_url).hostname or "").lower()
        if curated_host == "github.com" or curated_host.endswith(".github.com"):
            add(curated_url, source_type="github", provider="Community / ecosystem")
        else:
            add(curated_url, source_type="manufacturer", provider="Official manufacturer")

    manufacturer = getattr(obj, "filament_manufacturer", None) or getattr(obj, "manufacturer", None)
    manufacturer_name = str(getattr(manufacturer, "name", "") or "").strip()
    provider = f"{manufacturer_name} official".strip() if manufacturer_name else ""

    # Catalogue records use different metadata containers, but source-page
    # discovery should be consistent regardless of object type.
    for container in (specs, features, profile_data, profile_data.get("catalogue_provenance", {})):
        if not isinstance(container, dict):
            continue
        for key in (
            "official_image_source_page",
            "reference_url",
            "technical_source_url",
            "product_url",
            "tds_url",
            "sds_url",
            "datasheet_url",
            "pinout_url",
        ):
            add(
                container.get(key),
                source_type="manufacturer" if key in {"official_image_source_page", "product_url"} else "",
                provider=str(container.get("reference_provider") or provider).strip(),
            )

    add(
        getattr(obj, "source_url", ""),
        source_type="manufacturer" if manufacturer_name else "",
        provider=provider,
    )

    source = getattr(obj, "source", None)
    add(
        getattr(source, "url", ""),
        source_type=str(getattr(source, "source_type", "") or ""),
        provider=str(getattr(source, "name", "") or ""),
    )

    return ordered_source_candidates(candidates)[:8]


def _structured_product_image(soup: BeautifulSoup, base_url: str) -> str:
    """Extract a product image from structured page metadata.

    Source-page images remain remote references; this helper only discovers
    already-published HTTPS image URLs and does not cache them.
    """

    def resolved_https(value) -> str:
        value = str(value or "").strip()
        if not value:
            return ""
        resolved = urljoin(base_url, value)
        parsed = urlparse(resolved)
        return resolved if parsed.scheme == "https" and parsed.netloc else ""

    documents = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text("", strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue

        queue = payload if isinstance(payload, list) else [payload]
        while queue:
            item = queue.pop(0)
            if isinstance(item, list):
                queue.extend(item)
                continue
            if not isinstance(item, dict):
                continue
            documents.append(item)
            graph = item.get("@graph")
            if isinstance(graph, list):
                queue.extend(graph)

    graph_by_id = {
        str(item.get("@id")).strip(): item
        for item in documents
        if str(item.get("@id") or "").strip()
    }

    def image_candidate(candidate) -> str:
        if isinstance(candidate, dict):
            direct = candidate.get("url") or candidate.get("contentUrl") or candidate.get("thumbnailUrl")
            if direct:
                return resolved_https(direct)
            ref = str(candidate.get("@id") or "").strip()
            linked = graph_by_id.get(ref)
            if linked:
                return resolved_https(
                    linked.get("url") or linked.get("contentUrl") or linked.get("thumbnailUrl")
                )
            return ""
        return resolved_https(candidate)

    for item in documents:
        item_type = item.get("@type")
        types = set(item_type if isinstance(item_type, list) else [item_type])
        if not ({"Product", "IndividualProduct"} & types):
            continue

        image = item.get("image")
        candidates = image if isinstance(image, list) else [image]
        for candidate in candidates:
            resolved = image_candidate(candidate)
            if resolved:
                return resolved

        # Some commerce templates expose these fields directly on Product.
        for key in ("primaryImageOfPage", "thumbnailUrl"):
            resolved = image_candidate(item.get(key))
            if resolved:
                return resolved

    for attrs in (
        {"rel": "image_src"},
        {"itemprop": "image"},
    ):
        tag = soup.find(["link", "meta", "img"], attrs=attrs)
        if not tag:
            continue
        value = str(
            tag.get("href")
            or tag.get("content")
            or tag.get("src")
            or tag.get("data-src")
            or tag.get("data-original")
            or ""
        ).strip()
        if not value and tag.get("srcset"):
            value = str(tag.get("srcset")).split(",", 1)[0].strip().split(" ", 1)[0]
        resolved = resolved_https(value)
        if resolved:
            return resolved
    return ""


def find_curated_printer_image(printer_model, variant: str = "base") -> dict | None:
    """Return a version-controlled official printer image reference when present."""
    features = dict(getattr(printer_model, "features", None) or {})
    prefix = "official_image_multi_material" if variant == "multi_material" else "official_image"
    image_url = str(features.get(f"{prefix}_url") or "").strip()
    if not image_url.startswith("https://"):
        return None
    source_page = str(
        features.get(f"{prefix}_source_page")
        or getattr(printer_model, "source_url", "")
        or ""
    ).strip()
    provider = str(
        features.get(f"{prefix}_source_provider")
        or f"{getattr(getattr(printer_model, 'manufacturer', None), 'name', '')} official"
    ).strip()
    return {
        "external_image_url": image_url,
        "image_source_page": source_page,
        "image_source_provider": provider or "Official manufacturer",
        "image_source_type": "curated-official-remote",
        "image_source_discovery": "curated-profile",
        "image_source_tier": "manufacturer",
        "image_source_priority": 10,
        "image_license": "",
        "image_author": "",
    }


def find_orcaslicer_printer_cover(printer_model, variant: str = "base") -> dict | None:
    """Return an exact OrcaSlicer printer cover as a remote image reference.

    OrcaSlicer machine-model profiles may ship a 240x240 cover named after the
    exact machine-model-list entry. Because MakerVault stores the upstream
    vendor file, ref and original model name, this is a deterministic mapping
    rather than a fuzzy image search. The asset is referenced remotely instead
    of copied into MakerVault storage.
    """
    if variant != "base":
        return None

    features = dict(getattr(printer_model, "features", None) or {})
    provenance = features.get("orcaslicer") or {}
    if not isinstance(provenance, dict):
        return None

    vendor_file = str(provenance.get("vendor_file") or "").strip()
    raw_name = str(provenance.get("upstream_name") or "").strip()
    ref = str(provenance.get("ref") or "").strip()
    if not vendor_file or not raw_name or not ref:
        return None

    vendor_folder = vendor_file[:-5] if vendor_file.lower().endswith(".json") else vendor_file
    filename = f"{raw_name}_cover.png"
    raw_url = (
        "https://raw.githubusercontent.com/OrcaSlicer/OrcaSlicer/"
        f"{quote(ref, safe='')}/resources/profiles/"
        f"{quote(vendor_folder, safe='')}/{quote(filename, safe='')}"
    )
    source_page = (
        "https://github.com/OrcaSlicer/OrcaSlicer/blob/"
        f"{quote(ref, safe='')}/resources/profiles/"
        f"{quote(vendor_folder, safe='')}/{quote(filename, safe='')}"
    )

    # Probe only the exact, fixed-host asset. Streaming lets us validate the
    # status/content type without downloading and redistributing the image.
    try:
        response = requests.get(
            raw_url,
            timeout=(5, 15),
            stream=True,
            allow_redirects=True,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "image/webp,image/png,image/jpeg;q=0.9,*/*;q=0.2",
            },
        )
        status_code = response.status_code
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        response.close()
    except requests.RequestException:
        return None

    if status_code != 200 or content_type not in {"image/jpeg", "image/png", "image/webp"}:
        return None

    return {
        "external_image_url": raw_url,
        "image_source_page": source_page,
        "image_source_provider": "OrcaSlicer",
        "image_source_type": "orcaslicer-cover-remote",
        "image_source_discovery": "exact-profile-cover",
        "image_source_tier": "specialist",
        "image_source_priority": 30,
        "image_license": "",
        "image_author": "",
    }


def _is_computer_board(obj) -> bool:
    from .models import BoardModel
    return isinstance(obj, BoardModel) and str((obj.specifications or {}).get("board_type") or "") in {"sbc", "compute_module"}


def _page_image_candidates(soup: BeautifulSoup, base_url: str) -> list[tuple[str, str]]:
    """Return likely product images in priority order from a known source page."""
    preferred: list[tuple[str, str]] = []
    fallback: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(value, method, *, prefer=False):
        raw = str(value or "").strip()
        if not raw:
            return
        resolved = urljoin(base_url, raw)
        parsed = urlparse(resolved)
        if parsed.scheme != "https" or not parsed.netloc or resolved in seen:
            return
        path_hint = (parsed.path or "").lower()
        if path_hint.endswith((".svg", ".ico")):
            return
        # Source pages frequently publish brand/social artwork alongside the
        # actual product photo. Never promote obvious chrome/placeholders to a
        # catalogue image merely because they are first in page metadata.
        if any(token in path_hint for token in (
            "favicon", "site-logo", "/logo", "_logo", "-logo",
            "avatar", "placeholder", "default-image", "social-card",
            "social_share", "social-share", "banner",
        )):
            return
        seen.add(resolved)
        (preferred if prefer else fallback).append((resolved, method))

    # Product-aware structured metadata is the strongest page-level signal.
    add(_structured_product_image(soup, base_url), "structured", prefer=True)

    # Prefer semantically-labelled product/board photographs over social cards
    # or decorative hero/background assets. This avoids treating a vendor logo
    # or blank marketing background as a successful catalogue image.
    image_tags = list(soup.find_all("img", limit=120))
    for semantic_only in (True, False):
        for tag in image_tags:
            text = " ".join([
                str(tag.get("alt") or ""),
                str(tag.get("title") or ""),
                " ".join(str(part) for part in (tag.get("class") or [])),
            ]).lower()
            if any(word in text for word in (
                "logo", "icon", "avatar", "banner", "flag", "spinner",
                "background", "decorative", "author", "profile", "for user",
            )):
                continue
            semantic = any(word in text for word in (
                "product", "board", "photo", "hardware", "device", "front", "back",
            ))
            if semantic != semantic_only:
                continue
            value = (
                tag.get("data-large_image")
                or tag.get("data-zoom-image")
                or tag.get("data-lazy-src")
                or tag.get("data-lazy")
                or tag.get("data-src")
                or tag.get("data-original")
                or tag.get("data-url")
                or tag.get("data-image")
                or tag.get("src")
                or ""
            )
            for srcset_key in ("data-srcset", "srcset"):
                if not value and tag.get(srcset_key):
                    entries = [entry.strip() for entry in str(tag.get(srcset_key)).split(",") if entry.strip()]
                    if entries:
                        value = entries[-1].split(" ", 1)[0]
            add(value, "page-image", prefer=semantic_only)

    # Full-size product gallery links are also strong image candidates.
    for tag in soup.find_all("a", limit=120):
        classes = " ".join(str(part) for part in (tag.get("class") or [])).lower()
        rel = " ".join(str(part) for part in (tag.get("rel") or [])).lower()
        if not any(word in classes + " " + rel for word in ("woocommerce", "gallery", "zoom", "product")):
            continue
        href = str(tag.get("href") or "").strip()
        if re.search(r"\.(?:jpe?g|png|webp)(?:\?.*)?$", href, re.I):
            add(href, "gallery-image", prefer=True)

    # Social metadata remains useful when a source page does not expose a
    # semantically-labelled product image.
    for attrs in (
        {"property": "og:image:secure_url"},
        {"property": "og:image"},
        {"name": "twitter:image"},
        {"name": "twitter:image:src"},
        {"property": "twitter:image"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag:
            add(tag.get("content"), "meta")

    # Modern documentation/product sites sometimes render imagery through
    # <source> elements or inline CSS rather than a conventional <img src>.
    for tag in soup.find_all("source", limit=120):
        value = str(tag.get("src") or tag.get("data-src") or "").strip()
        srcset = str(tag.get("srcset") or tag.get("data-srcset") or "").strip()
        if not value and srcset:
            entries = [entry.strip() for entry in srcset.split(",") if entry.strip()]
            if entries:
                value = entries[-1].split(" ", 1)[0]
        context_tag = tag.parent
        context = " ".join([
            str(getattr(context_tag, "get", lambda *_: "")("class") or ""),
            str(getattr(context_tag, "get", lambda *_: "")("aria-label") or ""),
        ]).lower()
        add(value, "picture-source", prefer=any(word in context for word in ("product", "board", "photo", "gallery")))

    css_url = re.compile(r"""url\(\s*['"]?([^'")]+)['"]?\s*\)""", re.I)
    for tag in soup.find_all(style=True, limit=160):
        classes = " ".join(str(part) for part in (tag.get("class") or [])).lower()
        ident = str(tag.get("id") or "").lower()
        label = str(tag.get("aria-label") or "").lower()
        context = " ".join((classes, ident, label))
        if any(word in context for word in ("logo", "icon", "avatar", "banner", "spinner", "background")):
            continue
        semantic = any(word in context for word in ("product", "board", "photo", "gallery"))
        for match in css_url.finditer(str(tag.get("style") or "")):
            add(match.group(1), "css-background", prefer=semantic)

    return preferred + fallback

def find_source_page_image(obj, diagnostics: list[dict] | None = None) -> dict | None:
    """Find a remote product image from an already-known catalogue source page.

    These images are referenced remotely rather than cached because MakerVault
    does not assume redistribution rights merely because a source page exposes
    an OpenGraph image.
    """
    for source in _candidate_source_pages(obj):
        page_url = source["url"]
        tier = classify_source_url(page_url, source_type=source.get("source_type", ""))
        try:
            final_url, html = fetch_catalogue_source_html(page_url)
        except ImporterError as exc:
            if diagnostics is not None:
                diagnostics.append({
                    "url": page_url,
                    "tier": tier.key,
                    "result": "fetch-error",
                    "error": str(exc)[:220],
                })
            continue
        soup = BeautifulSoup(html, "html.parser")
        image_candidates = _page_image_candidates(soup, final_url)
        if not image_candidates:
            if diagnostics is not None:
                diagnostics.append({
                    "url": final_url,
                    "tier": tier.key,
                    "result": "no-image-candidate",
                    "error": "",
                })
            continue
        image_url, discovery_method = image_candidates[0]
        tier = classify_source_url(final_url, source_type=source.get("source_type", ""))
        if diagnostics is not None:
            diagnostics.append({
                "url": final_url,
                "tier": tier.key,
                "result": "image-candidate",
                "error": "",
                "image_url": image_url[:1000],
                "method": discovery_method,
            })
        return {
            "external_image_url": image_url,
            "image_source_page": final_url,
            "image_source_provider": source.get("provider") or urlparse(final_url).netloc.removeprefix("www."),
            "image_source_type": "source-page-remote",
            "image_source_discovery": discovery_method,
            "image_source_tier": tier.key,
            "image_source_priority": tier.priority,
            "image_license": "",
            "image_author": "",
        }
    return None


def resolve_catalogue_image(obj, variant: str = "base") -> ImageCandidate | None:
    from .models import BoardModel, ComponentModel, FilamentProduct, PrinterCatalogModel

    if isinstance(obj, BoardModel):
        if settings.CATALOGUE_IMAGE_PREFER_ESPBOARDS:
            candidate = find_espboards_image(obj)
            if candidate:
                return candidate
        return _search_open_media(_board_image_queries(obj), minimum_score=0.16)

    if isinstance(obj, ComponentModel):
        queries = _component_image_queries(obj)
        # Part-numbered components need a recognisable identity match, not a
        # generic lookalike photograph. Generic catalogue items can use a
        # category illustration if no suitably specific image can be found.
        identifiable = bool((obj.part_number or "").strip())
        minimum = 0.42 if identifiable else 0.30
        candidate = _search_open_media(queries[:3], minimum_score=minimum)
        if candidate:
            return candidate
        if not identifiable and len(queries) > 3:
            return _search_open_media(queries[3:], minimum_score=0.30)
        return None

    if isinstance(obj, FilamentProduct):
        return _search_open_media(_filament_image_queries(obj), minimum_score=0.58)

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
    board_types: list[str] | tuple[str, ...] | None = None,
) -> dict:
    from .models import BoardModel, ComponentModel, FilamentProduct, PrinterCatalogModel

    limit = settings.CATALOGUE_IMAGE_MAX_PER_RUN if limit is None else max(int(limit), 0)
    retry_days = max(int(settings.CATALOGUE_IMAGE_RETRY_DAYS), 1)
    allowed_kinds = {"printers", "boards", "components", "filaments"}
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
            "artwork": 0,
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
    requested_board_types = {str(item).strip().lower() for item in (board_types or []) if str(item).strip()}
    valid_board_types = {"microcontroller", "sbc", "compute_module"}
    invalid_board_types = requested_board_types - valid_board_types
    if invalid_board_types:
        raise ValueError(f"Unknown board type(s): {', '.join(sorted(invalid_board_types))}")
    if requested_board_types:
        board_ids = [
            board.pk for board in boards
            if str((board.specifications or {}).get("board_type") or "microcontroller").lower() in requested_board_types
        ]
        boards = BoardModel.objects.select_related("manufacturer", "source").filter(pk__in=board_ids).order_by("manufacturer__name", "name")
    components = ComponentModel.objects.select_related("category", "source").order_by("category__name", "name")
    printers = PrinterCatalogModel.objects.select_related("manufacturer").order_by("manufacturer__name", "name")
    filaments = FilamentProduct.objects.select_related(
        "filament_manufacturer", "manufacturer", "source"
    ).order_by("filament_manufacturer__name", "name", "color_name")

    sources = {
        "boards": boards,
        "components": components,
        "printers": printers,
        "filaments": filaments,
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

    processed = cached = failed = skipped = remote = artwork = 0
    by_kind = {
        key: {"processed": 0, "cached": 0, "remote": 0, "artwork": 0, "failed": 0, "skipped": 0}
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
                            "artwork": artwork,
                            "failures": failures,
                            "order": order,
                        }

                    image_field = "image_multi_material" if variant == "multi_material" else "image"
                    metadata, _ = catalogue_image_metadata(obj, variant=variant)
                    # A real locally-cached image is authoritative and does not
                    # need network revalidation. Remote references are different:
                    # they may expire, hotlink-block, or belong to an older discovery
                    # generation. Honour --force-retry for them, and automatically
                    # reconsider them after IMAGE_SEED_VERSION changes.
                    if getattr(obj, image_field, None):
                        skipped += 1
                        by_kind[kind]["skipped"] += 1
                        continue

                    external_image_url = str(metadata.get("external_image_url") or "").strip()
                    has_external_image = external_image_url.startswith("https://")
                    retry_remote_catalogue = (
                        has_external_image
                        and (
                            force_retry
                            or (
                                isinstance(obj, BoardModel)
                                and metadata.get("auto_image_attempt_version") != IMAGE_SEED_VERSION
                            )
                        )
                    )
                    if has_external_image and not retry_remote_catalogue:
                        skipped += 1
                        by_kind[kind]["skipped"] += 1
                        continue

                    if metadata.get("auto_image_opt_out"):
                        skipped += 1
                        by_kind[kind]["skipped"] += 1
                        continue

                    # Curated manufacturer imagery is deterministic and should
                    # be recorded before any search work. Multi-material images
                    # are deliberately restricted to this authoritative path:
                    # a generic AMS/CFS/MMU search is too likely to associate a
                    # valid accessory image with the wrong printer/variant.
                    if isinstance(obj, PrinterCatalogModel):
                        curated_remote = find_curated_printer_image(obj, variant=variant)
                        if curated_remote:
                            metadata.update(curated_remote)
                            metadata = append_source_trace(
                                metadata,
                                provider=curated_remote.get("image_source_provider", ""),
                                url=curated_remote.get("image_source_page", ""),
                                tier="manufacturer",
                                result="selected-curated-official-image",
                            )
                            metadata["auto_image_last_result"] = "remote-curated-official"
                            metadata["image_variant"] = variant
                            field = set_catalogue_image_metadata(obj, metadata, variant=variant)
                            obj.save(update_fields=[field, "updated_at"] if field else ["updated_at"])
                            remote += 1
                            by_kind[kind]["remote"] += 1
                            provider_key = curated_remote["image_source_provider"] or "Official manufacturer"
                            by_provider[provider_key] = by_provider.get(provider_key, 0) + 1
                            continue
                        if variant == "multi_material":
                            metadata["auto_image_last_result"] = "deferred-no-authoritative-multi-material-image"
                            metadata["auto_image_attempt_version"] = IMAGE_SEED_VERSION
                            metadata["image_variant"] = variant
                            field = set_catalogue_image_metadata(obj, metadata, variant=variant)
                            obj.save(update_fields=[field, "updated_at"] if field else ["updated_at"])
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
                        if isinstance(obj, FilamentProduct):
                            source_page_diagnostics = []
                            source_fallback = find_source_page_image(
                                obj,
                                diagnostics=source_page_diagnostics,
                            )
                            if source_page_diagnostics:
                                metadata["auto_image_source_page_attempts"] = source_page_diagnostics[-8:]
                            if source_fallback and source_fallback.get("image_source_tier") == "manufacturer":
                                metadata.update(source_fallback)
                                metadata = append_source_trace(
                                    metadata,
                                    provider=source_fallback.get("image_source_provider", ""),
                                    url=source_fallback.get("image_source_page", ""),
                                    tier="manufacturer",
                                    result="selected-authoritative-source-image",
                                )
                                metadata["auto_image_last_result"] = "remote-authoritative-source"
                                field = set_catalogue_image_metadata(obj, metadata, variant=variant)
                                obj.save(update_fields=[field, "updated_at"] if field else ["updated_at"])
                                remote += 1
                                by_kind[kind]["remote"] += 1
                                provider_key = source_fallback["image_source_provider"] or "Official manufacturer"
                                by_provider[provider_key] = by_provider.get(provider_key, 0) + 1
                                continue

                        if isinstance(obj, PrinterCatalogModel):
                            source_page_diagnostics = []
                            if variant == "base":
                                source_fallback = find_source_page_image(
                                    obj,
                                    diagnostics=source_page_diagnostics,
                                )
                                if source_page_diagnostics:
                                    metadata["auto_image_source_page_attempts"] = source_page_diagnostics[-8:]
                                if source_fallback and source_fallback.get("image_source_tier") == "manufacturer":
                                    metadata.update(source_fallback)
                                    metadata = append_source_trace(
                                        metadata,
                                        provider=source_fallback.get("image_source_provider", ""),
                                        url=source_fallback.get("image_source_page", ""),
                                        tier="manufacturer",
                                        result="selected-authoritative-source-image",
                                    )
                                    metadata["auto_image_last_result"] = "remote-authoritative-source"
                                    field = set_catalogue_image_metadata(obj, metadata, variant=variant)
                                    obj.save(update_fields=[field, "updated_at"] if field else ["updated_at"])
                                    remote += 1
                                    by_kind[kind]["remote"] += 1
                                    provider_key = source_fallback["image_source_provider"] or "Official manufacturer"
                                    by_provider[provider_key] = by_provider.get(provider_key, 0) + 1
                                    continue

                            source_fallback = find_orcaslicer_printer_cover(obj, variant=variant)
                            if source_fallback:
                                metadata.update(source_fallback)
                                metadata = append_source_trace(
                                    metadata,
                                    provider=source_fallback.get("image_source_provider", ""),
                                    url=source_fallback.get("image_source_page", ""),
                                    tier=source_fallback.get("image_source_tier", "specialist"),
                                    result="selected-exact-profile-cover",
                                )
                                metadata["auto_image_last_result"] = "remote-orcaslicer-cover"
                                field = set_catalogue_image_metadata(obj, metadata, variant=variant)
                                obj.save(update_fields=[field, "updated_at"] if field else ["updated_at"])
                                remote += 1
                                by_kind[kind]["remote"] += 1
                                provider_key = source_fallback["image_source_provider"] or "OrcaSlicer"
                                by_provider[provider_key] = by_provider.get(provider_key, 0) + 1
                                continue

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
                            source_page_diagnostics = []
                            source_fallback = find_source_page_image(
                                obj,
                                diagnostics=source_page_diagnostics,
                            ) if variant == "base" else None
                            if source_page_diagnostics:
                                metadata["auto_image_source_page_attempts"] = source_page_diagnostics[-8:]
                            # SBCs and compute modules should prefer an exact official
                            # product/documentation page image over fuzzy open-media
                            # search.  Remote-reference it rather than copying it, since
                            # publication does not imply redistribution rights.
                            if source_fallback and _is_computer_board(obj) and source_fallback.get("image_source_tier") == "manufacturer":
                                metadata.update(source_fallback)
                                metadata = append_source_trace(
                                    metadata,
                                    provider=source_fallback.get("image_source_provider", ""),
                                    url=source_fallback.get("image_source_page", ""),
                                    tier="manufacturer",
                                    result="selected-official-sbc-image",
                                )
                                metadata["auto_image_last_result"] = "remote-official-sbc"
                                field = set_catalogue_image_metadata(obj, metadata, variant=variant)
                                obj.save(update_fields=[field, "updated_at"] if field else ["updated_at"])
                                remote += 1
                                by_kind[kind]["remote"] += 1
                                provider_key = source_fallback["image_source_provider"] or "Official manufacturer"
                                by_provider[provider_key] = by_provider.get(provider_key, 0) + 1
                                continue

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
                                if source_fallback is None and not source_page_diagnostics:
                                    source_fallback = find_source_page_image(
                                        obj,
                                        diagnostics=source_page_diagnostics,
                                    )
                                    if source_page_diagnostics:
                                        metadata["auto_image_source_page_attempts"] = source_page_diagnostics[-8:]
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

                            if isinstance(obj, ComponentModel):
                                metadata["auto_image_last_result"] = "generic-artwork"
                                metadata["image_source_type"] = "generic-artwork"
                                field = set_catalogue_image_metadata(obj, metadata, variant=variant)
                                obj.save(update_fields=[field, "updated_at"] if field else ["updated_at"])
                                artwork += 1
                                by_kind[kind]["artwork"] += 1
                                continue

                            failed += 1
                            by_kind[kind]["failed"] += 1
                            metadata["auto_image_last_result"] = "no-confident-match"
                            field = set_catalogue_image_metadata(obj, metadata, variant=variant)
                            obj.save(update_fields=[field, "updated_at"] if field else ["updated_at"])
                            if len(failures) < 30:
                                reason = "no-confident-match"
                                if _is_computer_board(obj) and source_page_diagnostics:
                                    first = source_page_diagnostics[0]
                                    source_result = first.get("result") or "unknown"
                                    source_error = first.get("error") or ""
                                    source_host = urlparse(first.get("url") or "").netloc
                                    reason = f"official-source {source_host}: {source_result}"
                                    if source_error:
                                        reason += f" ({source_error})"
                                failures.append({
                                    "kind": kind,
                                    "id": str(obj.pk),
                                    "name": str(obj),
                                    "variant": variant,
                                    "reason": reason[:200],
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
                        metadata["auto_image_last_error"] = str(exc)[:300]
                        if isinstance(obj, ComponentModel):
                            metadata["auto_image_last_result"] = "generic-artwork-after-image-error"
                            metadata["image_source_type"] = "generic-artwork"
                            field = set_catalogue_image_metadata(obj, metadata, variant=variant)
                            obj.save(update_fields=[field, "updated_at"] if field else ["updated_at"])
                            artwork += 1
                            by_kind[kind]["artwork"] += 1
                            continue

                        failed += 1
                        by_kind[kind]["failed"] += 1
                        metadata["auto_image_last_result"] = "error"
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
            "artwork": artwork,
            "failures": failures,
            "order": order,
        }
    finally:
        cache.delete(lock_key)
