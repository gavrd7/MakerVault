"""Conservative per-job source-input admission based on live memory headroom.

This is a *preparation input* budget, not permission to bypass independently
validated STL geometry, expanded 3MF, worker transfer or native slicer limits.
A bounded heuristic is intentional: Python object/XML expansion can be much
larger than the compressed source, and parallel jobs share the same memory.
"""
from pathlib import Path

_MIB = 1024 * 1024
_FALLBACK_SOURCE_BYTES = 48 * _MIB
_MIN_SOURCE_BYTES = 8 * _MIB
_RESERVED_BYTES = 256 * _MIB
_SOURCE_EXPANSION_FACTOR = 8


def _read_number(path):
    try:
        value = Path(path).read_text(encoding="ascii").strip()
        if not value.isdecimal():
            return None
        number = int(value)
        return number if 0 <= number < (1 << 60) else None
    except (OSError, ValueError, OverflowError):
        return None


def _host_available_bytes():
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemAvailable:"):
                parts = line.split()
                if len(parts) == 3 and parts[1].isdecimal() and parts[2] == "kB":
                    return int(parts[1]) * 1024
    except (OSError, ValueError, OverflowError):
        pass
    return None


def _cgroup_available_bytes():
    # Prefer cgroups v2, matching the Docker memory limit and current usage.
    limit = _read_number("/sys/fs/cgroup/memory.max")
    usage = _read_number("/sys/fs/cgroup/memory.current")
    if limit is None or usage is None:
        # Debian / Docker installations using the older cgroups v1 interface.
        limit = _read_number("/sys/fs/cgroup/memory/memory.limit_in_bytes")
        usage = _read_number("/sys/fs/cgroup/memory/memory.usage_in_bytes")
    if limit is not None and usage is not None:
        return max(0, limit - usage)
    return None


def source_input_budget(*, upper_cap):
    """Return a bounded byte budget for *unique verified* plate STL sources.

    This is a snapshot, not a memory reservation. Use 1/8 of headroom after a
    fixed reserve; unknown memory data keeps the historical 48 MiB fallback.
    Always apply the caller's hard upper cap even when values are unavailable.
    """
    if type(upper_cap) is not int or upper_cap < 1:
        raise ValueError("Positive source budget upper bound required.")
    available = [value for value in (
        _cgroup_available_bytes(), _host_available_bytes()
    ) if value is not None]
    if not available:
        return min(upper_cap, _FALLBACK_SOURCE_BYTES)
    headroom = min(available)
    proposed = max(_MIN_SOURCE_BYTES,
                   max(0, headroom - _RESERVED_BYTES) // _SOURCE_EXPANSION_FACTOR)
    return min(upper_cap, proposed)


def resource_snapshot():
    """Return live host/cgroup RAM headroom without an engine-specific ceiling.

    Unknown host readings do not bypass a known cgroup limit. Unknown
    measurements fail closed for callers needing large-job admission.
    """
    observations = {
        "host_available_bytes": _host_available_bytes(),
        "cgroup_available_bytes": _cgroup_available_bytes(),
    }
    known = [n for n in observations.values() if n is not None]
    return {**observations, "available_bytes": min(known) if known else None}


def memory_budget(*, reserve_bytes, expansion_factor):
    """Provide an engine-neutral working-set admission budget.

    The reserve and empirically calibrated expansion factor are supplied by
    the operation (STL decoding, native XML, worker transport, or G-code),
    not chosen from a fixed list of engine names or arbitrary size ceilings.
    None means live resources could not be measured.
    """
    if (type(reserve_bytes) is not int or reserve_bytes < 0 or
            type(expansion_factor) is not int or expansion_factor < 1):
        raise ValueError("Invalid slicer operation memory budget parameters.")
    available = resource_snapshot()["available_bytes"]
    if available is None:
        return None
    return max(0, available - reserve_bytes) // expansion_factor
