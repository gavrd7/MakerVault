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
                       str(asset.file.size), str(updated), str(detail), "v2"))
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
    except (ValueError, TypeError, OSError, zlib.error, RuntimeError, ConnectionError):
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
    except (OSError, RuntimeError, ConnectionError):
        return None
    return cached_batch(index_key, heights[:MAX_BATCH_LAYERS])
