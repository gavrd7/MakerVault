"""Physical CFS slot identity verification must remain read-only."""
from types import SimpleNamespace
from django.test import SimpleTestCase

from core.slicer_creality_cfs_audit import (
    audit_creality_cfs_assignments, CrealityCfsAuditError,
)


class CrealityCfsAuditTests(SimpleTestCase):
    def setUp(self):
        self.objects = [
            {"color": "#777777", "material_slot": {
                "printer_id": "p", "slot_id": "grey", "slot_index": 3}},
            {"color": "#fadd4d", "material_slot": {
                "printer_id": "p", "slot_id": "yellow", "slot_index": 0}},
        ]
        self.rows = [
            SimpleNamespace(pk="grey", printer_id="p", system="creality_cfs",
                            is_loaded=True, unit_index=0, slot_index=3),
            SimpleNamespace(pk="yellow", printer_id="p", system="creality_cfs",
                            is_loaded=True, unit_index=1, slot_index=0),
        ]
        self.context = {"verified": True, "connected": True, "slots": [
            {"box_id": 1, "slot_id": 3, "label": "1D",
             "material": "PLA", "color_hex": "#777777"},
            {"box_id": 2, "slot_id": 0, "label": "2A",
             "material": "PLA", "color_hex": "#FADD4D"},
        ]}

    def audit(self):
        return audit_creality_cfs_assignments(
            self.objects, self.rows, self.context, printer_id="p")

    def test_non_contiguous_bays_keep_logical_tool_order(self):
        report = self.audit()
        self.assertEqual([row["slot_label"] for row in report["mapping"]],
                         ["1D", "2A"])
        self.assertEqual([row["tool_index"] for row in report["mapping"]], [0, 1])
        self.assertEqual([row["material_id"] for row in report["mapping"]], [3, 0])
        self.assertFalse(report["printer_submission_verified"])

    def test_stale_telemetry_fails_closed(self):
        self.context["verified"] = False
        with self.assertRaisesRegex(CrealityCfsAuditError, "Fresh"):
            self.audit()

    def test_wrong_colour_fails_closed(self):
        self.context["slots"][0]["color_hex"] = "#FFFFFF"
        with self.assertRaisesRegex(CrealityCfsAuditError, "colour differs"):
            self.audit()

    def test_missing_or_changed_slot_fails_closed(self):
        self.rows[0].slot_index = 2
        with self.assertRaisesRegex(CrealityCfsAuditError, "index has changed"):
            self.audit()

    def test_cross_printer_slot_fails_closed(self):
        self.rows[0].printer_id = "other"
        with self.assertRaisesRegex(CrealityCfsAuditError, "not a loaded"):
            self.audit()

    def test_same_physical_slot_cannot_serve_two_tools(self):
        self.objects[1]["material_slot"] = dict(self.objects[0]["material_slot"])
        with self.assertRaisesRegex(CrealityCfsAuditError, "distinct CFS slots"):
            self.audit()
