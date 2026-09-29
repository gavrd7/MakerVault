from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable

from django.db.models import Q, QuerySet

from .models import (
    BoardModel,
    ComponentModel,
    FileAsset,
    FilamentProduct,
    InventoryItem,
    Model3D,
    Printer,
    Project,
    Spool,
)


SEARCH_TYPES = {
    "projects": "Projects",
    "inventory": "Inventory",
    "boards": "Board catalogue",
    "components": "Components",
    "files": "Files",
    "models": "3D models",
    "printers": "Printers",
    "spools": "Spools",
    "filaments": "Filaments",
}


def _terms(raw: str) -> list[str]:
    return [part.strip() for part in str(raw or "").split() if part.strip()][:8]


def _filter_terms(queryset: QuerySet, terms: Iterable[str], fields: Iterable[str]) -> QuerySet:
    for term in terms:
        clause = Q()
        for field in fields:
            clause |= Q(**{f"{field}__icontains": term})
        queryset = queryset.filter(clause)
    return queryset


def _iso(value) -> str | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _score(query: str, title: str, subtitle: str = "", extra: str = "") -> int:
    needle = str(query or "").strip().casefold()
    if not needle:
        return 0
    title0 = str(title or "").casefold()
    subtitle0 = str(subtitle or "").casefold()
    extra0 = str(extra or "").casefold()
    score = 0
    if title0 == needle:
        score += 1000
    elif title0.startswith(needle):
        score += 700
    elif needle in title0:
        score += 500
    if needle in subtitle0:
        score += 180
    if needle in extra0:
        score += 80
    for term in _terms(needle):
        if title0.startswith(term):
            score += 90
        elif term in title0:
            score += 60
        elif term in subtitle0:
            score += 25
        elif term in extra0:
            score += 10
    return score


@dataclass
class SearchResult:
    type: str
    id: str
    title: str
    subtitle: str
    section: str
    status: str = ""
    project_id: str | None = None
    updated_at: str | None = None
    badge: str = ""
    extra: str = ""

    def as_dict(self, query: str) -> dict:
        return {
            "type": self.type,
            "type_label": SEARCH_TYPES[self.type],
            "id": self.id,
            "title": self.title,
            "subtitle": self.subtitle,
            "section": self.section,
            "status": self.status,
            "project_id": self.project_id,
            "updated_at": self.updated_at,
            "badge": self.badge,
            "score": _score(query, self.title, self.subtitle, self.extra),
        }


def _project_results(user, terms, *, project_id=None, status=None):
    qs = Project.objects.filter(owner=user)
    if project_id:
        qs = qs.filter(pk=project_id)
    if status:
        qs = qs.filter(status=status)
    qs = _filter_terms(qs, terms, ("name", "summary", "description", "notes", "slug"))
    for row in qs[:200]:
        yield SearchResult(
            "projects", str(row.id), row.name,
            row.summary or row.get_status_display(),
            "Projects",
            status=row.get_status_display(),
            project_id=str(row.id),
            updated_at=_iso(row.updated_at),
            badge=row.get_status_display(),
            extra=" ".join(str(x) for x in (row.tags or [])),
        )


def _inventory_results(user, terms, *, project_id=None, status=None):
    qs = InventoryItem.objects.filter(owner=user).select_related("board", "board__manufacturer", "component", "project")
    if project_id:
        qs = qs.filter(project_id=project_id)
    if status:
        qs = qs.filter(status=status)
    qs = _filter_terms(
        qs, terms,
        (
            "inventory_id", "custom_name", "location", "serial_number", "supplier",
            "notes", "board__name", "board__manufacturer__name", "component__name",
            "project__name",
        ),
    )
    for row in qs[:200]:
        yield SearchResult(
            "inventory", str(row.id), row.display_name,
            " · ".join(filter(None, [row.inventory_id, row.get_item_type_display(), row.project.name if row.project else ""])),
            "Inventory",
            status=row.get_status_display(),
            project_id=str(row.project_id) if row.project_id else None,
            updated_at=_iso(row.updated_at),
            badge=row.inventory_id,
            extra=" ".join(filter(None, [row.location, row.serial_number, row.supplier, row.notes])),
        )


def _board_results(terms, *, manufacturer=None):
    qs = BoardModel.objects.select_related("manufacturer")
    if manufacturer:
        qs = qs.filter(manufacturer__name__iexact=manufacturer)
    qs = _filter_terms(qs, terms, ("name", "variant", "family", "mcu", "architecture", "description", "manufacturer__name"))
    for row in qs[:200]:
        maker = row.manufacturer.name if row.manufacturer else "Generic"
        yield SearchResult(
            "boards", str(row.id), str(row),
            " · ".join(filter(None, [row.family, row.variant, row.mcu])),
            "Board Catalogue",
            updated_at=_iso(row.updated_at),
            badge=maker,
            extra=" ".join(filter(None, [row.description, row.architecture, row.usb_connector])),
        )


def _component_results(terms):
    qs = ComponentModel.objects.select_related("category")
    qs = _filter_terms(qs, terms, ("name", "part_number", "description", "category__name"))
    for row in qs[:200]:
        yield SearchResult(
            "components", str(row.id), row.name,
            " · ".join(filter(None, [row.category.name if row.category else "", row.part_number])),
            "Components",
            updated_at=_iso(row.updated_at),
            badge=row.category.name if row.category else "Component",
            extra=row.description,
        )


def _file_results(user, terms, *, project_id=None):
    qs = FileAsset.objects.filter(owner=user).select_related("project")
    if project_id:
        qs = qs.filter(project_id=project_id)
    qs = _filter_terms(qs, terms, ("name", "description", "version", "sha256", "project__name"))
    for row in qs[:200]:
        original = str((row.metadata or {}).get("original_name") or row.name)
        yield SearchResult(
            "files", str(row.id), row.name,
            " · ".join(filter(None, [original, row.get_category_display(), row.project.name if row.project else ""])),
            "Files",
            project_id=str(row.project_id) if row.project_id else None,
            updated_at=_iso(row.updated_at),
            badge=row.get_category_display(),
            extra=" ".join(filter(None, [row.description, row.version, row.sha256])),
        )


def _model_results(user, terms, *, project_id=None):
    qs = Model3D.objects.filter(owner=user).select_related("project")
    if project_id:
        qs = qs.filter(project_id=project_id)
    qs = _filter_terms(qs, terms, ("name", "description", "license", "project__name"))
    for row in qs[:200]:
        yield SearchResult(
            "models", str(row.id), row.name,
            " · ".join(filter(None, [row.project.name if row.project else "", row.license])),
            "3D Printing",
            project_id=str(row.project_id) if row.project_id else None,
            updated_at=_iso(row.updated_at),
            badge="3D model",
            extra=" ".join([row.description, " ".join(str(x) for x in (row.tags or []))]),
        )


def _printer_results(user, terms):
    qs = Printer.objects.filter(owner=user).select_related("printer_manufacturer", "manufacturer", "printing_location")
    qs = _filter_terms(
        qs, terms,
        ("name", "model", "serial_number", "location", "connection_host", "printer_manufacturer__name", "manufacturer__name", "printing_location__name"),
    )
    for row in qs[:200]:
        maker = row.printer_manufacturer or row.manufacturer
        yield SearchResult(
            "printers", str(row.id), row.name,
            " · ".join(filter(None, [str(maker) if maker else "", row.model, row.location])),
            "3D Printing",
            status="Active" if row.is_active else "Inactive",
            updated_at=_iso(row.updated_at),
            badge="Printer",
            extra=" ".join(filter(None, [row.serial_number, row.connection_host, row.notes])),
        )


def _spool_results(user, terms, *, status=None):
    qs = Spool.objects.filter(owner=user).select_related(
        "filament", "filament__filament_manufacturer", "filament__manufacturer", "storage_location", "assigned_printer"
    )
    if status:
        qs = qs.filter(status=status)
    qs = _filter_terms(
        qs, terms,
        ("spool_id", "rfid_uid", "location", "notes", "filament__name", "filament__material", "filament__color_name", "storage_location__name", "assigned_printer__name"),
    )
    for row in qs[:200]:
        yield SearchResult(
            "spools", str(row.id), row.spool_id,
            " · ".join(filter(None, [str(row.filament), row.filament.material, row.storage_location.name if row.storage_location else row.location, row.assigned_printer.name if row.assigned_printer else ""])),
            "3D Printing",
            status=row.get_status_display(),
            updated_at=_iso(row.updated_at),
            badge=row.get_status_display(),
            extra=" ".join(filter(None, [row.rfid_uid, row.notes])),
        )


def _filament_results(terms, *, manufacturer=None):
    qs = FilamentProduct.objects.select_related("filament_manufacturer", "manufacturer")
    if manufacturer:
        qs = qs.filter(
            Q(filament_manufacturer__name__iexact=manufacturer) |
            Q(manufacturer__name__iexact=manufacturer)
        )
    qs = _filter_terms(
        qs, terms,
        ("name", "material", "color_name", "finish", "pattern", "filament_manufacturer__name", "manufacturer__name"),
    )
    for row in qs[:200]:
        maker = row.filament_manufacturer or row.manufacturer
        yield SearchResult(
            "filaments", str(row.id), str(row),
            " · ".join(filter(None, [row.material, row.finish, row.transparency])),
            "3D Printing",
            updated_at=_iso(row.updated_at),
            badge=str(maker) if maker else "Filament",
            extra=" ".join(filter(None, [row.color_name, row.pattern])),
        )


BUILDERS: dict[str, Callable] = {
    "projects": _project_results,
    "inventory": _inventory_results,
    "boards": _board_results,
    "components": _component_results,
    "files": _file_results,
    "models": _model_results,
    "printers": _printer_results,
    "spools": _spool_results,
    "filaments": _filament_results,
}


def run_search(
    user,
    *,
    query: str = "",
    selected_types: Iterable[str] | None = None,
    sort: str = "relevance",
    limit_per_type: int = 25,
    project_id: str | None = None,
    status: str | None = None,
    manufacturer: str | None = None,
) -> dict:
    query = str(query or "").strip()[:200]
    terms = _terms(query)
    types = [item for item in (selected_types or SEARCH_TYPES.keys()) if item in SEARCH_TYPES]
    if not types:
        types = list(SEARCH_TYPES)

    limit_per_type = min(max(int(limit_per_type or 25), 1), 100)
    items = []

    for type_name in types:
        builder = BUILDERS[type_name]
        kwargs = {}
        if type_name in {"projects", "inventory", "files", "models"}:
            kwargs["project_id"] = project_id
        if type_name in {"projects", "inventory", "spools"}:
            kwargs["status"] = status
        if type_name in {"boards", "filaments"}:
            kwargs["manufacturer"] = manufacturer

        if type_name in {"boards", "components", "filaments"}:
            generated = builder(terms, **kwargs)
        else:
            generated = builder(user, terms, **kwargs)
        rows = [result.as_dict(query) for result in generated]

        if sort == "name":
            rows.sort(key=lambda row: (row["title"].casefold(), row["type_label"]))
        elif sort == "newest":
            rows.sort(key=lambda row: row["updated_at"] or "", reverse=True)
        elif sort == "oldest":
            rows.sort(key=lambda row: row["updated_at"] or "")
        else:
            rows.sort(key=lambda row: (-row["score"], row["title"].casefold()))

        items.extend(rows[:limit_per_type])

    if sort == "name":
        items.sort(key=lambda row: (row["title"].casefold(), row["type_label"]))
    elif sort == "newest":
        items.sort(key=lambda row: row["updated_at"] or "", reverse=True)
    elif sort == "oldest":
        items.sort(key=lambda row: row["updated_at"] or "")
    else:
        items.sort(key=lambda row: (-row["score"], row["type_label"], row["title"].casefold()))

    groups = {}
    for row in items:
        groups.setdefault(row["type"], []).append(row)

    return {
        "query": query,
        "sort": sort,
        "types": [{"value": key, "label": value} for key, value in SEARCH_TYPES.items()],
        "total": len(items),
        "rows": items,
        "groups": groups,
    }
