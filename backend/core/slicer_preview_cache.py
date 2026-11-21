"""Redis-backed, owner-scoped cached surface preview batches.

A cold request parses the entire bounded source once and retains *only*
display-level geometry. Later chunks and repeat opens never rescan the G-code.
Original source and exact-layer inspection are not modified.
"""
import hashlib
import json
import zlib

from django.core.cache import cache

from .slicer_layer_preview import MAX_BATCH_LAYERS, layer_batch_toolpaths

CACHE_SECONDS = 6 * 3600
MAX_INDEX_LAYERS = 2000


def preview_index_key(asset, detail):
    # FileAsset writes have an update timestamp; file size also invalidates
    # cached data if the backing file is replaced without changing its path.
    updated = getattr(asset, "updated_at", None)
    source = "|".join((str(asset.owner_id), str(asset.pk), str(asset.file.name),
                       str(asset.file.size), str(updated), str(detail), "v4-balanced"))
    return "gcode-preview:" + hashlib.sha256(source.encode("utf-8")).hexdigest()


def _same_heights(a, b):
    return len(a) == len(b) and all(round(float(x), 3) == round(float(y), 3)
                                    for x, y in zip(a, b))


def cached_batch(index_key, heights):
    """Return a matching complete cached 64-layer block or None."""
    try:
        manifest = cache.get(index_key + ":manifest")
        if not isinstance(manifest, list) or not manifest:
            return None
        first = round(heights[0], 3)
        # Heights are sorted as originally reported by the slicer analysis.
        start = next((i for i, value in enumerate(manifest)
                      if round(value, 3) == first), -1)
        if start < 0 or start % MAX_BATCH_LAYERS or not _same_heights(
                manifest[start:start + len(heights)], heights):
            return None
        packed = cache.get(index_key + ":batch:" + str(start // MAX_BATCH_LAYERS))
        if packed is None:
            return None
        return json.loads(zlib.decompress(packed))
    except Exception:
        # A cache outage or corrupt cached blob must not interrupt preview.
        return None


def index_overview(index_key, text, heights, detail):
    """Parse a complete G-code overview once; publish the index atomically.

    Incomplete source or a Redis failure leaves the normal batch endpoint
    available, but no misleading 'complete' cached geometry is published.
    """
    if not 1 <= len(heights) <= MAX_INDEX_LAYERS:
        raise ValueError("Invalid overview layer count.")
    result = layer_batch_toolpaths(
        text, heights, overview=True, overview_limit=detail,
        max_requested_layers=MAX_INDEX_LAYERS,
    )
    if not result["complete"]:
        return None
    batches = []
    for offset in range(0, len(heights), MAX_BATCH_LAYERS):
        part = result["layers"][offset:offset + MAX_BATCH_LAYERS]
        payload = {
            "layers": part,
            "complete": True,
            "sampled": True,
            "overview": True,
            "cached": True,
        }
        compressed = zlib.compress(
            json.dumps(payload, separators=(",", ":")).encode("utf-8"), level=3
        )
        batches.append((offset // MAX_BATCH_LAYERS, compressed))
    try:
        for number, compressed in batches:
            cache.set(index_key + ":batch:" + str(number), compressed, CACHE_SECONDS)
        # Written last so readers never see a half-created index.
        cache.set(index_key + ":manifest", list(heights), CACHE_SECONDS)
    except Exception:
        # Redis availability is optional for correctness.
        return None
    return cached_batch(index_key, heights[:MAX_BATCH_LAYERS])


def _store_overview(index_key, heights, layers, detail, *, full=False):
    """Publish validated batches; the manifest is the atomic ready marker."""
    if len(heights) != len(layers) or not 1 <= len(heights) <= MAX_INDEX_LAYERS:
        raise ValueError("Invalid preview index data.")
    batches = []
    for offset in range(0, len(heights), MAX_BATCH_LAYERS):
        part = layers[offset:offset + MAX_BATCH_LAYERS]
        payload = {
            "layers": part, "complete": True, "sampled": not full,
            "overview": not full, "high_fidelity": full, "cached": True,
        }
        packed = zlib.compress(
            json.dumps(payload, separators=(",", ":")).encode("utf-8"), level=3)
        batches.append((offset // MAX_BATCH_LAYERS, packed))
    try:
        for number, packed in batches:
            cache.set(index_key + ":batch:" + str(number), packed, CACHE_SECONDS)
        cache.set(index_key + ":manifest", list(heights), CACHE_SECONDS)
    except Exception:
        return False
    return True


def warm_asset_overviews(asset, source):
    """Prepare desktop and mobile density variants once after a slice finishes.

    Desktop and mobile share the same full G-code parse. Only the small
    retained overview is downsampled for the lower-memory variant.
    This intentionally runs outside the HTTP preview request.
    """
    from .slicer_preview import generated_preview
    from .slicer_layer_preview import _overview_segments

    if isinstance(source, bytes):
        if len(source) > 32 * 1024 * 1024 or b"\x00" in source:
            return False
        source = source.decode("utf-8")
    if not isinstance(source, str) or not source or len(source.encode("utf-8")) > 32 * 1024 * 1024:
        return False
    heights = generated_preview(source).get("layers", [])
    if not heights or len(heights) > MAX_INDEX_LAYERS:
        return False

    desktop = max(80, min(220, 220000 // len(heights)))
    mobile = max(80, min(110, 100000 // len(heights)))
    if (cached_batch(preview_index_key(asset, desktop), heights[:MAX_BATCH_LAYERS])
            is not None and
            cached_batch(preview_index_key(asset, mobile), heights[:MAX_BATCH_LAYERS])
            is not None):
        return True
    parsed = layer_batch_toolpaths(
        source, heights, overview=True, overview_limit=desktop,
        max_requested_layers=MAX_INDEX_LAYERS,
    )
    if not parsed["complete"]:
        return False
    rows = parsed["layers"]
    if not _store_overview(preview_index_key(asset, desktop), heights, rows, desktop):
        return False
    if desktop != mobile:
        slim = [
            {**row,
             "segments": _overview_segments(row["segments"], mobile),
             "overview_reduced": row["segment_count"] > mobile,
             "sampled": row["segment_count"] > mobile}
            for row in rows
        ]
        return _store_overview(preview_index_key(asset, mobile), heights, slim, mobile)
    return True

def warm_asset_high_fidelity(asset, source):
    """Precompute the geometry-preserving preview in the existing worker.

    Unlike the historical overview, never selects isolated segments from
    walls, supports or prime towers. Only consecutive collinear extrusion
    moves can be merged; every other original path remains represented.
    """
    from .slicer_preview import generated_preview
    from .slicer_layer_preview import MAX_FULL_PREVIEW_SEGMENTS
    if isinstance(source, bytes):
        if len(source) > 32 * 1024 * 1024 or b"\x00" in source:
            return False
        source = source.decode("utf-8")
    if not isinstance(source, str) or len(source.encode("utf-8")) > 32 * 1024 * 1024:
        return False
    heights = generated_preview(source).get("layers", [])
    if not heights or len(heights) > MAX_INDEX_LAYERS:
        return False
    index_key = preview_index_key(asset, "full-v1")
    if cached_batch(index_key, heights[:MAX_BATCH_LAYERS]) is not None:
        return True
    result = layer_batch_toolpaths(
        source, heights, high_fidelity=True,
        max_requested_layers=MAX_INDEX_LAYERS,
        max_total_segments=MAX_FULL_PREVIEW_SEGMENTS,
    )
    if not result["complete"]:
        # Avoid repeatedly scheduling expensive scans of G-code beyond the
        # memory budget. Direct bounded layer fetch remains available.
        try:
            cache.set(index_key + ":unavailable", "resource-limit", 3600)
        except Exception:
            pass
        return False
    return _store_overview(index_key, heights, result["layers"], 0, full=True)
