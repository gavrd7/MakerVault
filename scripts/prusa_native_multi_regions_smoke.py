"""Pinned native acceptance for two independent Prusa printable model volumes."""
import hashlib
from pathlib import Path
import runpy
import subprocess
import sys
from tempfile import TemporaryDirectory
from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset

def main(binary, vendor, baseline, modifier, negative, mixed_dir=None):
    sample = runpy.run_path("/tmp/prusa_regions.py")["regional_extrusion"]
    raw = Path(vendor).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    with TemporaryDirectory(prefix="prusa-two-object-regions-") as tmp:
        work = Path(tmp)
        profiles = []
        for kind, name in (("printer", "Original Prusa i3 MK2S"),
                           ("filament", "Generic PLA"), ("print", "0.20mm NORMAL")):
            path = work / (kind + ".ini")
            path.write_bytes(flatten_prusa_vendor_preset(raw, kind=kind,
                            name=name, expected_sha256=digest))
            profiles.extend(["--load", str(path)])
        receipts = {}
        for label, project in (("baseline", baseline), ("modifier", modifier), ("negative", negative)):
            output = work / (label + ".gcode")
            subprocess.run([binary, *profiles, "--export-gcode", "--dont-arrange",
                            "--output", str(output), project], cwd=work,
                            check=True, timeout=300)
            data = output.read_bytes()
            receipts[label] = tuple(sample(data, center_x=x, center_y=105)
                                    for x in (90, 160))
            print("Prusa two-object regional extrusion", label, receipts[label])
        for i in range(2):
            original = receipts["baseline"][i]
            changed = receipts["modifier"][i]
            negative = receipts["negative"][i]
            assert original[0] > .1 and original[1] > .1, ("no baseline", i, original)
            assert changed[0] > original[0]*1.5 and changed[1] > .1, (
                "modifier not applied to independent object", i, original, changed)
            assert negative[0] < .01 and negative[1] > .1, (
                "negative did not cut independent object", i, negative)
        print("PASS: both native Prusa 3MF printable objects independently honour their modifiers and negative volumes.")

        if mixed_dir is not None:
            controls = {}
            for label in ("mix-baseline", "mix-modifier", "mix-object", "mix-both"):
                output = work / (label + ".gcode")
                subprocess.run([
                    binary, *profiles, "--export-gcode", "--dont-arrange",
                    "--output", str(output), str(Path(mixed_dir) / (label + ".3mf")),
                ], cwd=work, check=True, timeout=300)
                controls[label] = tuple(
                    sample(output.read_bytes(), center_x=x, center_y=105)
                    for x in (90, 160))
                print("Prusa combined native Object/Modifier deposition",
                      label, controls[label], flush=True)
            baseline_counts = controls["mix-baseline"]
            modifier_counts = controls["mix-modifier"]
            object_counts = controls["mix-object"]
            mixed_counts = controls["mix-both"]
            # Independently check the *unmodified* neighbouring model in
            # both single-feature controls. It must keep baseline extrusion.
            for index, solo in ((1, modifier_counts), (0, object_counts)):
                baseline_inside = baseline_counts[index][0]
                if baseline_inside <= .1 or not .7 <= (
                        solo[index][0] / baseline_inside) <= 1.3:
                    raise AssertionError(
                        ("Prusa native regional feature contaminated neighbour",
                         index, solo, baseline_counts))
            # A modifier changes only model 1's central infill; a distinct
            # model's process override changes only model 2. Require both
            # effects to survive simultaneous native 3MF import and slicing.
            for index, solo in ((0, modifier_counts), (1, object_counts)):
                if (baseline_counts[index][0] <= .1 or
                        solo[index][0] <= baseline_counts[index][0] * 1.5 or
                        mixed_counts[index][0] <= baseline_counts[index][0] * 1.5):
                    raise AssertionError(
                        ("Prusa combined Object and modifier effect absent",
                         index, baseline_counts, solo, mixed_counts))
                ratio = mixed_counts[index][0] / solo[index][0]
                if not .7 <= ratio <= 1.3:
                    raise AssertionError(
                        ("Prusa combined Object and modifier affected another model",
                         index, ratio, solo, mixed_counts))
                if mixed_counts[index][1] <= .1:
                    raise AssertionError("Prusa combined native project lost outer infill.")
            print("PASS: Prusa two-object native parameter modifiers and Object settings "
                  "deposit independently without neighbour contamination.", flush=True)

            cavity = work / "mix-negative-object.gcode"
            subprocess.run([
                binary, *profiles, "--export-gcode", "--dont-arrange",
                "--output", str(cavity),
                str(Path(mixed_dir) / "mix-negative-object.3mf"),
            ], cwd=work, check=True, timeout=300)
            cavity_counts = tuple(
                sample(cavity.read_bytes(), center_x=x, center_y=105)
                for x in (90, 160))
            print("Prusa native cavity plus independent Object settings",
                  cavity_counts, flush=True)
            if (cavity_counts[0][0] >= .01 or
                    cavity_counts[0][1] <= .1 or
                    cavity_counts[1][0] <= baseline_counts[1][0] * 1.5 or
                    cavity_counts[1][1] <= .1):
                raise AssertionError(
                    ("Prusa native cavity/other Object setting contaminated "
                     "either model", cavity_counts, baseline_counts))
            print("PASS: Prusa cavity removes native material on model A while "
                  "an independent Object setting changes model B.", flush=True)

            stacked = {}
            for label in ("stack-object", "stack-both"):
                output = work / (label + ".gcode")
                subprocess.run([
                    binary, *profiles, "--export-gcode", "--dont-arrange",
                    "--output", str(output),
                    str(Path(mixed_dir) / (label + ".3mf")),
                ], cwd=work, check=True, timeout=300)
                stacked[label] = tuple(
                    sample(output.read_bytes(), center_x=x, center_y=105)
                    for x in (90, 160))
                print("Prusa stacked Object and modifier deposition",
                      label, stacked[label], flush=True)
            alone, combined = stacked["stack-object"], stacked["stack-both"]
            if (alone[0][0] <= .1 or combined[0][0] <= alone[0][0]*1.5
                    or min(alone[0][1], combined[0][1]) <= .1):
                raise AssertionError(
                    ("Prusa same-model modifier lost its local effect",
                     alone, combined))
            if not .7 <= combined[0][1] / alone[0][1] <= 1.3:
                raise AssertionError(
                    ("Prusa same-model region unexpectedly changed outer deposition",
                     alone, combined))
            for part in (0, 1):
                if not .7 <= combined[1][part] / baseline_counts[1][part] <= 1.3:
                    raise AssertionError(
                        ("Prusa modifier/Object stack contaminated the other model",
                         part, combined, baseline_counts))
            print("PASS: Prusa two-model Object infill and local box modifier "
                  "stack on one model without neighbour contamination.", flush=True)




if __name__ == "__main__":
    main(*sys.argv[1:])
