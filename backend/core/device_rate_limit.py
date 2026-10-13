"""Redis/Django-cache backed fixed-window device API throttling.

The originating address uses REMOTE_ADDR only; forwarded headers are not trusted
here because a client could forge them. All workers share the same cache backend.
"""
from __future__ import annotations

import hashlib
import os
import time

from django.core.cache import cache

WINDOW_SECONDS = 60


def _limit(name, default):
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(1, min(value, 100000))


def allowance(group: str, identity: str, *, limit: int):
    """Return (allowed, retry_after). Cache faults must not bypass protection."""
    bucket = int(time.time() // WINDOW_SECONDS)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    key = f"mv:device:throttle:v1:{group}:{digest}:{bucket}"
    remaining = WINDOW_SECONDS - (int(time.time()) % WINDOW_SECONDS)
    try:
        if cache.add(key, 1, timeout=WINDOW_SECONDS + 5):
            count = 1
        else:
            count = cache.incr(key)
    except Exception:
        return None, remaining
    return count <= limit, remaining


def _auth_key(request):
    address = request.META.get("REMOTE_ADDR") or "unknown"
    digest = hashlib.sha256(address.encode("utf-8")).hexdigest()
    return f"mv:device:throttle:v1:auth:{digest}:{int(time.time() // WINDOW_SECONDS)}"


def failed_auth_blocked(request):
    try:
        count = int(cache.get(_auth_key(request), 0))
        return count >= _limit("MAKERVAULT_DEVICE_AUTH_FAILS_PER_MINUTE", 20), WINDOW_SECONDS - (int(time.time()) % WINDOW_SECONDS)
    except Exception:
        return None, WINDOW_SECONDS


def record_failed_auth(request):
    key = _auth_key(request)
    try:
        if not cache.add(key, 1, timeout=WINDOW_SECONDS + 5):
            cache.incr(key)
        return True
    except Exception:
        return False


def device_request_allowed(identifier, *, write):
    env = "MAKERVAULT_DEVICE_WRITES_PER_MINUTE" if write else "MAKERVAULT_DEVICE_READS_PER_MINUTE"
    limit = _limit(env, 30 if write else 120)
    return allowance("write" if write else "read", identifier, limit=limit)
