"""Compatibility helpers for NFC / RFID identities.

Both legacy kinds represent radio tag identities. Keep the stored kind and
historical records unchanged while resolving and enforcing physical UID
conflicts across the two values.
"""
from django.db.models import Q

RADIO_KINDS = ("nfc", "rfid")


def radio_identity_query(kind, code):
    """Match either legacy radio kind for the same identifier."""
    if kind in RADIO_KINDS:
        return Q(kind__in=RADIO_KINDS, code=code)
    return Q(kind=kind, code=code)


def radio_tag_matches(queryset, kind, code):
    return queryset.filter(radio_identity_query(kind, code))
