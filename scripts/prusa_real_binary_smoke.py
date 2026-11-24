"""One independently qualified real PrusaSlicer FFF CLI G-code smoke.

Called *only* by the opt-in source-pinned runtime candidate workflow.
No printer, cloud, registry or installed MakerVault engine is modified.
"""
import argparse
import hashlib
import math
from pathlib import Path
import re
import struct
from tempfile import TemporaryDirectory

from slicer_worker.prusa_vendor_profiles import (
    flatten_prusa_vendor_preset, validate_flat_prusa_preset)
from slicer_worker.runner import run_prusa


def cube_stl() -> bytes:
    # Closed, outward-facing 20 mm cube, positioned within the MK2S 250 mm bed.
    points = [
        (50, 50, 0), (70, 50, 0), (70, 70, 0), (50, 70, 0),
        (50, 50, 20), (70, 50, 20), (70, 70, 20), (50, 70, 20),
    ]
    faces = [
        (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
        (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7),
    ]
    output = bytearray(b"MakerVault PrusaSlicer v2.9.7 CLI fixture".ljust(80, b"\0"))
    output.extend(struct.pack("<I", len(faces)))
    for triangle in faces:
        vec = [value for index in triangle for value in points[index]]
        output.extend(struct.pack("<12fH", 0, 0, 0, *vec, 0))
    return bytes(output)


def audit_positive_extrusion(gcode: bytes) -> dict:
    """Require actual XYZ/E deposition, not just a header, preview or G0."""
    if len(gcode) < 2000 or b"\0" in gcode[:4096]:
        raise ValueError("Prusa real-binary smoke emitted empty or binary output.")
    count = 0
    total_e = 0.
    for line in gcode.decode("utf-8", "replace").splitlines():
        command = line.split(";", 1)[0].strip()
        if not re.match(r"^G0?1(?:\s|$)", command):
            continue
        params = dict((key.upper(), float(value)) for key, value in
                      re.findall(r"([XYZE])\s*([-+]?(?:\d+\.?\d*|\.\d+))", command))
        if "E" in params and {"X", "Y"} & params.keys() and params["E"] > 0:
            if not math.isfinite(params["E"]):
                raise ValueError("Prusa CLI emitted nonfinite extrusion.")
            count += 1
            total_e += params["E"]
    if count < 20 or total_e <= 0:
        raise ValueError("Prusa CLI smoke did not produce positive-E toolpaths.")
    return {"positive_e_moves": count, "sample_positive_e_sum": round(total_e, 4)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--vendor", type=Path, required=True)
    args = parser.parse_args()
    raw = args.vendor.read_bytes()
    source_sha = hashlib.sha256(raw).hexdigest()
    profiles = (
        ("printer", "Original Prusa i3 MK2S", "printer.ini"),
        ("filament", "Generic PLA", "filament.ini"),
        ("print", "0.20mm NORMAL", "process.ini"),
    )
    with TemporaryDirectory(prefix="prusa-297-verified-") as work:
        folder = Path(work)
        (folder / "input.stl").write_bytes(cube_stl())
        for kind, name, filename in profiles:
            flat = flatten_prusa_vendor_preset(
                raw, kind=kind, name=name, expected_sha256=source_sha)
            validate_flat_prusa_preset(flat, kind=kind)
            (folder / filename).write_bytes(flat)
        receipt = run_prusa(args.binary.resolve(strict=True), folder, timeout_seconds=300)
        data = Path(receipt["gcode_path"]).read_bytes()
        result = audit_positive_extrusion(data)
        print(
            f"Prusa 2.9.7 genuine FFF cube slice passed: {len(data)} G-code bytes, "
            f"{result['positive_e_moves']} positive-E moves, "
            f"native vendor SHA-256 {source_sha}, "
            f"G-code SHA-256 {hashlib.sha256(data).hexdigest()}"
        )


if __name__ == "__main__":
    main()
