"""Native printer-compatibility fixtures are bounded, offline, and tool-agnostic."""
import io
import zipfile
from defusedxml import ElementTree as ET
from django.test import SimpleTestCase

from core.management.commands.diagnose_slicer_printer_profiles import (
    _fixture_items, _safe_native_result, _same_native_pair,
)
from core.slicer_plate_3mf import build_plate_3mf, NS


class PrinterCompatibilityFixtureTests(SimpleTestCase):
    def test_distinct_2_3_4_material_fixtures_on_verified_beds(self):
        for count in (2, 3, 4):
            for width, depth in ((90, 90), (180, 180), (350, 350)):
                with self.subTest(count=count, width=width):
                    items = _fixture_items(count, width, depth)
                    self.assertEqual(len(items), count)
                    self.assertEqual(len(set(item["instance_id"] for item, _ in items)),
                                     count)
                    self.assertEqual(len(set(item["x_mm"] for item, _ in items)), count)
                    project = build_plate_3mf(
                        items, bed_width=width, bed_depth=depth,
                        native_tool_indices=list(range(count)))
                    with zipfile.ZipFile(io.BytesIO(project)) as archive:
                        root = ET.fromstring(archive.read("3D/3dmodel.model"))
                    ns = "{" + NS + "}"
                    objects = root.findall("./" + ns + "resources/" + ns + "object")
                    self.assertEqual(len(objects), count)

    def test_small_bed_or_invalid_tool_count_fails_closed(self):
        for count, width, depth in ((0, 180, 180), (5, 180, 180),
                                    (2, 89, 200), (3, 200, 70)):
            with self.subTest(count=count, width=width, depth=depth):
                with self.assertRaises(ValueError):
                    _fixture_items(count, width, depth)

    def test_offline_native_result_exposes_digest_only(self):
        sample = (b";PRIVATE_MACHINE_GCODE\n"
                  b"G1 X1 Y1 E0.1\n"
                  b"G1 X2 Y2 E0.2\n"
                  b"T0\nM117 CHANGE\n")
        report = _safe_native_result(sample)
        self.assertEqual(len(report["gcode_sha256"]), 64)
        self.assertEqual(len(report["motion_sha256"]), 64)
        self.assertEqual(len(report["machine_command_sha256"]), 64)
        self.assertEqual(report["g1_with_extrusion"], 2)
        self.assertNotIn("PRIVATE_MACHINE_GCODE", str(report))
        self.assertNotIn("M117 CHANGE", str(report))

    def test_selected_profiles_must_share_owner_engine_and_version(self):
        class Profile:
            owner_id = "user1"
            engine = "orcaslicer"
            engine_version = "2.4.2"
            kind = "filament"
            status = "candidate"
        profile = Profile()
        self.assertTrue(_same_native_pair(
            profile, "user1", "orcaslicer", "2.4.2", "filament"))
        self.assertFalse(_same_native_pair(
            profile, "user2", "orcaslicer", "2.4.2", "filament"))
        self.assertFalse(_same_native_pair(
            profile, "user1", "crealityprint", "2.4.2", "filament"))
        self.assertFalse(_same_native_pair(
            profile, "user1", "orcaslicer", "2.5.0", "filament"))
        self.assertFalse(_same_native_pair(
            profile, "user1", "orcaslicer", "2.4.2", "printer"))
        profile.status = "unverified_invalid"
        self.assertFalse(_same_native_pair(
            profile, "user1", "orcaslicer", "2.4.2", "filament"))
