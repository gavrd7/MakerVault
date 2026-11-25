"""Real pinned Prusa CLI qualification for numeric process overrides."""
import hashlib
import math
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

from slicer_worker.prusa_process_overrides import apply_prusa_process_overrides, FIELDS
from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset, validate_flat_prusa_preset
from slicer_worker.runner import run_prusa
from slicer_worker.prusa_gcode_audit import audit_prusa_positive_e

BASE = b"layer_height = 0.2\nperimeters = 2\ntop_solid_layers = 4\nbottom_solid_layers = 3\nfill_density = 15%\nbrim_width = 0\nskirts = 1\n"
VALUES = {"layer_height": .25, "wall_loops": 3, "top_shell_layers": 5,
          "bottom_shell_layers": 4, "sparse_infill_density": 30,
          "brim_width": 3, "skirt_loops": 2}


class OverrideTests(unittest.TestCase):
    def test_native_mapping(self):
        output = apply_prusa_process_overrides(BASE, VALUES)
        parsed = validate_flat_prusa_preset(output, kind="print")
        self.assertEqual(parsed, {"layer_height": "0.25", "perimeters": "3",
            "top_solid_layers": "5", "bottom_solid_layers": "4",
            "fill_density": "30%", "brim_width": "3", "skirts": "2"})
        self.assertEqual(apply_prusa_process_overrides(BASE, {}), BASE)

    def test_native_speed_controls_are_bounded_and_never_execute_user_strings(self):
        raw = (BASE + b"external_perimeter_speed = 30\nperimeter_speed = 40\n"
               b"infill_speed = 70\ntravel_speed = 130\n"
               b"top_solid_infill_speed = 35\n")
        speeds = {"outer_wall_speed": 22, "inner_wall_speed": 38,
                  "sparse_infill_speed": 60, "travel_speed": 150,
                  "top_surface_speed": 25}
        result = validate_flat_prusa_preset(
            apply_prusa_process_overrides(raw, speeds), kind="print")
        for key, requested in speeds.items():
            self.assertEqual(float(result[FIELDS[key][0]]), requested)
        for invalid in (
            {"outer_wall_speed": 1}, {"travel_speed": 900},
            {"top_surface_speed": float("nan")},
            {"inner_wall_speed": "G28\npost_process=evil"},
            {"sparse_infill_speed": True}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                apply_prusa_process_overrides(raw, invalid)

    def test_invalid(self):
        for override in ({"post_process": "evil"}, {"wall_loops": 2.5},
                         {"layer_height": float("nan")}, {"brim_width": True},
                         {"sparse_infill_density": 101}, {"layer_height": "0.2\nfoo=bar"}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                apply_prusa_process_overrides(BASE, override)
        with self.assertRaises(ValueError):
            apply_prusa_process_overrides(b"layer_height = 0.2\n", {"wall_loops": 3})


def native_smoke(binary, vendor, cube):
    raw = Path(vendor).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    profiles = {kind: flatten_prusa_vendor_preset(raw, kind=kind, name=name,
                                                expected_sha256=sha)
                for kind, name in (("printer", "Original Prusa i3 MK2S"),
                                   ("filament", "Generic PLA"),
                                   ("print", "0.20mm NORMAL"))}
    with TemporaryDirectory(prefix="prusa-overrides-") as work:
        folder = Path(work)
        (folder / "input.stl").write_bytes(cube)
        for kind in ("printer", "filament"):
            (folder / (kind + ".ini")).write_bytes(profiles[kind])
        results = []
        speed_values = {
            "outer_wall_speed": 22, "inner_wall_speed": 38,
            "sparse_infill_speed": 60, "travel_speed": 150,
            "top_surface_speed": 25,
        }
        for overrides in ({}, VALUES, speed_values):
            (folder / "process.ini").write_bytes(apply_prusa_process_overrides(profiles["print"], overrides))
            receipt = run_prusa(Path(binary), folder, timeout_seconds=300)
            data = Path(receipt["gcode_path"]).read_bytes()
            assert audit_prusa_positive_e(data)["positive_e_moves"] >= 20
            lines = data.decode("utf-8").splitlines()
            settings = {}
            for line in lines:
                match = re.fullmatch(r"; ([a-z_]+) = (.*)", line)
                if match:
                    settings[match[1]] = match[2]
            if overrides:
                for key, value in overrides.items():
                    native, _, _, _, suffix = FIELDS[key]
                    actual = settings[native]
                    assert actual.endswith(suffix) and math.isclose(float(actual.rstrip("%")), value), (native, actual)
            layers = sum(line.strip() == ";LAYER_CHANGE" for line in lines)
            assert layers > 0
            from hashlib import sha256
            motions = "\\n".join(line.partition(";")[0] for line in lines
                                if line.lstrip().startswith(("G0 ", "G1 ")))
            results.append({"layers": layers, "motion": sha256(
                motions.encode("utf-8")).hexdigest()})
            Path(receipt["gcode_path"]).unlink()
        assert results[1]["layers"] < results[0]["layers"], results
        assert results[2]["layers"] == results[0]["layers"], results
        assert results[2]["motion"] != results[0]["motion"], (
            "Native Prusa speed controls did not affect real G-code movement.")
        print("PASS: five Prusa native speed overrides changed genuine toolpaths.")
        print("PASS: seven original native overrides and five speed controls echoed in genuine G-code", results)
