"""Conservative official-source image discovery for shared reusable spool designs.

Only manufacturer source pages already trusted by MakerVault may be fetched;
all suggested images pass the existing public-IP / image-sanitization cache.
"""
import re
from datetime import timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from django.utils import timezone

from .catalogue_images import CatalogueImageError, cache_catalogue_image_from_url
from .importers import ImporterError, fetch_catalogue_source_html
from .models import ReusableSpoolCatalogEntry


def _tokens(value):
    return set(re.findall(r"[a-z0-9]+", str(value or "").casefold())) - {
        "the", "and", "for", "official", "shop", "store", "new", "model", "with", "3d"
    }


def official_image_candidate(entry, html, source_url):
    """Reject generic preview images on unrelated manufacturer/article pages."""
    soup = BeautifulSoup(html, "html.parser")
    robots = soup.find("meta", attrs={"name": re.compile("^robots$", re.I)})
    if robots and "noimageindex" in str(robots.get("content") or "").lower():
        return None
    title_meta = soup.find("meta", attrs={"property": "og:title"})
    title = str(title_meta.get("content") or "") if title_meta else ""
    title = title or (soup.title.get_text(" ", strip=True) if soup.title else "")
    model_tokens = _tokens(entry.name) - _tokens(entry.manufacturer)
    title_tokens = _tokens(title)
    # The brand name by itself is never enough: require relevant spool-model
    # terms as well. Generic manufacturer homepages must not be used.
    overlap = model_tokens & title_tokens
    if len(overlap) < min(2, len(model_tokens)):
        return None
    image_meta = soup.find("meta", attrs={"property": "og:image"})
    if not image_meta:
        image_meta = soup.find("meta", attrs={"name": "twitter:image"})
    if not image_meta:
        return None
    raw = str(image_meta.get("content") or "").strip()
    if not raw or raw.startswith("data:"):
        return None
    return urljoin(source_url, raw)


def refresh_reusable_spool_images(*, limit=3, retry_days=7):
    now = timezone.now()
    saved = checked = failed = skipped = 0
    # ImageField can be stored as NULL or an empty string.
    qs = ReusableSpoolCatalogEntry.objects.exclude(source_url="").order_by("key")
    # Prioritise never-attempted entries even when a low per-run limit is used.
    # This prevents repeated runs from starving entries after earlier failures.
    pending = [item for item in qs if not item.image]
    pending.sort(key=lambda item: (
        bool((item.provenance or {}).get("last_image_attempt_at")),
        str((item.provenance or {}).get("last_image_attempt_at") or ""),
        item.key,
    ))
    for item in pending:
        if checked >= max(0, min(int(limit), 10)):
            break
        if item.image:
            continue
        meta = dict(item.provenance or {})
        last = meta.get("last_image_attempt_at")
        if last:
            try:
                from datetime import datetime
                if datetime.fromisoformat(last) > now - timedelta(days=retry_days):
                    skipped += 1
                    continue
            except (TypeError, ValueError):
                pass
        checked += 1
        status = "no-reviewed-image"
        failure_reason = ""
        try:
            final_url, html = fetch_catalogue_source_html(item.source_url)
            candidate = official_image_candidate(item, html, final_url)
            if candidate:
                cache_catalogue_image_from_url(item, candidate)
                item.image_url = candidate
                saved += 1
                status = "cached"
        except (ImporterError, CatalogueImageError, OSError, ValueError) as exc:
            failed += 1
            status = "source-unavailable"
            # Keep a bounded human-readable diagnostic, never raw response data.
            failure_reason = f"{type(exc).__name__}: {str(exc)[:180]}"
        meta = dict(item.provenance or {})
        meta.update({"last_image_attempt_at": now.isoformat(), "last_image_status": status, "last_image_error": failure_reason})
        item.provenance = meta
        item.save(update_fields=["image_url", "provenance", "updated_at"])
    return {"processed": checked, "cached": saved, "failed": failed, "skipped": skipped}
