"""Read-only NDEF URL preview for browser-initiated NTAG215 writes.

No tag is programmed, no device operation is queued and no database row
changes in this endpoint. A later operation must independently authorize the
exact URL and tag before the firmware receives any write instruction.
"""
import ipaddress
import json
import re
from urllib.parse import urlsplit

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .models import MakerTag
from .maker_tags import TARGETS, resolve_tag_target
from django.core.exceptions import ValidationError

_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def _base_origin(value):
    """Validate a user-selected base origin, not an arbitrary redirect URL."""
    if not isinstance(value, str) or len(value) > 220 or value != value.strip():
        raise ValueError("Invalid address.")
    if any(ord(c) < 33 or ord(c) > 126 or c == "\\" for c in value):
        raise ValueError("Invalid address.")
    try:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("Use an HTTP or HTTPS address.")
        if parts.username is not None or parts.password is not None:
            raise ValueError("Credentials are not allowed in addresses.")
        if parts.path not in {"", "/"} or parts.query or parts.fragment:
            raise ValueError("Provide a base address without a path, query or fragment.")
        hostname, port = parts.hostname, parts.port
    except (ValueError, AttributeError) as exc:
        raise ValueError("Invalid address or port.") from exc
    if not hostname:
        raise ValueError("Hostname required.")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        if len(hostname) > 253 or not all(_HOST_LABEL.fullmatch(x) for x in hostname.rstrip(".").split(".")):
            raise ValueError("Invalid hostname.")
    authority = parts.netloc.rstrip("/")
    if hostname.endswith(".") or "%" in authority or authority.count("@"):
        raise ValueError("Invalid hostname.")
    return f"{parts.scheme}://{authority}", hostname, port


def _local_host(hostname):
    if hostname.lower() in {"localhost"} or hostname.lower().endswith((".local", ".localhost")):
        return True
    try:
        ip = ipaddress.ip_address(hostname)
        return not ip.is_global
    except ValueError:
        return "." not in hostname


@login_required
@require_POST
def ndef_preview(request, tag_id):
    if not request.user.has_perm("core.change_makertag"):
        return JsonResponse({"error": "Insufficient permissions."}, status=403)
    tag = MakerTag.objects.filter(
        pk=tag_id, owner=request.user, status="active", kind="nfc"
    ).first()
    if not tag:
        return JsonResponse({"error": "Active NFC Maker Tag not found."}, status=404)
    definition = TARGETS.get(tag.target_type)
    if not definition or not request.user.has_perm(f"core.view_{definition.model._meta.model_name}"):
        return JsonResponse({"error": "Tag target not accessible."}, status=404)
    try:
        resolve_tag_target(request.user, tag.target_type, tag.target_id)
    except ValidationError:
        return JsonResponse({"error": "Tag target not accessible."}, status=404)
    if len(request.body) > 1024:
        return JsonResponse({"error": "Request too large."}, status=413)
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict) or set(data) != {"origin", "override"}:
            raise ValueError("Invalid preview request.")
        source, _, _ = _base_origin(data["origin"])
        # A same-origin browser POST provides Origin; never trust a JSON origin
        # that disagrees with the browser's Origin header.
        header, _, _ = _base_origin(request.headers.get("Origin", ""))
        if source != header:
            raise ValueError("Browser origin mismatch.")
        chosen, hostname, _ = _base_origin(data["override"] or source)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return JsonResponse({"error": str(exc) or "Invalid preview request."}, status=400)
    url = f"{chosen}/t/MV-{tag.short_id}/"
    # Bounded for both the firmware response parser and Type 2 NDEF capacity.
    if len(url.encode("utf-8")) > 240:
        return JsonResponse({"error": "URL is too long for this operation."}, status=400)
    response = JsonResponse({
        "maker_tag_id": f"MV-{tag.short_id}",
        "url": url,
        "override": bool(data["override"]),
        "local_address_warning": _local_host(hostname),
        "write_started": False,
    })
    response["Cache-Control"] = "no-store"
    return response
