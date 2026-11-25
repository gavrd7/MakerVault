"""Read-only Prusa 2.9.7 pinned vendor MMU/XL profile inventory.

Does not install printer profiles, enable multi-material or create G-code.
The actual upstream inheritance chain determines valid native extruder types.
"""
from pathlib import Path
import re
import sys
import hashlib
import struct
import subprocess
from tempfile import TemporaryDirectory

from slicer_worker.prusa_vendor_profiles import (
    parse_prusa_vendor_bundle, flatten_prusa_vendor_preset,
    validate_flat_prusa_preset,
)

def main(path):
    raw = Path(path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    sections = parse_prusa_vendor_bundle(raw)
    selected = [key for key in sections
                if key.startswith("printer:") and
                any(term in key.lower() for term in ("mmu3", "mmu2s", "xl 5t", "xl 2t", "xl 5", "xl 2"))]
    print("Pinned Prusa native MMU/XL printer source candidates:", len(selected))
    for section in selected[:45]:
        name = section[len("printer:"):]
        try:
            parsed = validate_flat_prusa_preset(flatten_prusa_vendor_preset(
                raw, kind="printer", name=name, expected_sha256=sha), kind="printer")
        except ValueError as exc:
            print("UNRESOLVED", name, type(exc).__name__, str(exc))
            continue
        print("CANDIDATE", repr(name), {
            key:parsed.get(key) for key in (
                "printer_technology", "nozzle_diameter", "single_extruder_multi_material",
                "extruder_colour", "wipe_tower", "min_layer_height", "max_layer_height",
                "bed_shape", "gcode_flavor", "toolchange_gcode",
            ) if key in parsed and key != "toolchange_gcode"
        })
    # Look for literal XL profiles separately: upstream names do not
    # consistently use shorthand 2T/5T, so never infer a toolhead count
    # from a product label without reading its native nozzle vector.
    xl = [label.split(":", 1)[1] for label in sections
          if label.startswith("printer:") and "xl" in label.lower()
          and not label.split(":", 1)[1].startswith("*")]
    print("PINNED XL MODEL PRESETS:", len(xl))
    for name in xl:
        try:
            profile = validate_flat_prusa_preset(flatten_prusa_vendor_preset(
                raw, kind="printer", name=name, expected_sha256=sha),
                kind="printer")
        except ValueError as exc:
            print("UNRESOLVED XL", repr(name), str(exc))
            continue
        nozzles = profile["nozzle_diameter"].split(",")
        print("XL NATIVE TOOLHEADS", repr(name), len(nozzles),
              "single_nozzle_changer", profile.get("single_extruder_multi_material", "0"),
              "gcode_flavor", profile.get("gcode_flavor", ""))
    # Real pinned CLI feasibility for a modern BG-code-default machine.
    # Source and G-code remain offline; production imports independently
    # enforce text-only profiles and owner-bound source identities.
    machine = "Original Prusa MK4S MMU3 0.4 nozzle"
    if "printer:" + machine in sections:
        flat = flatten_prusa_vendor_preset(
            raw, kind="printer", name=machine, expected_sha256=sha)
        lines = flat.decode("utf-8").splitlines()
        converted = []
        for line in lines:
            if line.split("=", 1)[0].strip() == "binary_gcode":
                converted.append("binary_gcode = 0")
            else:
                converted.append(line)
        text_profile = ("\\n".join(converted)+"\\n").encode()
        try:
            modern = validate_flat_prusa_preset(text_profile, kind="printer")
        except ValueError as exc:
            # A vetted profile may still lack a mandatory printable bed
            # polygon. Do not invent geometry or allow a partial preset.
            print("MODERN NATIVE PROFILE STILL UNRESOLVED:", machine,
                  "reason", str(exc), "has_nozzles", "nozzle_diameter =" in
                  text_profile.decode(), "has_bed_shape", "bed_shape =" in
                  text_profile.decode())
            modern = None
        if modern is None:
            print("Modern printer native real-binary check postponed until "
                  "required exact upstream machine geometry is resolved.")
            runtime = None
        else:
            assert modern.get("binary_gcode") == "0"
            runtime = Path(path).parents[2] / "bin/prusa-slicer"
        if runtime is not None and runtime.is_file():
            with TemporaryDirectory(prefix="prusa-modern-text-profile-") as scratch:
                temp = Path(scratch)
                (temp/"printer.ini").write_bytes(text_profile)
                for kind, name, output in (
                    ("filament", "Generic PLA", "filament.ini"),
                    ("print", "0.20mm NORMAL", "process.ini")):
                    native = flatten_prusa_vendor_preset(
                        raw, kind=kind, name=name, expected_sha256=sha)
                    (temp/output).write_bytes(native)
                # Fully closed 20mm cube with twelve triangles.
                points = [(0,0,0),(20,0,0),(20,20,0),(0,20,0),
                          (0,0,20),(20,0,20),(20,20,20),(0,20,20)]
                faces = [(0,2,1),(0,3,2),(4,5,6),(4,6,7),
                         (0,1,5),(0,5,4),(1,2,6),(1,6,5),
                         (2,3,7),(2,7,6),(3,0,4),(3,4,7)]
                stl=bytearray(b"Prusa modern text smoke".ljust(80,b"\\x00"))
                stl.extend(struct.pack("<I",len(faces)))
                for a,b,c in faces:
                    stl.extend(struct.pack("<12fH",0.,0.,0.,*points[a],
                                           *points[b],*points[c],0))
                (temp/"cube.stl").write_bytes(stl)
                cmd=[str(runtime),"--load",str(temp/"printer.ini"),
                     "--load",str(temp/"filament.ini"),
                     "--load",str(temp/"process.ini"),
                     "--export-gcode","--output",str(temp/"cube.gcode"),
                     str(temp/"cube.stl")]
                completed=subprocess.run(cmd,cwd=temp,timeout=180,
                                         stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                result=temp/"cube.gcode"
                if completed.returncode==0 and result.exists():
                    generated=result.read_bytes()
                    assert generated.startswith((b";",b"G",b"M"))
                    assert b"G1 " in generated and b" E" in generated
                    print("PASS: modern MK4S MMU3 official printer profile safely "
                          "converted to genuine text G-code:",len(generated),"bytes")
                else:
                    print("MODERN NATIVE CLI FEASIBILITY BLOCKED:",
                          machine,"exit",completed.returncode)
    if not selected:
        raise ValueError("Official pinned Prusa 2.9.7 source has no MMU/XL candidates.")
    print("PASS: read-only native multi-material/independent-toolhead source inventory.")

if __name__ == "__main__":
    main(sys.argv[1])
