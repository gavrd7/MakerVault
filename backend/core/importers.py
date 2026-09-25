from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


MAX_IMPORT_BYTES = 4 * 1024 * 1024
ESPBOARDS_HOSTS = {"espboards.dev", "www.espboards.dev"}


class ImporterError(ValueError):
    """Raised when an external catalogue URL cannot be safely imported."""


@dataclass(frozen=True)
class SafeImportURL:
    url: str
    host: str


def _host_is_public(host: str) -> bool:
    try:
        answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ImporterError("The import host could not be resolved.") from exc

    if not answers:
        raise ImporterError("The import host did not resolve to an address.")

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


def validate_import_url(raw_url: str) -> SafeImportURL:
    value = (raw_url or "").strip()
    if not value:
        raise ImporterError("Enter a URL to import.")

    parsed = urlparse(value)
    if parsed.scheme != "https":
        raise ImporterError("MakerVault imports require an HTTPS URL.")
    host = (parsed.hostname or "").lower().rstrip(".")
    if host not in ESPBOARDS_HOSTS:
        raise ImporterError("v0.2 currently supports ESPBoards.dev URLs only.")
    if parsed.port not in (None, 443):
        raise ImporterError("Non-standard ports are not permitted for URL imports.")
    if parsed.username or parsed.password:
        raise ImporterError("Credentials in import URLs are not permitted.")
    if not _host_is_public(host):
        raise ImporterError("The import URL resolved to a private or reserved address.")
    return SafeImportURL(url=value, host=host)


def fetch_import_html(raw_url: str) -> tuple[str, str]:
    current = validate_import_url(raw_url).url
    headers = {
        "User-Agent": "MakerVault/0.2 (+self-hosted catalogue importer)",
        "Accept": "text/html,application/xhtml+xml",
    }

    for _ in range(5):
        safe = validate_import_url(current)
        try:
            response = requests.get(
                safe.url,
                headers=headers,
                timeout=(5, 15),
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as exc:
            raise ImporterError("MakerVault could not retrieve that URL.") from exc

        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location")
            if not location:
                raise ImporterError("The source returned an invalid redirect.")
            current = urljoin(safe.url, location)
            response.close()
            continue

        if response.status_code != 200:
            response.close()
            raise ImporterError(f"The source returned HTTP {response.status_code}.")

        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type not in {"text/html", "application/xhtml+xml"}:
            response.close()
            raise ImporterError("The source did not return an HTML page.")

        declared = response.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > MAX_IMPORT_BYTES:
            response.close()
            raise ImporterError("The source page is too large to import safely.")

        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_IMPORT_BYTES:
                response.close()
                raise ImporterError("The source page is too large to import safely.")
            chunks.append(chunk)
        encoding = response.encoding or "utf-8"
        response.close()
        return current, b"".join(chunks).decode(encoding, errors="replace")

    raise ImporterError("The source redirected too many times.")


def _first_number(text: str, patterns: list[str]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except (TypeError, ValueError):
                pass
    return None


def parse_espboards_html(source_url: str, html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if not h1:
        raise ImporterError("ESPBoards page did not contain a board title.")

    heading = " ".join(h1.stripped_strings).strip()
    text = soup.get_text("\n", strip=True)
    flat = re.sub(r"\s+", " ", text)

    by_match = re.search(r"(?im)^by\s+([^\n]{2,80})$", text)
    manufacturer = by_match.group(1).strip() if by_match else "Generic"
    if manufacturer.lower() in {"generic", "unknown"}:
        manufacturer = "Generic"

    name = heading
    if manufacturer != "Generic" and name.lower().startswith(manufacturer.lower() + " "):
        name = name[len(manufacturer) + 1 :].strip()

    description_tag = soup.find("meta", attrs={"name": "description"})
    description = description_tag.get("content", "").strip() if description_tag else ""

    image_tag = soup.find("meta", attrs={"property": "og:image"})
    image_url = urljoin(source_url, image_tag.get("content", "").strip()) if image_tag else ""

    canonical = soup.find("link", rel=lambda value: value and "canonical" in value)
    canonical_url = urljoin(source_url, canonical.get("href", "").strip()) if canonical else source_url

    family_match = re.search(r"\b(ESP32-(?:S2|S3|C2|C3|C5|C6|H2|P4))\b", flat, re.IGNORECASE)
    if not family_match:
        family_match = re.search(r"\b(ESP8266|ESP32)\b", flat, re.IGNORECASE)
    family = family_match.group(1).upper() if family_match else "ESP32"

    architecture = ""
    if re.search(r"\bRISC-V\b", flat, re.IGNORECASE):
        architecture = "RISC-V"
    elif re.search(r"\bXtensa\b", flat, re.IGNORECASE):
        architecture = "Xtensa"

    dims = re.search(r"(\d+(?:\.\d+)?)\s*[×x]\s*(\d+(?:\.\d+)?)\s*mm", flat, re.IGNORECASE)
    dimensions = {}
    if dims:
        dimensions = {"length": float(dims.group(1)), "width": float(dims.group(2)), "unit": "mm"}

    flash_mb = _first_number(flat, [
        r"(\d+(?:\.\d+)?)\s*MB\s*flash\b",
        r"\bflash\b[^\d]{0,24}(\d+(?:\.\d+)?)\s*MB\b",
    ])
    psram_mb = _first_number(flat, [
        r"(\d+(?:\.\d+)?)\s*MB[^.]{0,12}\bPSRAM\b",
        r"\bPSRAM\b[^\d]{0,24}(\d+(?:\.\d+)?)\s*MB\b",
    ])
    sram_kb = _first_number(flat, [
        r"(\d+(?:\.\d+)?)\s*KB\s*SRAM\b",
        r"\bSRAM\b[^\d]{0,24}(\d+(?:\.\d+)?)\s*KB\b",
    ])
    clock_mhz = _first_number(flat, [r"(\d+(?:\.\d+)?)\s*MHz\b"])
    gpio_count = _first_number(flat, [
        r"(\d+)\s*[·/]\s*\d+\s*ADC\s*GPIO\b",
        r"\bGPIO\s*[·:/-]?\s*(\d+)\b",
        r"(\d+)\s*GPIO\b",
    ])

    usb_connector = ""
    if re.search(r"\bUSB-C\b", flat, re.IGNORECASE):
        usb_connector = "USB-C"
    elif re.search(r"\bMicro-USB\b", flat, re.IGNORECASE):
        usb_connector = "Micro-USB"

    datasheet_url = ""
    pinout_url = ""
    for anchor in soup.find_all("a", href=True):
        label = " ".join(anchor.stripped_strings).strip().lower()
        href = urljoin(source_url, anchor["href"])
        if not datasheet_url and "datasheet" in label:
            datasheet_url = href
        if not pinout_url and "pinout" in label:
            pinout_url = href

    compatibility = []
    for platform, pattern in [
        ("Arduino", r"\bArduino IDE\b"),
        ("PlatformIO", r"\bPlatformIO\b"),
        ("ESPHome", r"\bESPHome\b"),
    ]:
        if re.search(pattern, flat, re.IGNORECASE):
            compatibility.append({"platform": platform, "support_level": "full"})

    specifications = {
        "clock_mhz": int(clock_mhz) if clock_mhz and clock_mhz.is_integer() else clock_mhz,
        "sram_kb": sram_kb,
        "external_image_url": image_url,
        "datasheet_url": datasheet_url,
        "pinout_url": pinout_url,
        "source_url": canonical_url,
        "imported_from": "ESPBoards.dev",
    }
    specifications = {key: value for key, value in specifications.items() if value not in (None, "")}

    return {
        "source_type": "espboards",
        "source_name": "ESPBoards.dev",
        "source_url": canonical_url,
        "manufacturer": manufacturer,
        "name": name,
        "family": family,
        "variant": "",
        "description": description,
        "image_url": image_url,
        "mcu": family,
        "architecture": architecture,
        "flash_mb": flash_mb,
        "psram_mb": psram_mb,
        "ram_kb": sram_kb,
        "gpio_count": int(gpio_count) if gpio_count is not None else None,
        "wifi": bool(re.search(r"\bWi[ -]?Fi\b", flat, re.IGNORECASE)),
        "bluetooth": bool(re.search(r"\bBluetooth\b|\bBLE\b", flat, re.IGNORECASE)),
        "zigbee": bool(re.search(r"\bZigbee\b", flat, re.IGNORECASE)),
        "thread": bool(re.search(r"\bThread\b", flat, re.IGNORECASE)),
        "usb_connector": usb_connector,
        "dimensions_mm": dimensions,
        "specifications": specifications,
        "compatibility": compatibility,
    }


def preview_board_url(raw_url: str) -> dict:
    safe = validate_import_url(raw_url)
    if safe.host in ESPBOARDS_HOSTS:
        final_url, html = fetch_import_html(safe.url)
        return parse_espboards_html(final_url, html)
    raise ImporterError("No importer is available for that URL.")
