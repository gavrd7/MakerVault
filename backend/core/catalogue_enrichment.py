from __future__ import annotations

import re
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.text import slugify

from .importers import ImporterError, fetch_import_html, parse_espboards_html


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
    return {
        token
        for token in re.findall(r"[a-z0-9]+", (value or "").lower())
        if len(token) > 1 and token not in stop
    }


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
        "description": "description",
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


def run_board_catalogue_enrichment(limit: int | None = None) -> dict:
    from .models import BoardModel

    if limit is None:
        limit = max(int(getattr(settings, "BOARD_ENRICHMENT_MAX_PER_RUN", 80)), 0)
    lock_key = "makervault:board-catalogue-enrichment:v0.3"
    if not cache.add(lock_key, "running", timeout=60 * 45):
        return EnrichmentResult("already-running", 0, 0, 0, 0).as_dict()

    processed = enriched = failed = skipped = 0
    try:
        queryset = BoardModel.objects.select_related("manufacturer", "source").order_by("manufacturer__name", "name")
        for board in queryset.iterator():
            if limit and processed >= limit:
                return EnrichmentResult("limit-reached", processed, enriched, failed, skipped).as_dict()
            if not _is_esp_family(board):
                skipped += 1
                continue
            specs = board.specifications or {}
            if specs.get("technical_source_provider") == "ESPBoards.dev" and specs.get("technical_enriched_at"):
                skipped += 1
                continue
            processed += 1
            try:
                if enrich_board_from_espboards(board):
                    enriched += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
        return EnrichmentResult("complete", processed, enriched, failed, skipped).as_dict()
    finally:
        cache.delete(lock_key)
