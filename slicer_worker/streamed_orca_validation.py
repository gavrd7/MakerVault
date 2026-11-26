"""Streaming verification of one plain Orca compound 3MF core mesh.

This contract is used only by the authenticated, engine-scoped streamed-plate
request. It does not expand an XML tree, trust external resources, accept
settings or extend any existing 3MF project's admission privileges.
"""
import io
import math
from xml.parsers import expat
import zipfile

from .runner import WorkerError

_CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
_LANG = "http://www.w3.org/XML/1998/namespace}lang"
_ALLOWED = {"3D/3dmodel.model", "[Content_Types].xml", "_rels/.rels"}


from .resource_budget import memory_headroom as _memory_headroom
from .resource_budget import operation_memory_budget


def streamed_orca_memory_budget():
    # Generic operation policy; the geometry exporter supplies cost estimates.
    # Keep this function as a compatibility boundary for existing tests.
    return operation_memory_budget(
        reserve_bytes=256 * 1024 * 1024, expansion_factor=4) or 0


def validate_streamed_orca_3mf(data):
    """Validate the exact standalone geometry-only ZIP, returning facet counts.

    All body and expanded-XML admission is sized from measured worker memory,
    not a fixed overall triangle count. Each SAX node is checked and released.
    """
    memory_budget = streamed_orca_memory_budget()
    if (not isinstance(data, bytes) or not data
            or memory_budget == 0 or len(data) * 8 > memory_budget):
        raise WorkerError("Streamed Orca plate exceeds available worker memory.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if (len(members) != 3 or {m.filename for m in members} != _ALLOWED
                    or any(m.is_dir() or m.flag_bits & 1 or m.file_size <= 0
                           for m in members)):
                raise WorkerError("Invalid streamed Orca core 3MF members.")
            main = archive.getinfo("3D/3dmodel.model")
            if (main.file_size > memory_budget or
                    archive.getinfo("[Content_Types].xml").file_size > 4096 or
                    archive.getinfo("_rels/.rels").file_size > 4096):
                raise WorkerError("Streamed Orca 3MF exceeds verified memory.")
            # Sidecar content is not used by the geometry executor. Keep
            # exactly the reviewed package envelope, never project settings.
            types = archive.read("[Content_Types].xml")
            rels = archive.read("_rels/.rels")
            if (b"3dmanufacturing" not in types or
                    b"/3D/3dmodel.model" not in rels):
                raise WorkerError("Malformed streamed Orca 3MF package.")
            stack = []
            counts = {"vertices": 0, "triangles": 0}
            seen = {"resources": 0, "object": 0, "mesh": 0,
                    "vertices": 0, "triangles": 0, "build": 0, "item": 0}
            transitions = {
                "": ("model",), "model": ("resources", "build"),
                "resources": ("object",), "object": ("mesh",),
                "mesh": ("vertices", "triangles"),
                "vertices": ("vertex",), "triangles": ("triangle",),
                "build": ("item",),
            }

            def start(name, attrs):
                prefix = _CORE + "}"
                if not name.startswith(prefix):
                    raise WorkerError("Unapproved streamed Orca XML namespace.")
                tag = name[len(prefix):]
                parent = stack[-1] if stack else ""
                if tag not in transitions.get(parent, ()):
                    raise WorkerError("Unapproved streamed Orca XML structure.")
                stack.append(tag)
                if tag in seen:
                    seen[tag] += 1
                    if seen[tag] != 1:
                        raise WorkerError("Duplicated streamed Orca XML resource.")
                if tag == "model":
                    if attrs != {"unit": "millimeter", _LANG: "en-US"}:
                        raise WorkerError("Unexpected streamed Orca model properties.")
                elif tag == "object":
                    if attrs != {"id": "1", "type": "model"}:
                        raise WorkerError("Unexpected streamed Orca object identity.")
                elif tag == "item":
                    if attrs != {"objectid": "1",
                                 "transform": "1 0 0 0 1 0 0 0 1 0 0 0"}:
                        raise WorkerError("Invalid streamed Orca build target.")
                elif tag == "vertex":
                    if set(attrs) != {"x", "y", "z"}:
                        raise WorkerError("Invalid streamed Orca vertex.")
                    try:
                        point = [float(attrs[v]) for v in ("x", "y", "z")]
                    except ValueError:
                        raise WorkerError("Invalid streamed Orca coordinates.") from None
                    if any(not math.isfinite(v) or abs(v) > 10000 for v in point):
                        raise WorkerError("Unsafe streamed Orca coordinates.")
                    counts["vertices"] += 1
                elif tag == "triangle":
                    if set(attrs) != {"v1", "v2", "v3"}:
                        raise WorkerError("Invalid streamed Orca facet.")
                    try:
                        indices = [int(attrs[v]) for v in ("v1", "v2", "v3")]
                    except ValueError:
                        raise WorkerError("Invalid streamed Orca facet indices.") from None
                    if any(v < 0 or v >= counts["vertices"] for v in indices):
                        raise WorkerError("Streamed Orca facet references an invalid vertex.")
                    counts["triangles"] += 1
                elif attrs:
                    raise WorkerError("Unsupported streamed Orca XML attributes.")
                if (counts["vertices"] * 120 + counts["triangles"] * 240
                        > memory_budget):
                    raise WorkerError("Streamed Orca geometry exceeds available memory.")

            def end(name):
                tag = name.split("}")[-1]
                if not stack or stack[-1] != tag:
                    raise WorkerError("Unbalanced streamed Orca model.")
                stack.pop()

            parser = expat.ParserCreate(namespace_separator="}")
            parser.StartElementHandler = start
            parser.EndElementHandler = end
            parser.StartDoctypeDeclHandler = lambda *_: (_ for _ in ()).throw(
                WorkerError("Streamed Orca plate must not contain a DTD."))
            parser.ExternalEntityRefHandler = lambda *_: 0
            with archive.open(main) as xml:
                while block := xml.read(65536):
                    parser.Parse(block, False)
                parser.Parse(b"", True)
            if (stack or not all(v == 1 for v in seen.values())
                    or counts["vertices"] < 3 or counts["triangles"] < 1):
                raise WorkerError("Incomplete streamed Orca build plate.")
            return counts
    except WorkerError:
        raise
    except (OSError, ValueError, KeyError, zipfile.BadZipFile,
            expat.ExpatError, OverflowError):
        raise WorkerError("Invalid compressed streamed Orca geometry.") from None
