"""Bounded subprocess preparation for CPU-heavy, independent geometry tasks.

Use exec-based children rather than a nested multiprocessing pool inside
Celery's daemon workers. Inputs and outputs are private temporary files.
"""
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .slicer_profiles import SlicerProfileError
from .slicer_resource_budget import preparation_worker_count


def _worker_cap():
    value = os.environ.get("MAKERVAULT_SLICER_PREPARATION_WORKERS", "").strip()
    if not value:
        return None
    if not value.isdecimal() or int(value) < 1:
        raise SlicerProfileError("Invalid slicer preparation worker setting.")
    return int(value)


@contextmanager
def prepared_mesh_batches(sources, *, estimated_bytes_per_worker):
    """Yield ordered meshes with bounded subprocesses and deterministic cleanup.

    A single worker uses the caller's sequential path (None). The parent
    owns all children so Celery soft timeouts can interrupt waits and reap
    every outstanding process before temporary files are removed.
    """
    if not sources:
        yield iter(())
        return
    count = preparation_worker_count(
        independent_tasks=len(sources),
        bytes_per_worker=estimated_bytes_per_worker, max_workers=_worker_cap())
    if count == 1:
        yield ((identity, raw, None) for identity, raw in sources)
        return
    with tempfile.TemporaryDirectory(prefix="mv-geometry-") as directory:
        children = []
        def batches():
            for start in range(0, len(sources), count):
                batch = sources[start:start + count]
                for index, (_, raw) in enumerate(batch):
                    source = Path(directory) / ("source-%d.stl" % index)
                    result = Path(directory) / ("mesh-%d.xml" % index)
                    source.write_bytes(raw)
                    child = subprocess.Popen(
                        [sys.executable, "-m", "core.slicer_parallel_geometry",
                         str(source), str(result)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    children.append((child, source, result))
                for (identity, raw), (child, source, result) in zip(batch, children):
                    if child.wait() != 0:
                        raise SlicerProfileError("Parallel source mesh preparation failed.")
                    yield identity, raw, result.read_bytes()
                    source.unlink()
                    result.unlink()
                children.clear()
        try:
            yield batches()
        finally:
            for child, _, _ in children:
                if child.poll() is None:
                    child.kill()
                child.wait()


def _main():
    from xml.etree import ElementTree as ET
    from .slicer_plate_3mf import NS, _render_mesh
    source, output = map(Path, sys.argv[1:])
    obj = ET.Element("{" + NS + "}object")
    _render_mesh(source.read_bytes(), obj)
    with output.open("wb") as stream:
        ET.ElementTree(obj).write(stream, encoding="utf-8")


if __name__ == "__main__":
    _main()
