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
            clean[key] = str(value).strip()[:1000 if key == "description" else 500]
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
        return JsonResponse({"rows": [
            {"id": x.id, "manufacturer": x.manufacturer, "name": x.name, "source_url": x.source_url,
             "status": x.status, "review_note": x.review_note, "proposed_specs": x.proposed_specs}
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
        if not manufacturer or not name or design_type not in ("manufacturer", "printed"):
            raise ValueError("Manufacturer, product name and design type are required.")
        parsed = urlparse(source_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError("Provide a valid public HTTPS product source.")
        if ReusableSpoolCatalogEntry.objects.filter(manufacturer__iexact=manufacturer, name__iexact=name).exists():
            raise ValueError("This catalogue product already exists; propose corrections separately.")
        if ReusableSpoolCatalogueSuggestion.objects.filter(owner=request.user, manufacturer__iexact=manufacturer, name__iexact=name, status="pending").exists():
            raise ValueError("You already have a pending suggestion for this model.")
    except (ValueError, TypeError, ValidationError) as exc:
        return error(str(exc))
    obj = ReusableSpoolCatalogueSuggestion.objects.create(owner=request.user, manufacturer=manufacturer, name=name, design_type=design_type, source_url=source_url, proposed_specs=specs)
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
            if action == "approve":
                if ReusableSpoolCatalogEntry.objects.filter(manufacturer__iexact=suggestion.manufacturer, name__iexact=suggestion.name).exists():
                    return error("Matching product already exists; no duplicate created.")
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
            suggestion.reviewed_by = request.user
            suggestion.review_note = str(payload.get("note") or "").strip()[:1000]
            suggestion.save(update_fields=["status", "reviewed_by", "review_note", "updated_at"])
    except (ValueError, TypeError) as exc:
        return error(str(exc))
    return JsonResponse({"status": suggestion.status, "catalogue_entry_id": entry_id})
