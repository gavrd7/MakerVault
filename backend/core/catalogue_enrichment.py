from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.text import slugify

from .importers import ImporterError, fetch_import_html, parse_espboards_html
from .catalogue_profiles import apply_board_profile


ENRICHMENT_VERSION = "0.3.8"


@dataclass
class EnrichmentResult:
    status: str
    processed: int
    enriched: int
    failed: int
    skipped: int

    def as_dict(self):
        return {
            "status": self.status,
            "processed": self.processed,
            "enriched": self.enriched,
            "failed": self.failed,
            "skipped": self.skipped,
        }


def _tokens(value: str) -> set[str]:
    stop = {"generic", "board", "development", "dev", "style", "mini", "module"}
    raw = re.findall(r"[a-z0-9]+", (value or "").lower())
    tokens = set()
    for token in raw:
        if len(token) <= 1 or token in stop:
            continue
        chip = re.fullmatch(r"(esp32)([a-z][0-9]?)", token)
        if chip:
            tokens.update(chip.groups())
            continue
        tokens.add(token)
    return tokens


def _slug_candidates(board) -> list[str]:
    maker = board.manufacturer.name if board.manufacturer else ""
    names = [board.name]
    if maker and board.name.lower().startswith(maker.lower() + " "):
        names.append(board.name[len(maker):].strip())
    names.append(re.sub(r"\([^)]*\)", "", board.name).strip())
    replacements = [
        ("Seeed Studio ", ""),
        ("Adafruit ", ""),
        ("Waveshare ", ""),
        ("Espressif ", ""),
    ]
    for old, new in replacements:
        names.append(board.name.replace(old, new))
    slugs = []
    for name in names:
        slug = slugify(name)
        if slug and slug not in slugs:
            slugs.append(slug)
    return slugs[:6]


def _is_esp_family(board) -> bool:
    text = " ".join([board.name or "", board.family or "", board.mcu or ""]).upper()
    return "ESP32" in text or "ESP8266" in text


def _merge_board_data(board, data) -> bool:
    changed = False
    field_map = {
        "family": "family",
        "mcu": "mcu",
        "architecture": "architecture",
        "flash_mb": "flash_mb",
        "psram_mb": "psram_mb",
        "ram_kb": "ram_kb",
        "gpio_count": "gpio_count",
        "usb_connector": "usb_connector",
        "dimensions_mm": "dimensions_mm",
    }
    for field, key in field_map.items():
        current = getattr(board, field)
        incoming = data.get(key)
        if incoming in (None, "", {}, []):
            continue
        if current in (None, "", {}, []):
            setattr(board, field, incoming)
            changed = True

    for field in ["wifi", "bluetooth", "zigbee", "thread"]:
        incoming = bool(data.get(field))
        if incoming and not getattr(board, field):
            setattr(board, field, True)
            changed = True

    incoming_specs = data.get("specifications") or {}
    current_specs = dict(board.specifications or {})
    merged_specs = dict(current_specs)
    for key, value in incoming_specs.items():
        if value in (None, "", {}, []):
            continue
        if merged_specs.get(key) in (None, "", {}, []):
            merged_specs[key] = value
    if data.get("source_url"):
        merged_specs["technical_source_url"] = data["source_url"]
        merged_specs["technical_source_provider"] = "ESPBoards.dev"
        merged_specs["technical_enriched_at"] = timezone.now().isoformat()
    if merged_specs != current_specs:
        board.specifications = merged_specs
        changed = True
    return changed


TRACKED_BOARD_FIELDS = (
    "mcu", "architecture", "flash", "psram", "ram", "gpio", "usb", "dimensions",
    "clock_mhz", "eeprom_kb", "cpu_cores", "operating_voltage", "pin_count",
    "adc_channels", "dac_channels", "uart_count", "spi_count", "i2c_count",
    "pwm_channels", "native_usb", "usb_capability", "wifi_standard",
    "bluetooth_generation", "ieee_802154", "pio_state_machines", "wireless",
)


def _tracked_board_values(board) -> dict:
    specs = board.specifications or {}
    radios = [name for enabled, name in (
        (board.wifi, "Wi-Fi"), (board.bluetooth, "Bluetooth"),
        (board.zigbee, "Zigbee"), (board.thread, "Thread"),
    ) if enabled]
    return {
        "mcu": board.mcu,
        "architecture": board.architecture,
        "flash": specs.get("flash_kb") if specs.get("flash_kb") is not None else board.flash_mb,
        "psram": board.psram_mb,
        "ram": board.ram_kb if board.ram_kb is not None else specs.get("sram_kb"),
        "gpio": board.gpio_count,
        "usb": board.usb_connector,
        "dimensions": board.dimensions_mm if board.dimensions_mm else None,
        "clock_mhz": specs.get("clock_mhz"),
        "eeprom_kb": specs.get("eeprom_kb"),
        "cpu_cores": specs.get("cpu_cores"),
        "operating_voltage": specs.get("operating_voltage"),
        "pin_count": specs.get("pin_count"),
        "adc_channels": specs.get("adc_channels"),
        "dac_channels": specs.get("dac_channels"),
        "uart_count": specs.get("uart_count"),
        "spi_count": specs.get("spi_count"),
        "i2c_count": specs.get("i2c_count"),
        "pwm_channels": specs.get("pwm_channels"),
        "native_usb": specs.get("native_usb"),
        "usb_capability": "USB OTG" if specs.get("usb_otg") is True else (
            "USB Serial/JTAG" if specs.get("usb_serial_jtag") is True else None
        ),
        "wifi_standard": specs.get("wifi_standard"),
        "bluetooth_generation": specs.get("bluetooth_generation"),
        "ieee_802154": specs.get("ieee_802154"),
        "pio_state_machines": specs.get("pio_state_machines"),
        "wireless": radios or None,
    }


def update_board_enrichment_state(board, *, save=True) -> bool:
    """Persist per-field known/unknown/not-applicable state for future enrichers."""
    specs = dict(board.specifications or {})
    not_applicable = set(specs.get("not_applicable_specs") or [])
    if {"wifi_standard", "bluetooth_generation", "ieee_802154"}.issubset(not_applicable):
        not_applicable.add("wireless")
    if specs.get("native_usb") is False and not specs.get("usb_otg") and not specs.get("usb_serial_jtag"):
        not_applicable.add("usb_capability")
    values = _tracked_board_values(board)
    state = {}
    unresolved = []
    for key in TRACKED_BOARD_FIELDS:
        value = values.get(key)
        if key in not_applicable:
            state[key] = "not_applicable"
        elif value is not None and value != "" and value != [] and value != {}:
            state[key] = "value"
        else:
            state[key] = "unknown"
            unresolved.append(key)

    old_state = specs.get("technical_field_status")
    old_unresolved = specs.get("technical_unresolved_fields")
    changed = (
        old_state != state
        or old_unresolved != unresolved
        or specs.get("technical_status_version") != ENRICHMENT_VERSION
    )
    if not changed:
        return False
    specs["technical_field_status"] = state
    specs["technical_unresolved_fields"] = unresolved
    specs["technical_status_version"] = ENRICHMENT_VERSION
    specs["technical_status_updated_at"] = datetime.now().astimezone().isoformat()
    board.specifications = specs
    if save:
        board.save(update_fields=["specifications", "updated_at"])
    return True


def enrich_board(board, *, online=True) -> bool:
    """Run safe curated enrichment, optional online enrichment, then refresh field status."""
    changed = enrich_board_from_profile(board)
    if online and _is_esp_family(board) and _online_attempt_due(board):
        _mark_online_attempt(board)
        changed = enrich_board_from_espboards(board) or changed
    changed = update_board_enrichment_state(board) or changed
    return changed


def enrich_board_from_profile(board) -> bool:
    """Fill missing board fields/specifications from curated technical profiles."""
    definition = {
        "manufacturer": board.manufacturer.name if board.manufacturer else "Generic",
        "name": board.name,
        "family": board.family,
        "mcu": board.mcu,
        "architecture": board.architecture,
        "flash_mb": board.flash_mb,
        "psram_mb": board.psram_mb,
        "ram_kb": board.ram_kb,
        "gpio_count": board.gpio_count,
        "wifi": board.wifi,
        "bluetooth": board.bluetooth,
        "zigbee": board.zigbee,
        "thread": board.thread,
        "usb_connector": board.usb_connector,
        "dimensions_mm": board.dimensions_mm,
        "specifications": dict(board.specifications or {}),
    }
    profiled = apply_board_profile(definition)
    changed = _merge_board_data(board, profiled)
    if changed:
        board.save()
    return changed


def _online_attempt_due(board) -> bool:
    specs = board.specifications or {}
    if specs.get("technical_source_provider") == "ESPBoards.dev" and specs.get("technical_enriched_at"):
        return False
    if specs.get("technical_attempt_version") != ENRICHMENT_VERSION:
        return True
    raw = specs.get("technical_last_attempt")
    if not raw:
        return True
    try:
        attempted = datetime.fromisoformat(raw)
        if timezone.is_naive(attempted):
            attempted = timezone.make_aware(attempted)
    except (TypeError, ValueError):
        return True
    retry_days = max(int(getattr(settings, "BOARD_ENRICHMENT_RETRY_DAYS", 14)), 1)
    return attempted < timezone.now() - timedelta(days=retry_days)


def _mark_online_attempt(board):
    specs = dict(board.specifications or {})
    specs["technical_attempt_version"] = ENRICHMENT_VERSION
    specs["technical_last_attempt"] = timezone.now().isoformat()
    board.specifications = specs
    board.save(update_fields=["specifications", "updated_at"])


def enrich_board_from_espboards(board) -> bool:
    wanted = _tokens(f"{board.manufacturer.name if board.manufacturer else ''} {board.name}")
    for slug in _slug_candidates(board):
        url = f"https://www.espboards.dev/esp32/{slug}/"
        try:
            final_url, html = fetch_import_html(url)
            data = parse_espboards_html(final_url, html)
        except ImporterError:
            continue

        found = _tokens(f"{data.get('manufacturer', '')} {data.get('name', '')}")
        overlap = len(wanted & found) / max(len(wanted), 1)
        if overlap < 0.45:
            continue

        from .models import CatalogSource

        source, _ = CatalogSource.objects.update_or_create(
            source_type="espboards",
            url=data["source_url"],
            defaults={
                "name": f"ESPBoards.dev — {data['name']}",
                "external_id": data["source_url"].rstrip("/").split("/")[-1],
                "raw_metadata": data,
                "last_checked_at": timezone.now(),
            },
        )
        changed = _merge_board_data(board, data)
        if board.source_id is None or (
            board.source and board.source.source_type == "manual"
            and board.source.name == "MakerVault starter catalogue"
        ):
            board.source = source
            changed = True
        elif board.source_id == source.id:
            changed = True

        if changed:
            board.save()
        return changed
    return False


def run_board_catalogue_enrichment(limit: int | None = None, force_retry: bool = False) -> dict:
    from .models import BoardModel

    if limit is None:
        limit = max(int(getattr(settings, "BOARD_ENRICHMENT_MAX_PER_RUN", 80)), 0)
    lock_key = f"makervault:board-catalogue-enrichment:{ENRICHMENT_VERSION}"
    if not cache.add(lock_key, "running", timeout=60 * 45):
        return EnrichmentResult("already-running", 0, 0, 0, 0).as_dict()

    processed = enriched = failed = skipped = 0
    try:
        queryset = BoardModel.objects.select_related("manufacturer", "source").order_by("manufacturer__name", "name")
        for board in queryset.iterator():
            if limit and processed >= limit:
                return EnrichmentResult("limit-reached", processed, enriched, failed, skipped).as_dict()

            processed += 1
            changed = False
            board_failed = False

            try:
                changed = enrich_board_from_profile(board) or changed
            except Exception:
                board_failed = True

            if _is_esp_family(board) and (force_retry or _online_attempt_due(board)):
                try:
                    _mark_online_attempt(board)
                    online_changed = enrich_board_from_espboards(board)
                    changed = online_changed or changed
                    if not online_changed:
                        board_failed = True
                except Exception:
                    board_failed = True

            try:
                changed = update_board_enrichment_state(board) or changed
            except Exception:
                board_failed = True

            enriched += int(changed)
            failed += int(board_failed)
            skipped += int(not changed and not board_failed)

        return EnrichmentResult("complete", processed, enriched, failed, skipped).as_dict()
    finally:
        cache.delete(lock_key)

