"""Only explicitly selected native Creality CFS presets can pass the offline gate."""
import json
from django.test import SimpleTestCase

from core.slicer_creality_release_gate import (
    CrealityCfsGateError, selected_creality_multicolor_capability,
    audit_creality_multicolor_gcode,
)


class CrealityReleaseGateTests(SimpleTestCase):
    def test_stock_machine_remains_disabled_without_opt_in(self):
        for config in ({}, {"multicolor_method": "0"},
                       {"multicolor_method": 0},
                       {"multicolor_method": False}):
            with self.subTest(config=config):
                self.assertFalse(selected_creality_multicolor_capability(
                    json.dumps(config).encode()))
        for config in ({"multicolor_method": "1"}, {"multicolor_method": 1},
                       {"multicolor_method": True}):
            self.assertTrue(selected_creality_multicolor_capability(
                json.dumps(config).encode()))
        for invalid in ({"multicolor_method": 1.0},
                        {"multicolor_method": "yes"},
                        {"multicolor_method": []}):
            with self.subTest(config=invalid), self.assertRaises(
                    CrealityCfsGateError):
                selected_creality_multicolor_capability(
                    json.dumps(invalid).encode())

    def test_real_native_sections_required_but_not_printer_approval(self):
        valid = (
            b"M83\nT0\nT1\nM8200 P0\n"
            b"; FLUSH_START\nG1 E10 F600\n; FLUSH_END\n"
        )
        report = audit_creality_multicolor_gcode(valid)
        self.assertTrue(report["offline_native_purge_observed"])
        self.assertFalse(report["printer_submission_approved"])
        self.assertEqual(report["balanced_flush_sections"], 1)
        for rejected in (
                b"M83\nT0\nT1\n",
                valid.replace(b"M8200 P0\n", b""),
                valid.replace(b"; FLUSH_END\n", b""),
                valid.replace(b"M83\n", b"M82\n"),
                valid.replace(b"G1 E10 F600\n", b"G1 X2 E10\n"),
                valid.replace(b"; FLUSH_END\n", b"; FLUSH_START\n"),
                b"",
        ):
            with self.subTest(payload=rejected), self.assertRaises(
                    CrealityCfsGateError):
                audit_creality_multicolor_gcode(rejected)

    def test_no_ambiguous_or_absolute_approvals(self):
        gcode = (
            b"M83\nT0\nT1\nM8200 P0\n; FLUSH_START\n"
            b"M82\nG1 E10\n; FLUSH_END\n"
        )
        with self.assertRaises(CrealityCfsGateError):
            audit_creality_multicolor_gcode(gcode)
