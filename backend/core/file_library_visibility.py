"""Keep the general Files library separate from private slicer storage.

FileAsset is still the encrypted, owner-scoped storage backend for slicer jobs
and native profiles. Visibility is a query concern, not a deletion or a change
to the assets referenced by SliceJob / SlicerProfile.

User uploads that are not registered as a slicer profile or private job output
continue to appear normally.
"""
from django.db.models import Q

from .models import SlicerProfile


def library_visible_assets(queryset, owner):
    """Return only explicitly library-visible FileAssets for this owner.

    Historical records are covered without a migration: older generated G-code
    uses category='other', and older native profiles have a SlicerProfile link
    but no private metadata marker. G-code explicitly saved to the library has
    category='gcode', whether chosen during slicing or promoted afterwards.
    """
    # PostgreSQL JSON-key lookups are NULL for missing keys. Applying a
    # negated OR directly to the library queryset excludes otherwise-visible
    # ordinary files with missing metadata keys (three-valued SQL logic).
    # Build a positive private-ID subquery, then exclude only matched IDs.
    # Files without slicer markers remain visible, including legacy uploads.
    from .models import FileAsset

    profile_assets = SlicerProfile.objects.filter(owner=owner).values("file_asset_id")
    private_ids = FileAsset.objects.filter(owner=owner).filter(
        Q(metadata__slicer_temporary=True)
        | Q(metadata__slicer_profile_internal=True)
        | Q(pk__in=profile_assets)
        | (Q(metadata__generated_by="makervault-slicer") & ~Q(category="gcode"))
    ).values("pk")
    return queryset.exclude(pk__in=private_ids)
