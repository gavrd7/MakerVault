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

    def test_one_painted_object_maps_base_then_painted_cfs_slot(self):
        from core.slicer_creality_cfs_audit import creality_cfs_audit_objects
        painted = [{
            **self.objects[0],
            "colour_paint": {
                "version": 2, "signature": "2:deadbeef",
                "palette": [
                    {"color": "#777777", "label": "Grey", "printer_id":
                     "11111111-1111-4111-8111-111111111111",
                     "slot_id": "grey", "slot_index": 3},
                    {"color": "#FADD4D", "label": "Yellow", "printer_id":
                     "11111111-1111-4111-8111-111111111111",
                     "slot_id": "yellow", "slot_index": 0},
                ],
                "regions": [{"slot": 1, "patches": [
                    {"face": 0, "polygon": [[0,0,0], [1,0,0], [0,1,0]]}
                ]}],
            },
        }]
        painted[0]["material_slot"]["printer_id"] = "11111111-1111-4111-8111-111111111111"
        for row in self.rows:
            row.printer_id = "11111111-1111-4111-8111-111111111111"
        expanded = creality_cfs_audit_objects(
            painted, printer_id="11111111-1111-4111-8111-111111111111")
        self.assertEqual(len(expanded), 2)
        self.assertEqual(expanded[0]["material_slot"]["slot_id"], "grey")
        self.assertEqual(expanded[1]["material_slot"]["slot_id"], "yellow")
        self.assertEqual(expanded[1]["color"].upper(), "#FADD4D")
        report = audit_creality_cfs_assignments(
            expanded, self.rows, self.context,
            printer_id="11111111-1111-4111-8111-111111111111")
        self.assertEqual([row["slot_label"] for row in report["mapping"]],
                         ["1D", "2A"])

    def test_one_painted_object_rejects_unassigned_or_extra_slot(self):
        from core.slicer_creality_cfs_audit import creality_cfs_audit_objects
        obj = dict(self.objects[0])
        obj["colour_paint"] = {
            "version": 2, "signature": "2:deadbeef",
            "palette": [{"color": "#FADD4D", "label": "Yellow"}],
            "regions": [{"slot": 0, "patches": [
                {"face": 0, "polygon": [[0,0,0], [1,0,0], [0,1,0]]}
            ]}],
        }
        with self.assertRaises(CrealityCfsAuditError):
            creality_cfs_audit_objects([obj], printer_id="p")

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

    def test_two_database_slots_cannot_resolve_to_one_bay(self):
        self.rows[1].unit_index = 0
        self.rows[1].slot_index = 3
        self.objects[1]["material_slot"]["slot_index"] = 3
        with self.assertRaisesRegex(CrealityCfsAuditError, "same CFS bay"):
            self.audit()

    def test_same_physical_slot_cannot_serve_two_tools(self):
        self.objects[1]["material_slot"] = dict(self.objects[0]["material_slot"])
        with self.assertRaisesRegex(CrealityCfsAuditError, "distinct CFS slots"):
            self.audit()

    def test_completed_slice_gcode_must_match_live_slot_identity(self):
        import hashlib
        from core.slicer_creality_cfs_audit import audit_creality_gcode_for_cfs
        raw = (
            b"; filament_type = PLA-Silk;PLA-Silk;PLA-Silk;PLA-Silk\n"
            b"; filament_colour = #777777;#FADD4D;#777777;#FADD4D\n"
            b"T0\nM83\nG1 X1 Y1 E0.2\nT1\nG1 X2 Y2 E0.2\n"
        )
        asset = SimpleNamespace(
            sha256=hashlib.sha256(raw).hexdigest(),
            metadata={"slice_job_id": "job", "printer_id": "p",
                      "multi_material_test": True, "printer_submission_verified": False},
        )
        job = SimpleNamespace(pk="job", printer_id="p", engine="crealityprint",
                              status="completed", output_asset=asset)
        result = audit_creality_gcode_for_cfs(job, self.audit(), raw)
        self.assertTrue(result["gcode_material_preflight_passed"])
        self.assertFalse(result["printer_submission_verified"])
        self.assertEqual(result["verified_gcode_tools"], [0, 1])
        altered = raw.replace(b"#FADD4D", b"#FFFFFF")
        with self.assertRaisesRegex(CrealityCfsAuditError, "SHA-256"):
            audit_creality_gcode_for_cfs(job, self.audit(), altered)
        asset.sha256 = hashlib.sha256(altered).hexdigest()
        with self.assertRaisesRegex(CrealityCfsAuditError, "colour differs"):
            audit_creality_gcode_for_cfs(job, self.audit(), altered)

    def test_gcode_preflight_rejects_missing_second_tool(self):
        import hashlib
        from core.slicer_creality_cfs_audit import audit_creality_gcode_for_cfs
        raw = (b"; filament_type = PLA;PLA;PLA;PLA\n"
               b"; filament_colour = #777777;#FADD4D;#777777;#FADD4D\n"
               b"T0\nM83\nG1 X1 Y1 E0.2\n")
        asset = SimpleNamespace(
            sha256=hashlib.sha256(raw).hexdigest(),
            metadata={"slice_job_id": "job", "printer_id": "p",
                      "multi_material_test": True, "printer_submission_verified": False},
        )
        job = SimpleNamespace(pk="job", printer_id="p", engine="crealityprint",
                              status="completed", output_asset=asset)
        with self.assertRaisesRegex(CrealityCfsAuditError, "tool/extrusion"):
            audit_creality_gcode_for_cfs(job, self.audit(), raw)
