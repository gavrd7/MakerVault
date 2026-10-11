"""Reviewed additions and corrections to the shared reusable spool catalogue."""
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.utils.text import slugify
from django.views.decorators.http import require_http_methods

from .importers import ImporterError, fetch_catalogue_source_html
from .models import ReusableSpoolCatalogEntry, ReusableSpoolCatalogueSuggestion
from .reusable_spools import error, read_json

NUMERIC = ("nominal_tare_g", "outer_diameter_mm", "width_mm", "hub_diameter_mm", "capacity_g")
OTHER = ("material", "description", "max_dryer_temp_c", "temperature_source")
ALLOWED = NUMERIC + OTHER


def _specs(raw):
    if not isinstance(raw, dict) or set(raw) - set(ALLOWED):
        raise ValueError("Unsupported specification field.")
    clean = {}
    for key, value in raw.items():
        if value in ("", None):
            continue
        if key in NUMERIC:
            try:
                number = Decimal(str(value))
            except (InvalidOperation, ValueError, TypeError):
                raise ValueError(f"{key} must be a number.")
            if not number.is_finite() or number <= 0 or number > 100000:
                raise ValueError(f"{key} must be positive and within range.")
            clean[key] = str(number)
        elif key == "max_dryer_temp_c":
            if isinstance(value, bool) or not str(value).isdigit() or not 1 <= int(value) <= 200:
                raise ValueError("Dryer temperature must be between 1 and 200°C.")
            clean[key] = int(value)
        else:
            clean[key] = str(value).strip()[:1000 if key == "description" else 80 if key == "material" else 200]
    if "max_dryer_temp_c" in clean and not clean.get("temperature_source"):
        raise ValueError("Dryer temperature needs a source URL for the exact design.")
    if clean.get("temperature_source"):
        p = urlparse(clean["temperature_source"])
        if p.scheme != "https" or not p.hostname or p.username or p.password:
            raise ValueError("Temperature evidence must use a valid HTTPS URL.")
    return clean


@login_required
@require_http_methods(["GET", "POST"])
def suggestions(request):
    if request.method == "GET":
        qs = ReusableSpoolCatalogueSuggestion.objects.all() if request.user.is_staff else ReusableSpoolCatalogueSuggestion.objects.filter(owner=request.user)
        return JsonResponse({"can_review": bool(request.user.is_staff and request.user.has_perm("core.change_reusablespoolcatalogentry")), "rows": [
            {"id": x.id, "manufacturer": x.manufacturer, "name": x.name, "source_url": x.source_url,
             "status": x.status, "review_note": x.review_note, "proposed_specs": x.proposed_specs,
             "target_entry_key": x.target_entry.key if x.target_entry_id else None}
            for x in qs.order_by("-created_at")[:100]
        ]})
    if not request.user.has_perm("core.add_filamentproduct"):
        return error("Permission denied.", 403)
    try:
        data = read_json(request)
        manufacturer = str(data.get("manufacturer") or "").strip()[:120]
        name = str(data.get("name") or "").strip()[:200]
        source_url = str(data.get("source_url") or "").strip()[:500]
        design_type = str(data.get("design_type") or "manufacturer")
        specs = _specs(data.get("proposed_specs") or {})
        target_key = str(data.get("target_entry_key") or "").strip()
        target = ReusableSpoolCatalogEntry.objects.filter(key=target_key).first() if target_key else None
        if target_key and not target:
            raise ValueError("The catalogue entry to correct was not found.")
        if target and not specs:
            raise ValueError("Enter at least one proposed specification change.")
        if target and (manufacturer.casefold() != target.manufacturer.casefold() or name.casefold() != target.name.casefold()):
            raise ValueError("The manufacturer and model must match the selected catalogue entry.")
        if not manufacturer or not name or design_type not in ("manufacturer", "printed"):
            raise ValueError("Manufacturer, product name and design type are required.")
        parsed = urlparse(source_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError("Provide a valid public HTTPS product source.")
        if not target and ReusableSpoolCatalogEntry.objects.filter(manufacturer__iexact=manufacturer, name__iexact=name).exists():
            raise ValueError("This catalogue product already exists; propose corrections separately.")
        if ReusableSpoolCatalogueSuggestion.objects.filter(owner=request.user, manufacturer__iexact=manufacturer, name__iexact=name, status="pending").exists():
            raise ValueError("You already have a pending suggestion for this model.")
    except (ValueError, TypeError, ValidationError) as exc:
        return error(str(exc))
    with transaction.atomic():
        obj = ReusableSpoolCatalogueSuggestion.objects.create(owner=request.user, manufacturer=manufacturer, name=name, design_type=design_type, source_url=source_url, proposed_specs=specs, target_entry=target)
        if request.user.is_staff and request.user.has_perm("core.change_reusablespoolcatalogentry"):
            try:
                _apply_review(obj, request.user, "approve", "Automatically approved administrator submission.")
            except ValueError as exc:
                return error(str(exc))
    return JsonResponse({"id": obj.id, "status": obj.status}, status=201)


@login_required
@require_http_methods(["POST"])
def preview_source(request):
    if not request.user.has_perm("core.add_filamentproduct"):
        return error("Permission denied.", 403)
    try:
        url = str(read_json(request).get("url") or "")
        resolved, html = fetch_catalogue_source_html(url)
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.get_text(" ", strip=True)[:200] if soup.title else ""
    except (ImporterError, ValueError, OSError, ValidationError) as exc:
        return error(f"Unable to inspect approved catalogue source: {exc}")
    return JsonResponse({"source_url": resolved, "page_title": title, "note": "Page metadata only; specifications require review."})


def _apply_review(suggestion, reviewer, action, note=""):
    """Apply one approved suggestion; caller must hold a database transaction."""
    if action == "approve" and suggestion.target_entry_id:
        entry = ReusableSpoolCatalogEntry.objects.select_for_update().filter(pk=suggestion.target_entry_id).first()
        if entry is None:
            raise ValueError("Catalogue entry no longer exists.")
        if suggestion.source_url != entry.source_url:
            raise ValueError("Correction evidence must match the product source; update the source separately.")
        changes = dict(suggestion.proposed_specs)
        for field, value in changes.items():
            setattr(entry, field, value)
        provenance = dict(entry.provenance or {})
        history = list(provenance.get("reviewed_corrections") or [])
        history.append({"suggestion_id": suggestion.id, "fields": list(changes), "source_url": suggestion.source_url})
        provenance["reviewed_corrections"] = history[-30:]
        verified_fields = set(provenance.get("verified_fields") or [])
        provenance["verified_fields"] = sorted(verified_fields - set(changes))
        entry.provenance = provenance
        entry.save(update_fields=list(changes) + ["provenance", "updated_at"])
        entry_id = str(entry.id)
    elif action == "approve":
        if ReusableSpoolCatalogEntry.objects.filter(manufacturer__iexact=suggestion.manufacturer, name__iexact=suggestion.name).exists():
            raise ValueError("Matching product already exists; no duplicate created.")
        base = slugify(suggestion.manufacturer + "-" + suggestion.name)[:110] or "spool"
        key = base
        index = 2
        while ReusableSpoolCatalogEntry.objects.filter(key=key).exists():
            key = f"{base[:105]}-{index}"
            index += 1
        specs = dict(suggestion.proposed_specs)
        entry = ReusableSpoolCatalogEntry.objects.create(
            key=key, manufacturer=suggestion.manufacturer, name=suggestion.name,
            design_type=suggestion.design_type, source_url=suggestion.source_url,
            verified=False, provenance={"source_type": "user-suggested", "reviewed_suggestion_id": suggestion.id,
                                        "proposed_fields": list(specs)},
            **specs,
        )
        # Approval only means the item was accepted; user-proposed fields are not manufacturer-verified.
        entry_id = str(entry.id)
    else:
        entry_id = None
    suggestion.status = "approved" if action == "approve" else "rejected"
    suggestion.reviewed_by = reviewer
    suggestion.review_note = note[:1000]
    suggestion.save(update_fields=["status", "reviewed_by", "review_note", "updated_at"])
    return entry_id


@login_required
@require_http_methods(["POST"])
def review_suggestion(request, suggestion_id):
    if not request.user.is_staff or not request.user.has_perm("core.change_reusablespoolcatalogentry"):
        return error("Admin catalogue review required.", 403)
    try:
        payload = read_json(request)
        action = payload.get("action")
        if action not in ("approve", "reject"):
            raise ValueError("Choose approve or reject.")
        with transaction.atomic():
            suggestion = ReusableSpoolCatalogueSuggestion.objects.select_for_update().filter(pk=suggestion_id, status="pending").first()
            if suggestion is None:
                return error("Pending suggestion not found.", 404)
            entry_id = _apply_review(suggestion, request.user, action, str(payload.get("note") or "").strip())
    except (ValueError, TypeError, ValidationError) as exc:
        return error(str(exc))
    return JsonResponse({"status": suggestion.status, "catalogue_entry_id": entry_id})
