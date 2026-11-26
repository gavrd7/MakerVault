"""Bounded subprocess preparation for CPU-heavy, independent geometry tasks.

Use exec-based children rather than a nested multiprocessing pool inside
Celery's daemon workers. Inputs and outputs are private temporary files.
"""
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
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


def _render_file(directory, raw):
    with tempfile.TemporaryDirectory(dir=directory) as folder:
        source = Path(folder) / "source.stl"
        source.write_bytes(raw)
        result = Path(folder) / "mesh.xml"
        # Inherit the backend interpreter and import path, never a shell.
        with subprocess.Popen(
                [sys.executable, "-m", "core.slicer_parallel_geometry",
                 str(source), str(result)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as child:
            try:
                if child.wait() != 0:
                    raise SlicerProfileError("Parallel source mesh preparation failed.")
                return result.read_bytes()
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()


@contextmanager
def prepared_mesh_batches(sources, *, estimated_bytes_per_worker):
    """Yield ordered batches, bounded by CPU and estimated RAM.

    A single worker uses the caller's existing sequential path (None).
    Only one batch is submitted at a time; no unbounded futures queue.
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
        with ThreadPoolExecutor(max_workers=count) as executor:
            def batches():
                for start in range(0, len(sources), count):
                    batch = sources[start:start + count]
                    futures = [executor.submit(_render_file, directory, raw)
                               for _, raw in batch]
                    for (identity, raw), future in zip(batch, futures):
                        yield identity, raw, future.result()
            yield batches()


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
