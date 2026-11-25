"""Pinned Prusa 2.9.7 must preserve independent placed STL mesh coordinates.

This tests the real native CLI, not an imagined slicer model. The fixture is
a true two-solid, 24-triangle binary STL and is never submitted to a printer.
"""
import argparse
import hashlib
from pathlib import Path
import re
import struct
from tempfile import TemporaryDirectory

from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset
from slicer_worker.runner import run_prusa, prusa_command
from slicer_worker.prusa_gcode_audit import audit_prusa_positive_e
import runpy
cube_stl = runpy.run_path('/tmp/prusa_smoke.py')['cube_stl']


def two_positioned_cubes() -> bytes:
    source = cube_stl()
    triangles = list(struct.iter_unpack("<12fH", source[84:]))
    result = bytearray(b"MakerVault Prusa independently placed test".ljust(80, b"\0"))
    result.extend(struct.pack("<I", len(triangles) * 2))
    for dx in (30.0, 100.0):
        for record in triangles:
            values = list(record)
            for offset in (3,6,9):
                values[offset] += dx
                values[offset+1] += 25.0
            result.extend(struct.pack("<12fH", *values))
    return bytes(result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--vendor", required=True, type=Path)
    args = parser.parse_args()
    vendor = args.vendor.read_bytes()
    digest = hashlib.sha256(vendor).hexdigest()
    with TemporaryDirectory(prefix="prusa-placed-") as tmp:
        workdir = Path(tmp)
        (workdir / "input.stl").write_bytes(two_positioned_cubes())
        (workdir / "prusa-placed-stl.marker").write_text("v1")
        for kind, name, dest in (
            ("printer", "Original Prusa i3 MK2S", "printer.ini"),
            ("filament", "Generic PLA", "filament.ini"),
            ("print", "0.20mm NORMAL", "process.ini"),
        ):
            flat = flatten_prusa_vendor_preset(
                vendor, kind=kind, name=name, expected_sha256=digest)
            (workdir / dest).write_bytes(flat)
        cmd = prusa_command(args.binary, workdir)
        assert "--dont-arrange" in cmd, cmd
        receipt = run_prusa(args.binary, workdir, timeout_seconds=300)
        data = Path(receipt["gcode_path"]).read_bytes()
        quality = audit_prusa_positive_e(data)
        assert quality["positive_e_moves"] >= 40, quality
        positions = []
        for line in data.decode("utf-8", "replace").splitlines():
            if not re.match(r"^G0?1\s", line):
                continue
            x = re.search(r"\bX(-?\d+(?:\.\d+)?)", line)
            e = re.search(r"\bE(-?\d+(?:\.\d+)?)", line)
            if x and e and float(e.group(1)) > 0:
                positions.append(float(x.group(1)))
        assert positions, "No positioned extrusion coordinates found"
        assert any(79 <= x <= 101 for x in positions), (
            "First native cube was not extruded at its original coordinates")
        assert any(149 <= x <= 171 for x in positions), (
            "Second native cube was not extruded at its original coordinates")
        assert not any(x < -1 or x > 251 for x in positions), (
            "Native cube extrusion escaped the pinned MK2S 250mm build area")
        print("PASS: real Prusa 2.9.7 preserved two independent cube positions "
              + "and extruded native toolpaths at X80-100 and X150-170; "
              + str(quality["positive_e_moves"]) + " extrusion moves")


if __name__ == "__main__":
    main()
