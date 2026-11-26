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
# Render-cache granularity, not a cap on how much of the print is shown.
# Small exact blocks avoid inflating an entire 64-layer model in Redis and
# Python just to serve an iPhone's 1-2-layer transport request.
FULL_RENDER_CACHE_LAYERS = 8


def preview_index_key(asset, detail):
    # FileAsset writes have an update timestamp; file size also invalidates
    # cached data if the backing file is replaced without changing its path.
    updated = getattr(asset, "updated_at", None)
    source = "|".join((str(asset.owner_id), str(asset.pk), str(asset.file.name),
                       str(asset.file.size), str(updated), str(detail), "v5-mobile-exact-blocks"))
    return "gcode-preview:" + hashlib.sha256(source.encode("utf-8")).hexdigest()


def _same_heights(a, b):
    return len(a) == len(b) and all(round(float(x), 3) == round(float(y), 3)
                                    for x, y in zip(a, b))


def cached_batch(index_key, heights):
    """Return exactly the requested complete layer range from cached blocks.

    A mobile client may request smaller batches than the 64-layer cache
    layout. Cached entries must not return extra layers or require page
    alignment, and requests crossing a cache boundary must remain valid.
    """
    try:
        if not heights:
            return None
        manifest = cache.get(index_key + ":manifest")
        if not isinstance(manifest, list) or not manifest:
            return None
        first = round(heights[0], 3)
        start = next((i for i, value in enumerate(manifest)
                      if round(value, 3) == first), -1)
        if start < 0 or not _same_heights(
                manifest[start:start + len(heights)], heights):
            return None
        selected = []
        template = None
        block_size = cache.get(index_key + ":block_size") or MAX_BATCH_LAYERS
        if type(block_size) is not int or not 1 <= block_size <= MAX_BATCH_LAYERS:
            return None
        end = start + len(heights)
        for block_start in range(
                start // block_size * block_size,
                end, block_size):
            packed = cache.get(
                index_key + ":batch:" + str(block_start // block_size))
            if packed is None:
                return None
            payload = json.loads(zlib.decompress(packed))
            block = payload.get("layers")
            if not isinstance(block, list):
                return None
            if template is None:
                template = payload
            first_index = max(start, block_start) - block_start
            last_index = min(end, block_start + len(block)) - block_start
            selected.extend(block[first_index:last_index])
        if len(selected) != len(heights) or template is None:
            return None
        return {**template, "layers": selected}
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
    block_size = FULL_RENDER_CACHE_LAYERS if full else MAX_BATCH_LAYERS
    for offset in range(0, len(heights), block_size):
        part = layers[offset:offset + block_size]
        payload = {
            "layers": part, "complete": True, "sampled": not full,
            "overview": not full, "high_fidelity": full, "cached": True,
        }
        packed = zlib.compress(
            json.dumps(payload, separators=(",", ":")).encode("utf-8"), level=3)
        batches.append((offset // block_size, packed))
    try:
        for number, packed in batches:
            cache.set(index_key + ":batch:" + str(number), packed, CACHE_SECONDS)
        cache.set(index_key + ":block_size", block_size, CACHE_SECONDS)
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

def complete_preview_inventory(asset):
    """Owner-bound cached complete layer inventory for large plain-text G-code.

    Scan in bounded lines from storage, never read an entire sliced job into
    Python memory or return a first-32-MiB layer list as if complete.
    """
    from .slicer_preview import generated_preview
    from .slicer_layer_preview import streamed_gcode_lines
    key = preview_index_key(asset, "complete-summary-v1")
    try:
        packed = cache.get(key)
        if packed is not None:
            return json.loads(zlib.decompress(packed))
    except Exception:
        pass
    with asset.file.storage.open(asset.file.name, "rb") as handle:
        result = generated_preview(streamed_gcode_lines(handle))
    try:
        cache.set(key, zlib.compress(
            json.dumps(result, separators=(",", ":")).encode("utf-8"), 3),
            CACHE_SECONDS)
    except Exception:
        pass
    return result

def warm_streamed_high_fidelity(asset):
    """Cache full-detail geometry of large files one bounded batch at a time.

    The manifest becomes visible only when every layer was parsed exactly.
    A dense batch beyond the budget stays uncached and is still available via
    the paged on-demand API; we never publish partial geometry as complete.
    """
    from .slicer_layer_preview import (
        streamed_gcode_lines, MAX_FULL_PREVIEW_SEGMENTS)
    summary = complete_preview_inventory(asset)
    heights = summary.get("layers", [])
    if not 1 <= len(heights) <= MAX_INDEX_LAYERS:
        return False
    index_key = preview_index_key(asset, "full-v1")
    if cached_batch(index_key, heights[:MAX_BATCH_LAYERS]) is not None:
        return True

    # Most 20-model prints fit the per-job geometry budget even if their
    # original G-code is >32 MiB. Parse the complete source once where live
    # RAM can support all retained Python paths and their JSON encoding.
    # Larger jobs automatically fall back to bounded 64-layer passes; neither
    # path loses extrusion geometry.
    from .slicer_resource_budget import resource_snapshot
    total_moves = summary.get("segment_count")
    available = resource_snapshot()["available_bytes"]
    if (type(total_moves) is int and 0 < total_moves <= MAX_FULL_PREVIEW_SEGMENTS
            and available is not None
            and total_moves * 850 + 512 * 1024 * 1024 < available // 2):
        with asset.file.storage.open(asset.file.name, "rb") as handle:
            combined = layer_batch_toolpaths(
                streamed_gcode_lines(handle), heights,
                high_fidelity=True, max_requested_layers=len(heights),
                max_total_segments=MAX_FULL_PREVIEW_SEGMENTS,
            )
        if combined["complete"]:
            return _store_overview(index_key, heights, combined["layers"],
                                   0, full=True)
        # The full-pass admission is only an optimisation, not a stopping
        # condition for a dense layer or unexpectedly high extrusion count.

    for offset in range(0, len(heights), MAX_BATCH_LAYERS):
        with asset.file.storage.open(asset.file.name, "rb") as handle:
            result = layer_batch_toolpaths(
                streamed_gcode_lines(handle),
                heights[offset:offset + MAX_BATCH_LAYERS],
                high_fidelity=True,
                max_total_segments=MAX_FULL_PREVIEW_SEGMENTS,
            )
        if not result["complete"]:
            return False
        try:
            for suboffset in range(0, len(result["layers"]), FULL_RENDER_CACHE_LAYERS):
                packed = zlib.compress(json.dumps({
                    "layers": result["layers"][suboffset:suboffset + FULL_RENDER_CACHE_LAYERS],
                    "complete": True, "sampled": False, "overview": False,
                    "high_fidelity": True, "cached": True,
                }, separators=(",", ":")).encode("utf-8"), level=3)
                cache.set(index_key + ":batch:" +
                          str((offset + suboffset) // FULL_RENDER_CACHE_LAYERS),
                          packed, CACHE_SECONDS)
        except Exception:
            return False
    try:
        # Cache readers only observe complete sets; partial writes aren't
        # advertised and never alter the source G-code.
        cache.set(index_key + ":block_size", FULL_RENDER_CACHE_LAYERS, CACHE_SECONDS)
        cache.set(index_key + ":manifest", list(heights), CACHE_SECONDS)
    except Exception:
        return False
    return True

def _direct_batch_key(asset, heights, *, high_fidelity, overview, detail):
    """Key a complete bounded response by source identity and exact layer set."""
    request = json.dumps([
        "exact-v1", [round(float(z), 3) for z in heights],
        bool(high_fidelity), bool(overview), int(detail),
    ], separators=(",", ":"))
    digest = hashlib.sha256(request.encode("ascii")).hexdigest()
    return preview_index_key(asset, "direct-batches-v1") + ":" + digest


def cached_direct_batch(asset, heights, *, high_fidelity, overview, detail):
    """Reuse earlier exact responses without rescanning G-code after reconnect."""
    try:
        packed = cache.get(_direct_batch_key(
            asset, heights, high_fidelity=high_fidelity,
            overview=overview, detail=detail))
        if packed is not None:
            result = json.loads(zlib.decompress(packed))
            if result.get("complete") and len(result.get("layers", ())) == len(heights):
                return result
    except Exception:
        pass
    return None


def store_direct_batch(asset, heights, result, *,
                       high_fidelity, overview, detail):
    """Cache only complete exact batches, never partial geometry or paged cursors.

    Individual Redis items are bounded independently of the overall print;
    a cache outage or too-large page does not change the requested toolpaths.
    """
    if not result.get("complete") or len(result.get("layers", ())) != len(heights):
        return False
    try:
        packed = zlib.compress(json.dumps(
            result, separators=(",", ":")).encode("utf-8"), level=1)
        if len(packed) > 4 * 1024 * 1024:
            return False
        cache.set(_direct_batch_key(
            asset, heights, high_fidelity=high_fidelity,
            overview=overview, detail=detail), packed, CACHE_SECONDS)
        return True
    except Exception:
        return False
