from __future__ import annotations

from .catalogue_enrichment import TRACKED_BOARD_FIELDS, _tracked_board_values
from .catalogue_source_policy import classify_source_url
from .models import BoardModel, ComponentModel, FilamentProduct, PrinterCatalogModel


def _pct(value: int, total: int) -> float:
    if not total:
        return 100.0
    return round((value / total) * 100.0, 1)


def _metric(key: str, label: str, complete: int, total: int) -> dict:
    return {
        "key": key,
        "label": label,
        "complete": int(complete),
        "missing": max(int(total) - int(complete), 0),
        "total": int(total),
        "percent": _pct(int(complete), int(total)),
    }


def _board_coverage() -> dict:
    rows = list(BoardModel.objects.select_related("manufacturer", "source").all())
    total = len(rows)

    def authoritative_source(row):
        specs = row.specifications or {}
        url = str(
            specs.get("technical_source_url")
            or specs.get("reference_url")
            or getattr(row.source, "url", "")
            or ""
        ).strip()
        if not url:
            return False
        source_type = str(getattr(row.source, "source_type", "") or "")
        return classify_source_url(url, source_type=source_type).priority <= 30

    def has_image(row):
        specs = row.specifications or {}
        return bool(row.image or specs.get("external_image_url"))

    with_image = sum(has_image(row) for row in rows)
    core_complete = 0
    resolved_technical = 0
    technical_slots = total * len(TRACKED_BOARD_FIELDS)
    missing_samples = []

    for board in rows:
        specs = board.specifications or {}

        core_values = [
            board.name,
            board.family,
            board.mcu,
            board.architecture,
            board.gpio_count,
            board.usb_connector,
            board.dimensions_mm,
        ]
        if all(value not in (None, "", {}, []) for value in core_values):
            core_complete += 1

        states = specs.get("technical_field_status") or {}
        if not states:
            values = _tracked_board_values(board)
            not_applicable = set(specs.get("not_applicable_specs") or [])
            states = {
                key: (
                    "not_applicable" if key in not_applicable
                    else "value" if values.get(key) not in (None, "", {}, [])
                    else "unknown"
                )
                for key in TRACKED_BOARD_FIELDS
            }
        resolved_technical += sum(
            1 for key in TRACKED_BOARD_FIELDS
            if states.get(key) in {"value", "not_applicable"}
        )

        unresolved = [key for key in TRACKED_BOARD_FIELDS if states.get(key) not in {"value", "not_applicable"}]
        if (not has_image(board) or unresolved) and len(missing_samples) < 12:
            missing_samples.append({
                "id": str(board.id),
                "name": str(board),
                "missing_image": not has_image(board),
                "unresolved_fields": unresolved[:8],
            })

    return {
        "key": "boards",
        "label": "Board catalogue",
        "total": total,
        "metrics": [
            _metric("images", "Images", with_image, total),
            _metric("core", "Core specifications", core_complete, total),
            _metric("technical", "Technical fields resolved", resolved_technical, technical_slots),
            _metric("sources", "Authoritative sources", sum(authoritative_source(row) for row in rows), total),
        ],
        "missing_samples": missing_samples,
    }


def _component_coverage() -> dict:
    rows = list(ComponentModel.objects.select_related("category", "source").all())
    total = len(rows)

    def authoritative_source(row):
        specs = row.specifications or {}
        url = str(specs.get("reference_url") or getattr(row.source, "url", "") or "").strip()
        if not url:
            return False
        source_type = str(getattr(row.source, "source_type", "") or "")
        return classify_source_url(url, source_type=source_type).priority <= 30

    def has_image(row):
        specs = row.specifications or {}
        return bool(row.image or specs.get("external_image_url"))

    samples = []
    for row in rows:
        missing = []
        if not has_image(row):
            missing.append("image")
        if not row.category_id:
            missing.append("category")
        if not str(row.description or "").strip():
            missing.append("description")
        if not (row.specifications or {}):
            missing.append("specifications")
        if missing and len(samples) < 12:
            samples.append({"id": str(row.id), "name": row.name, "missing": missing})

    return {
        "key": "components",
        "label": "Components",
        "total": total,
        "metrics": [
            _metric("images", "Images", sum(has_image(row) for row in rows), total),
            _metric("category", "Category", sum(bool(row.category_id) for row in rows), total),
            _metric("description", "Descriptions", sum(bool(str(row.description or "").strip()) for row in rows), total),
            _metric("specifications", "Specifications", sum(bool(row.specifications or {}) for row in rows), total),
            _metric("sources", "Authoritative sources", sum(authoritative_source(row) for row in rows), total),
        ],
        "missing_samples": samples,
    }


def _printer_coverage() -> dict:
    rows = list(PrinterCatalogModel.objects.select_related("manufacturer").all())
    total = len(rows)
    samples = []

    def has_base_image(row):
        metadata = row.image_metadata or {}
        return bool(
            row.image
            or metadata.get("external_image_url")
            or (row.features or {}).get("official_image_url")
        )

    def has_multi_material_image(row):
        metadata = row.image_multi_material_metadata or {}
        return bool(
            row.image_multi_material
            or metadata.get("external_image_url")
            or (row.features or {}).get("official_image_multi_material_url")
        )

    for row in rows:
        missing = []
        if not has_base_image(row):
            missing.append("image")
        if any(value is None for value in (row.build_volume_x_mm, row.build_volume_y_mm, row.build_volume_z_mm)):
            missing.append("build_volume")
        if not (row.features or {}):
            missing.append("features")
        if not row.source_url:
            missing.append("source")
        if row.multi_material_system and not has_multi_material_image(row):
            missing.append("multi_material_image")
        if missing and len(samples) < 12:
            samples.append({"id": str(row.id), "name": str(row), "missing": missing})

    return {
        "key": "printers",
        "label": "Printer catalogue",
        "total": total,
        "metrics": [
            _metric("images", "Images", sum(has_base_image(row) for row in rows), total),
            _metric(
                "build_volume",
                "Build volumes",
                sum(all(value is not None for value in (row.build_volume_x_mm, row.build_volume_y_mm, row.build_volume_z_mm)) for row in rows),
                total,
            ),
            _metric("features", "Feature metadata", sum(bool(row.features or {}) for row in rows), total),
            _metric("source", "Source links", sum(bool(row.source_url) for row in rows), total),
        ],
        "missing_samples": samples,
    }


def _filament_coverage() -> dict:
    rows = list(FilamentProduct.objects.select_related(
        "filament_manufacturer", "manufacturer", "source"
    ).all())
    total = len(rows)
    samples = []

    def profile(row):
        return dict(row.profile_data or {})

    def provenance(row):
        return dict(profile(row).get("catalogue_provenance") or {})

    def has_image(row):
        metadata = row.image_metadata or {}
        return bool(row.image or metadata.get("external_image_url"))

    def has_source(row):
        data = provenance(row)
        return bool(
            data.get("product_url")
            or data.get("tds_url")
            or getattr(row.source, "url", "")
        )

    for row in rows:
        missing = []
        if not has_image(row):
            missing.append("image")
        if not (row.filament_manufacturer_id or row.manufacturer_id):
            missing.append("manufacturer")
        if not row.color_name and not row.color_hex and not row.color_hexes:
            missing.append("colour")
        if row.density_g_cm3 is None:
            missing.append("density")
        if row.nominal_weight_g is None:
            missing.append("weight")
        if any(value is None for value in (
            row.nozzle_temp_min_c,
            row.nozzle_temp_max_c,
            row.bed_temp_min_c,
            row.bed_temp_max_c,
        )):
            missing.append("temperatures")
        if not has_source(row):
            missing.append("source")
        if missing and len(samples) < 12:
            samples.append({"id": str(row.id), "name": str(row), "missing": missing})

    return {
        "key": "filaments",
        "label": "Filament catalogue",
        "total": total,
        "metrics": [
            _metric("images", "Images", sum(has_image(row) for row in rows), total),
            _metric(
                "manufacturer",
                "Manufacturer",
                sum(bool(row.filament_manufacturer_id or row.manufacturer_id) for row in rows),
                total,
            ),
            _metric(
                "colour",
                "Colour data",
                sum(bool(row.color_name or row.color_hex or row.color_hexes) for row in rows),
                total,
            ),
            _metric("density", "Density", sum(row.density_g_cm3 is not None for row in rows), total),
            _metric("weight", "Nominal weight", sum(row.nominal_weight_g is not None for row in rows), total),
            _metric(
                "temperatures",
                "Print temperatures",
                sum(all(value is not None for value in (
                    row.nozzle_temp_min_c,
                    row.nozzle_temp_max_c,
                    row.bed_temp_min_c,
                    row.bed_temp_max_c,
                )) for row in rows),
                total,
            ),
            _metric("sources", "Source links", sum(has_source(row) for row in rows), total),
        ],
        "missing_samples": samples,
    }


def catalogue_coverage_summary() -> dict:
    catalogues = [
        _board_coverage(),
        _component_coverage(),
        _printer_coverage(),
        _filament_coverage(),
    ]
    return {
        "catalogues": catalogues,
        "records": sum(item["total"] for item in catalogues),
    }
