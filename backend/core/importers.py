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
CATALOGUE_SOURCE_HOST_SUFFIXES = {
    "espboards.dev",
    "orangepi.org",
    "hardkernel.com",
    "radxa.com",
    "banana-pi.org",
    "beagleboard.org",
    "lattepanda.com",
    "nvidia.com",
    "khadas.com",
    "raspberrypi.com",
    "creality.com",
    "bambulab.com",
    "prusa3d.com",
    "anycubic.com",
    "flashforge.com",
    "elegoo.com",
    "qidi3d.com",
    "sovol3d.com",
    "snapmaker.com",
    "adafruit.com",
    "arduino.cc",
    "dfrobot.com",
    "elecrow.com",
    "espressif.com",
    "sparkfun.com",
    "seeedstudio.com",
    "waveshare.com",
    "m5stack.com",
    "lilygo.cc",
    "heltec.org",
}


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



def validate_catalogue_source_url(raw_url: str) -> SafeImportURL:
    """Validate an allow-listed catalogue source without widening user URL imports."""
    value = (raw_url or "").strip()
    if not value:
        raise ImporterError("Enter a catalogue source URL.")

    parsed = urlparse(value)
    if parsed.scheme != "https":
        raise ImporterError("MakerVault catalogue sources require an HTTPS URL.")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not any(host == suffix or host.endswith("." + suffix) for suffix in CATALOGUE_SOURCE_HOST_SUFFIXES):
        raise ImporterError("The catalogue source host is not allow-listed.")
    if parsed.port not in (None, 443):
        raise ImporterError("Non-standard ports are not permitted for catalogue sources.")
    if parsed.username or parsed.password:
        raise ImporterError("Credentials in catalogue source URLs are not permitted.")
    if not _host_is_public(host):
        raise ImporterError("The catalogue source URL resolved to a private or reserved address.")
    return SafeImportURL(url=value, host=host)


def _fetch_safe_html(raw_url: str, validator, *, user_agent: str) -> tuple[str, str]:
    current = validator(raw_url).url
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
        "Cache-Control": "no-cache",
    }

    for _ in range(5):
        safe = validator(current)
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


def fetch_catalogue_source_html(raw_url: str) -> tuple[str, str]:
    return _fetch_safe_html(
        raw_url,
        validate_catalogue_source_url,
        user_agent="Mozilla/5.0 (compatible; MakerVault/0.7; +self-hosted catalogue enrichment)",
    )

def fetch_import_html(raw_url: str) -> tuple[str, str]:
    # Deliberately retain the narrow ESPBoards-only validation for user-driven
    # URL imports. Catalogue enrichment uses fetch_catalogue_source_html().
    return _fetch_safe_html(
        raw_url,
        validate_import_url,
        user_agent="MakerVault/0.2 (+self-hosted catalogue importer)",
    )


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

    manufacturer = "Generic"
    by_match = re.search(r"(?im)^by\s+([^\n]{2,80})$", text)
    if by_match:
        manufacturer = by_match.group(1).strip()
    else:
        # ESPBoards commonly renders the manufacturer as "by <a>Maker</a>".
        # BeautifulSoup's newline separator can split that into separate text
        # nodes, so inspect compact nearby containers as a fallback.
        for tag in soup.find_all(["p", "div", "span", "section"]):
            label = " ".join(tag.stripped_strings).strip()
            candidate = re.fullmatch(r"by\s+(.{2,80})", label, re.IGNORECASE)
            if candidate:
                manufacturer = candidate.group(1).strip()
                break
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
    core_count = _first_number(flat, [
        r"(\d+)\s*(?:CPU\s*)?cores?\b",
        r"\bcores?\b[^\d]{0,12}(\d+)\b",
    ])
    adc_channels = _first_number(flat, [
        r"(\d+)\s*ADC\s*(?:channels?|pins?)\b",
        r"\bADC\b[^\d]{0,16}(\d+)\b",
    ])
    dac_channels = _first_number(flat, [
        r"(\d+)\s*DAC\s*(?:channels?|pins?)\b",
        r"\bDAC\b[^\d]{0,16}(\d+)\b",
    ])
    uart_count = _first_number(flat, [r"(\d+)\s*UART\b", r"\bUART\b[^\d]{0,12}(\d+)\b"])
    spi_count = _first_number(flat, [r"(\d+)\s*SPI\b", r"\bSPI\b[^\d]{0,12}(\d+)\b"])
    i2c_count = _first_number(flat, [r"(\d+)\s*I2C\b", r"\bI2C\b[^\d]{0,12}(\d+)\b"])
    pwm_channels = _first_number(flat, [
        r"(\d+)\s*PWM\s*(?:channels?|pins?)\b",
        r"\bPWM\b[^\d]{0,16}(\d+)\b",
    ])
    pin_count = _first_number(flat, [
        r"(\d+)\s*(?:total\s*)?pins?\b",
        r"\bpins?\b[^\d]{0,12}(\d+)\b",
    ])
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

    operating_voltage = ""
    voltage_match = re.search(r"(?:logic|operating|io)\s*voltage[^\d]{0,16}(\d+(?:\.\d+)?)\s*V", flat, re.IGNORECASE)
    if voltage_match:
        operating_voltage = f"{voltage_match.group(1)} V"
    elif re.search(r"\b3\.3\s*V\b", flat, re.IGNORECASE):
        operating_voltage = "3.3 V"

    specifications = {
        "clock_mhz": int(clock_mhz) if clock_mhz and clock_mhz.is_integer() else clock_mhz,
        "cpu_cores": int(core_count) if core_count is not None else None,
        "sram_kb": sram_kb,
        "adc_channels": int(adc_channels) if adc_channels is not None else None,
        "dac_channels": int(dac_channels) if dac_channels is not None else None,
        "uart_count": int(uart_count) if uart_count is not None else None,
        "spi_count": int(spi_count) if spi_count is not None else None,
        "i2c_count": int(i2c_count) if i2c_count is not None else None,
        "pwm_channels": int(pwm_channels) if pwm_channels is not None else None,
        "pin_count": int(pin_count) if pin_count is not None else None,
        "operating_voltage": operating_voltage,
        "native_usb": bool(re.search(r"\bnative\s+USB\b|\bUSB\s+OTG\b", flat, re.IGNORECASE)),
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
