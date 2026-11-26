"""Engine-neutral resource measurement for isolated slicer operations.

Every engine adapter can use the same memory/temporary-disk admission
contract. A budget is not a security validation and does not authorise
untrusted native options or unbounded concurrent workers.
"""
from pathlib import Path
import shutil
import tempfile


def _read_positive_number(path):
    try:
        value = Path(path).read_text(encoding="ascii").strip()
        return int(value) if value.isdecimal() and int(value) < (1 << 60) else None
    except (OSError, ValueError, OverflowError):
        return None


def memory_headroom():
    readings = []
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemAvailable:"):
                readings.append(int(line.split()[1]) * 1024)
                break
    except (OSError, ValueError, IndexError, OverflowError):
        pass
    for root, limit_file, current_file in (
        ("/sys/fs/cgroup", "memory.max", "memory.current"),
        ("/sys/fs/cgroup/memory", "memory.limit_in_bytes", "memory.usage_in_bytes"),
    ):
        maximum = _read_positive_number(root + "/" + limit_file)
        used = _read_positive_number(root + "/" + current_file)
        if maximum is not None and used is not None:
            readings.append(max(0, maximum - used))
            break
    return min(readings) if readings else None


def operation_memory_budget(*, reserve_bytes, expansion_factor):
    """Bytes safely admitted for a particular operation's expansion factor."""
    if (type(reserve_bytes) is not int or reserve_bytes < 0 or
            type(expansion_factor) is not int or expansion_factor < 1):
        raise ValueError("Invalid slicer resource budget parameters.")
    available = memory_headroom()
    return (max(0, available - reserve_bytes) // expansion_factor
            if available is not None else None)


def scratch_disk_headroom(path=None):
    """Return actual free bytes on the scratch filesystem for each job."""
    try:
        return shutil.disk_usage(path or tempfile.gettempdir()).free
    except OSError:
        return None


def admit_working_set(*, memory_bytes, scratch_bytes=0,
                      reserve_bytes=256 * 1024 * 1024,
                      disk_reserve_bytes=256 * 1024 * 1024):
    """Fail closed unless measured worker RAM and scratch space cover demand.

    Actual memory cost is supplied by the engine's measured expansion model;
    the policy itself is independent of engine and source format.
    """
    if (type(memory_bytes) is not int or memory_bytes < 0 or
            type(scratch_bytes) is not int or scratch_bytes < 0):
        raise ValueError("Invalid slicer working-set estimate.")
    memory = memory_headroom()
    disk = scratch_disk_headroom()
    return (memory is not None and disk is not None
            and memory_bytes + reserve_bytes <= memory
            and scratch_bytes + disk_reserve_bytes <= disk)


def model_input_budget():
    """Per-input in-memory native model byte budget for any engine."""
    available = operation_memory_budget(
        reserve_bytes=256 * 1024 * 1024, expansion_factor=8)
    return available if available is not None else 32 * 1024 * 1024


def gcode_output_budget():
    """Common worker output ceiling derived from RAM and available disk.

    Legacy fallback applies only when resource readings are unavailable.
    """
    available = operation_memory_budget(
        reserve_bytes=256 * 1024 * 1024, expansion_factor=6)
    disk = scratch_disk_headroom()
    budget = available if available is not None else 64 * 1024 * 1024
    if disk is not None:
        budget = min(budget, max(0, disk - 256 * 1024 * 1024))
    return budget
