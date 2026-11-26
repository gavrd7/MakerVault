"""Real Prusa 2.9.7 seam acceptance: exact painted patch versus baseline."""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
from tempfile import TemporaryDirectory

from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset
from slicer_worker.prusa_gcode_audit import WORD


def first_external_wall_starts(data):
    """Research only: inspect real first external perimeters, not an XML flag."""
    role = ""
    relative = False
    e = 0.
    pos = {"X": None, "Y": None, "Z": None}
    captured = False
    starts = []
    for line in data.decode("utf-8").splitlines():
        stripped = line.strip()
        if stripped == ";LAYER_CHANGE":
            captured = False
        if stripped.startswith(";TYPE:"):
            role = stripped.partition(":")[2].strip().lower()
        cmd = stripped.split(";", 1)[0].strip()
        if not cmd:
            continue
        op = cmd.split(None, 1)[0].upper()
        if op not in ("G0", "G00", "G1", "G01", "G92", "M82", "M83"):
            continue
        words = {key.upper(): float(value) for key, value in WORD.findall(cmd)}
        if op == "M82":
            relative = False
        elif op == "M83":
            relative = True
        elif op == "G92":
            e = words.get("E", e)
        else:
            pos.update({k: value for k, value in words.items() if k in pos})
            if "E" in words:
                extrusion = words["E"] if relative else words["E"]-e
                e = e+words["E"] if relative else words["E"]
                if (not captured and extrusion > 1e-6 and
                        "external perimeter" in role and
                        all(v is not None for v in pos.values()) and
                        3 < pos["Z"] < 17):
                    starts.append((round(pos["X"],2),round(pos["Y"],2)))
                    captured = True
    return {"layers": len(starts), "unique_starts": sorted(set(starts))[:8]}


def override_research_seam_position(source, mode):
    """Only native-research process-profile edits; never mutate owner presets."""
    if mode is None:
        return source
    if mode not in ("rear", "aligned", "nearest", "random"):
        raise ValueError("Unrecognised Prusa seam-position research mode.")
    clean = [line for line in source.splitlines()
             if line.partition(b"=")[0].strip() != b"seam_position"]
    return b"\n".join(clean) + (b"\nseam_position = " +
                              mode.encode("ascii") + b"\n")


def main(binary, vendor, directory, seam_mode=None):
    audit = runpy.run_path("/tmp/prusa_seam_audit.py")["audit_prusa_seam_enforcer_gcode"]
    raw = Path(vendor).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    model = Path(directory)
    names = ("seam-front", "seam-back", "seam-left", "seam-right")
    with TemporaryDirectory(prefix="prusa-seam-acceptance-") as temp:
        root = Path(temp)
        options = []
        for kind, preset in (("printer", "Original Prusa i3 MK2S"),
                             ("filament", "Generic PLA"),
                             ("print", "0.20mm NORMAL")):
            ini = root / (kind + ".ini")
            resolved = flatten_prusa_vendor_preset(
                raw, kind=kind, name=preset, expected_sha256=digest)
            ini.write_bytes(override_research_seam_position(
                resolved, seam_mode) if kind == "print" else resolved)
            options.extend(["--load", str(ini)])
        verified = []
        for name in ("baseline", *names):
            output = root / (name + ".gcode")
            subprocess.run([binary, *options, "--export-gcode", "--dont-arrange",
                            "--output", str(output), str(model / (name + ".3mf"))],
                           cwd=root, check=True, timeout=300)
        baseline = (root / "baseline.gcode").read_bytes()
        for name in names:
            item = json.loads((model / (name + ".json")).read_text())
            print("Native seam directional G-code", seam_mode or "profile-default", name,
                  first_external_wall_starts((root / (name + ".gcode")).read_bytes()))
            try:
                observed = audit((root / (name + ".gcode")).read_bytes(),
                                 item, bed_width=250, bed_depth=210)
            except ValueError as exc:
                print("UNQUALIFIED native seam direction", seam_mode or "profile-default", name, str(exc))
                continue
            try:
                audit(baseline, item, bed_width=250, bed_depth=210)
            except ValueError:
                print("QUALIFIED native seam direction", seam_mode or "profile-default", name, observed)
                verified.append(name)
            else:
                print("UNQUALIFIED native seam direction", seam_mode or "profile-default", name,
                      "baseline also satisfies the painted patch")
        if len(verified) < 2:
            raise AssertionError("No independent pair of painted Prusa seam directions has real spatial proof.")
        print("PASS: native Prusa seam painting directed independently:", verified)


if __name__ == "__main__":
    main(*sys.argv[1:])
