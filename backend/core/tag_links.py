"""Phone-tappable Maker Tag links based on permanent short identities.

The NDEF payload contains a stable MV-XXXXXXXX identity, not a target record.
A signed-in owner resolves it to the existing owner-scoped application scan.
"""
import re

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseRedirect
from django.views.decorators.http import require_GET

from .maker_tags import TARGETS, resolve_tag_target
from .models import MakerTag
from django.core.exceptions import ValidationError


SHORT_ID_RE = re.compile(r"MV-([0-9A-F]{8})", re.IGNORECASE)


@login_required
@require_GET
def maker_tag_link(request, maker_tag_id):
    match = SHORT_ID_RE.fullmatch(maker_tag_id)
    if not match:
        raise Http404("Maker Tag not found.")

    tag = MakerTag.objects.filter(
        owner=request.user,
        short_id=match.group(1).upper(),
        status="active",
    ).first()
    if tag is None or tag.target_type not in TARGETS:
        raise Http404("Maker Tag not found.")

    definition = TARGETS[tag.target_type]
    if not request.user.has_perm("core.view_makertag") or not request.user.has_perm(
        f"core.view_{definition.model._meta.model_name}"
    ):
        raise Http404("Maker Tag not found.")
    try:
        resolve_tag_target(request.user, tag.target_type, tag.target_id)
    except ValidationError as exc:
        raise Http404("Maker Tag not found.") from exc

    # Keep existing app scan behaviour and its permission checks unchanged.
    response = HttpResponseRedirect(f"/?tag={tag.public_token}")
    response["Cache-Control"] = "no-store"
    return response
