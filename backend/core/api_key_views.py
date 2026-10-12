"""Session-authenticated, owner-scoped API key management.

Bearer authentication is intentionally NOT enabled by these endpoints.
"""
from __future__ import annotations

import json
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .device_api_keys import generate_token, validate_scopes
from .models import UserApiKey


def _metadata(key):
    return {
        "id": str(key.id),
        "name": key.name,
        "prefix": f"mvk_{key.identifier}",
        "scopes": key.scopes,
        "created_at": key.created_at.isoformat(),
        "expires_at": key.expires_at.isoformat() if key.expires_at else None,
        "revoked_at": key.revoked_at.isoformat() if key.revoked_at else None,
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        "active": key.is_active(),
    }


def _error(message, status=400):
    return JsonResponse({"error": message}, status=status)


@login_required
@require_http_methods(["GET", "POST"])
def api_keys(request):
    if request.method == "GET":
        rows = UserApiKey.objects.filter(owner=request.user)[:250]
        return JsonResponse({"rows": [_metadata(row) for row in rows]})

    if not request.user.is_active:
        return _error("Account is inactive.", 403)

    try:
        payload = json.loads(request.body or b"{}")
        if not isinstance(payload, dict):
            return _error("Expected a JSON object.")
        name = str(payload.get("name") or "").strip()
        if not (1 <= len(name) <= 120):
            return _error("Key name must contain 1–120 characters.")
        scopes = list(validate_scopes(payload.get("scopes")))
        days = payload.get("expires_in_days")
        if days is None:
            expires_at = None
        elif type(days) is int and 1 <= days <= 3650:
            expires_at = timezone.now() + timedelta(days=days)
        else:
            return _error("Expiration must be 1–3650 days or null.")
    except (ValueError, UnicodeDecodeError, TypeError):
        return _error("Invalid key configuration.")

    # The plaintext value exists only during this response. Never log it.
    with transaction.atomic():
        issued = generate_token()
        key = UserApiKey(
            owner=request.user, name=name, identifier=issued.identifier,
            secret_digest=issued.digest, scopes=scopes, expires_at=expires_at,
        )
        key.full_clean(exclude=["created_at"])
        key.save()
    return JsonResponse({"item": _metadata(key), "token": issued.plaintext}, status=201)


@login_required
@require_http_methods(["POST"])
def revoke_api_key(request, key_id):
    with transaction.atomic():
        key = UserApiKey.objects.select_for_update().filter(
            owner=request.user, pk=key_id,
        ).first()
        if key is None:
            return _error("API key not found.", 404)
        if key.revoked_at is None:
            key.revoked_at = timezone.now()
            key.save(update_fields=["revoked_at", "updated_at"])
    return JsonResponse({"item": _metadata(key)})


@login_required
@require_http_methods(["DELETE"])
def delete_api_key(request, key_id):
    """Delete only a revoked key; active credentials must first be revoked."""
    with transaction.atomic():
        key = UserApiKey.objects.select_for_update().filter(
            owner=request.user, pk=key_id,
        ).first()
        if key is None:
            return _error("API key not found.", 404)
        if key.revoked_at is None:
            return _error("Revoke this API key before deleting it.", 409)
        key.delete()
    return JsonResponse({"deleted": True})
