"""Generate and slice fixed two-material Bambu 3MF acceptance fixtures.

No printer control, network access, arbitrary paths inside the worker or
external model/profile data is embedded. Verify real tool deposition instead
of treating a successfully opened project as a multicolour slicing pass.
"""
import argparse
import hashlib
import io
import json
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from slicer_worker.bambu_runner import run_bambu
from slicer_worker.material_gcode_audit import (
    expected_native_tools, verify_multi_material_output,
    verify_two_object_tool_regions,
)
from slicer_worker.runner import WorkerError
from slicer_worker.three_mf_validation import CORE_NS, validate_worker_3mf


def make_bambu_material_fixture(*, painted=False):
    """Build 1 painted cube or 2 separately assigned cubes on a 256mm plate."""
    ns = "{" + CORE_NS + "}"
    ET.register_namespace("", CORE_NS)
    model = ET.Element(ns + "model", {"unit": "millimeter"})
    resources = ET.SubElement(model, ns + "resources")
    build = ET.SubElement(model, ns + "build")
    # X positions deliberately match the existing material/deposition audit.
    positions = [(75, 110)] if painted else [(75, 110), (145, 110)]
    vertices = [
        (-10, -10, 0), (10, -10, 0), (10, 10, 0), (-10, 10, 0),
        (-10, -10, 20), (10, -10, 20), (10, 10, 20), (-10, 10, 20),
    ]
    faces = (
        (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
        (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7),
    )
    manifest = ET.Element("config")
    for index, (x, y) in enumerate(positions, 1):
        obj = ET.SubElement(resources, ns + "object", {"id": str(index), "type": "model"})
        mesh = ET.SubElement(obj, ns + "mesh")
        points = ET.SubElement(mesh, ns + "vertices")
        for dx, dy, z in vertices:
            ET.SubElement(points, ns + "vertex", {
                "x": str(x + dx), "y": str(y + dy), "z": str(z)})
        triangles = ET.SubElement(mesh, ns + "triangles")
        for face_index, (v1, v2, v3) in enumerate(faces):
            attrs = {"v1": str(v1), "v2": str(v2), "v3": str(v3)}
            if painted and face_index in (2, 3, 6, 7):
                # Native 3MF TriangleSelector state: paint_color=8 => tool 1.
                attrs["paint_color"] = "8"
            ET.SubElement(triangles, ns + "triangle", attrs)
        ET.SubElement(build, ns + "item", {
            "objectid": str(index),
            "transform": "1 0 0 0 1 0 0 0 1 0 0 0"})
        item = ET.SubElement(manifest, "object", {"id": str(index)})
        ET.SubElement(item, "metadata", {
            "key": "extruder", "value": str(1 if painted else index)})
    plate = ET.SubElement(manifest, "plate")
    ET.SubElement(plate, "metadata", {"key": "plater_id", "value": "1"})
    for index in range(1, len(positions) + 1):
        item = ET.SubElement(plate, "model_instance")
        for name, value in (("object_id", str(index)), ("instance_id", "0"),
                            ("identify_id", str(index))):
            ET.SubElement(item, "metadata", {"key": name, "value": value})
    content_types = (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
        '</Types>')
    rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rel0" Target="/3D/3dmodel.model" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
        '</Relationships>')
    with io.BytesIO() as data:
        with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as package:
            package.writestr("3D/3dmodel.model", ET.tostring(model, encoding="utf-8"))
            package.writestr("Metadata/model_settings.config",
                             ET.tostring(manifest, encoding="utf-8"))
            package.writestr("[Content_Types].xml", content_types)
            package.writestr("_rels/.rels", rels)
        raw = data.getvalue()
    validate_worker_3mf(raw, native_tool_count=2)
    if expected_native_tools(raw) != {0, 1}:
        raise WorkerError("Two-material fixture did not select both logical tools.")
    return raw


def run_fixture(binary, profiles, *, painted=False, timeout=180):
    source = Path(profiles)
    with tempfile.TemporaryDirectory(prefix="makervault-bambu-two-tool-") as tmp:
        workdir = Path(tmp)
        project = make_bambu_material_fixture(painted=painted)
        (workdir / "input.3mf").write_bytes(project)
        for kind in ("printer", "process", "filament"):
            raw = (source / (kind + ".json")).read_bytes()
            (workdir / (kind + ".json")).write_bytes(raw)
        filament = (workdir / "filament.json").read_bytes()
        (workdir / "filament-0.json").write_bytes(filament)
        # Same verified PLA preset in two logical slots. Material assignment
        # must still be evident in the *native G-code*, not inferred from colour.
        (workdir / "filament-1.json").write_bytes(filament)
        try:
            receipt = run_bambu(Path(binary), workdir, timeout_seconds=timeout)
        except WorkerError:
            # Diagnostic only: this invocation is an ephemeral CI fixture
            # using public, pinned BBL profiles and a synthetic 3MF. Never
            # expose native stderr from production worker requests.
            import os
            if os.environ.get("MAKERVAULT_BAMBU_FIXTURE_DIAGNOSTICS") == "1":
                import subprocess
                from slicer_worker.bambu_runner import bambu_command
                from slicer_worker.headless_env import slicing_environment
                (workdir / "bambu-sliced.3mf").unlink(missing_ok=True)
                args = bambu_command(Path(binary), workdir)
                attempt = subprocess.run(args, cwd=workdir,
                    env={**slicing_environment(workdir),
                         "SSL_CERT_FILE": "/etc/ssl/certs/ca-certificates.crt"},
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, timeout=timeout, check=False)
                for channel in (attempt.stdout, attempt.stderr):
                    for line in channel.decode("utf-8", "replace").splitlines()[-25:]:
                        if any(token in line.lower() for token in (
                            "error", "failed", "invalid", "warn", "filament",
                            "3mf", "plate", "slice", "unsupported")):
                            print("CI native diagnosis:", line[:320])
                print("CI native exit code:", attempt.returncode)
            raise
        gcode = (workdir / "output.gcode").read_bytes()
        verify_multi_material_output(gcode, {0, 1})
        coverage = ({} if painted else verify_two_object_tool_regions(gcode))
        return {
            "status": "passed", "engine": "bambustudio",
            "fixture": "painted-facets" if painted else "two-objects",
            "gcode_bytes": receipt["bytes"],
            "gcode_sha256": hashlib.sha256(gcode).hexdigest(),
            "both_tools_extrude": True, **coverage,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True)
    parser.add_argument("--profiles", required=True)
    parser.add_argument("--painted", action="store_true")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    try:
        print(json.dumps(run_fixture(
            args.binary, args.profiles, painted=args.painted, timeout=args.timeout),
            sort_keys=True))
    except (WorkerError, OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
