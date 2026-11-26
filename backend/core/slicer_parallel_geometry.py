"""Bounded subprocess preparation for CPU-heavy, independent geometry tasks.

Use exec-based children rather than a nested multiprocessing pool inside
Celery's daemon workers. Inputs and outputs are private temporary files.
"""
import os
import json
import fcntl
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .slicer_profiles import SlicerProfileError
from .slicer_resource_budget import preparation_worker_count, effective_cpu_count


_MIN_PARALLEL_INPUT_BYTES = 512 * 1024


def _worker_cap():
    value = os.environ.get("MAKERVAULT_SLICER_PREPARATION_WORKERS", "").strip()
    if not value:
        return None
    if not value.isdecimal() or int(value) < 1:
        raise SlicerProfileError("Invalid slicer preparation worker setting.")
    return int(value)


# These advisory slots coordinate independent Celery job processes within
# the same backend container. Kernel locks are released after worker crashes.
@contextmanager
def _local_parallel_slots(requested):
    """Reserve process-wide parallel CPU slots without a persistent registry."""
    if requested < 2:
        yield 1
        return
    slots = []
    try:
        directory = Path(tempfile.gettempdir()) / "makervault-geometry-slots"
        directory.mkdir(mode=0o700, exist_ok=True)
        for index in range(max(1, effective_cpu_count() - 1)):
            if len(slots) == requested:
                break
            filename = directory / ("slot-%d.lock" % index)
            fd = os.open(filename, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                continue
            slots.append(fd)
    except OSError:
        # Fail back to serial processing when local coordination cannot be
        # established; do not swallow exceptions from the caller's work.
        for fd in slots:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        slots.clear()
    try:
        yield len(slots) if len(slots) >= 2 else 1
    finally:
        for fd in slots:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


@contextmanager
def prepared_mesh_batches(sources, *, estimated_bytes_per_worker, mode="mesh"):
    """Yield ordered meshes with bounded subprocesses and deterministic cleanup.

    A single worker uses the caller's sequential path (None). The parent
    owns all children so Celery soft timeouts can interrupt waits and reap
    every outstanding process before temporary files are removed.
    """
    if mode not in ("mesh", "inspect"):
        raise ValueError("Unknown geometry preparation mode.")
    if not sources:
        yield iter(())
        return
    count = preparation_worker_count(
        independent_tasks=len(sources),
        bytes_per_worker=estimated_bytes_per_worker, max_workers=_worker_cap())
    # Starting several interpreters is slower than direct handling of tiny
    # source meshes. This is a scheduling threshold, not a geometry cap.
    if sum(len(entry[1]) for entry in sources) < _MIN_PARALLEL_INPUT_BYTES:
        count = 1
    if count > 1 and shutil.disk_usage(tempfile.gettempdir()).free < (
            estimated_bytes_per_worker * count):
        count = 1
    with _local_parallel_slots(count) as count:
        if count == 1:
            yield ((entry[0], entry[1], None) for entry in sources)
            return
        with tempfile.TemporaryDirectory(prefix="mv-geometry-") as directory:
            children = []
            def batches():
                for start in range(0, len(sources), count):
                    batch = sources[start:start + count]
                    for index, entry in enumerate(batch):
                        raw = entry[1]
                        options = entry[2] if len(entry) > 2 else {}
                        source = Path(directory) / ("source-%d.stl" % index)
                        result = Path(directory) / ("mesh-%d.out" % index)
                        config = Path(directory) / ("config-%d.json" % index)
                        options = dict(options)
                        if mode == "mesh" and options.get("colour_tool_indices") is not None:
                            options["colour_tool_indices"] = list(options["colour_tool_indices"].items())
                        config.write_text(json.dumps(options), encoding="utf-8")
                        source.write_bytes(raw)
                        # Parent fixture scripts can add backend/ to sys.path without
                        # exporting PYTHONPATH. Explicitly propagate the package root
                        # so exec-based children work from any caller working directory.
                        package_root = str(Path(__file__).resolve().parent.parent)
                        env = dict(os.environ)
                        env["PYTHONPATH"] = os.pathsep.join(
                            [package_root, env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
                        error = Path(directory) / ("error-%d.log" % index)
                        with error.open("wb") as stderr:
                            child = subprocess.Popen(
                                [sys.executable, "-m", "core.slicer_parallel_geometry",
                                 mode, str(source), str(result), str(config)],
                                stdout=subprocess.DEVNULL, stderr=stderr, env=env)
                        children.append((child, source, result, config, error))
                    for entry, (child, source, result, config, error) in zip(batch, children):
                        identity, raw = entry[:2]
                        if child.wait() != 0:
                            # Diagnostic stays in server logs and never includes
                            # model contents or arbitrary input file paths.
                            import logging
                            logging.getLogger(__name__).error(
                                "Parallel source preparation failed (exit %s): %s",
                                child.returncode, error.read_text(
                                    encoding="utf-8", errors="replace")[-4096:])
                            raise SlicerProfileError("Parallel source mesh preparation failed.")
                        yield identity, raw, result.read_bytes()
                        source.unlink()
                        result.unlink()
                        config.unlink()
                        error.unlink()
                    children.clear()
            try:
                yield batches()
            finally:
                for child, _, _, _, _ in children:
                    if child.poll() is None:
                        child.kill()
                    child.wait()


def _main():
    from xml.etree import ElementTree as ET
    from .slicer_plate_3mf import NS, _render_mesh
    mode = sys.argv[1]
    source, output, config = map(Path, sys.argv[2:])
    options = json.loads(config.read_text(encoding="utf-8"))
    raw = source.read_bytes()
    if mode == "inspect":
        from .slicer_mesh import inspect_stl
        output.write_text(json.dumps(inspect_stl(raw)), encoding="utf-8")
    elif mode == "mesh":
        if options.get("colour_tool_indices") is not None:
            options["colour_tool_indices"] = dict(options["colour_tool_indices"])
        obj = ET.Element("{" + NS + "}object")
        _render_mesh(raw, obj, **options)
        with output.open("wb") as stream:
            ET.ElementTree(obj).write(stream, encoding="utf-8")
    else:
        raise ValueError("Unknown geometry preparation mode.")


if __name__ == "__main__":
    _main()
