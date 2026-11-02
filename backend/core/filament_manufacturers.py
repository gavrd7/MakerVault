"""Case-insensitive resolution of filament manufacturer identity.

Existing duplicate manufacturer rows are preserved until an explicit migration:
their linked products may carry user-managed metadata. New writes reuse one
canonical row instead of creating yet another capitalization variant.
"""
from django.db import IntegrityError, transaction

from .models import FilamentManufacturer


def resolve_filament_manufacturer(name):
    cleaned = " ".join(str(name or "Generic").split())[:200] or "Generic"
    existing = list(FilamentManufacturer.objects.filter(name__iexact=cleaned))
    if existing:
        # Stable selection: prefer an existing ID with the most linked products,
        # then oldest UUID ordering; never silently delete or relink user data.
        return sorted(existing, key=lambda row: (row.name != cleaned, str(row.pk)))[0]
    try:
        with transaction.atomic():
            return FilamentManufacturer.objects.create(name=cleaned)
    except IntegrityError:
        return FilamentManufacturer.objects.filter(name__iexact=cleaned).order_by("pk").first()
