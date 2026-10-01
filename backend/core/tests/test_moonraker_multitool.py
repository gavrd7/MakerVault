from unittest.mock import patch

from django.test import SimpleTestCase

from core.printer_connectivity import PrinterConnectionError, poll_moonraker


class MoonrakerMultiToolTests(SimpleTestCase):
    def poll(self, available, extra=None, active="extruder1"):
        responses = [
            {"result": {"klippy_state": "ready"}},
            {"result": {"status": {
                "print_stats": {"state": "printing", "filename": "part.gcode"},
                "extruder": {"temperature": 190, "target": 200},
                "heater_bed": {"temperature": 60, "target": 60},
                "heaters": {"available_heaters": available},
                "toolhead": {"extruder": active},
            }}},
        ]
        if extra is not None:
            responses.append(extra)
        with patch("core.printer_connectivity._get", side_effect=responses) as get:
            snapshot = poll_moonraker("http://printer.local:7125", {"api_key": "test-key"})
        return snapshot, get

    def test_discovered_tools_keep_indices_and_active_tool(self):
        snapshot, get = self.poll(
            ["extruder3", "extruder", "extruder1", "extruder1", "heater_bed"],
            {"result": {"status": {
                "extruder1": {"temperature": 220, "target": 225},
                "extruder3": {"temperature": 25, "target": 0},
            }}},
        )
        self.assertEqual(snapshot["temperatures"]["tool1"]["actual_c"], 220)
        self.assertEqual(snapshot["temperatures"]["tool3"]["target_c"], 0)
        self.assertNotIn("tool2", snapshot["temperatures"])
        self.assertEqual(snapshot["source_metadata"]["active_tool"], "tool1")
        self.assertTrue(get.call_args.args[0].endswith("?extruder1&extruder3"))
        self.assertEqual(get.call_args.kwargs["headers"]["X-Api-Key"], "test-key")
        self.assertEqual(snapshot["materials"], [])

    def test_legacy_single_tool_needs_no_extra_request(self):
        snapshot, get = self.poll(None, active="extruder")
        self.assertEqual(get.call_count, 2)
        self.assertEqual(snapshot["temperatures"]["tool0"]["actual_c"], 190)
        self.assertEqual(snapshot["source_metadata"]["active_tool"], "tool0")

    def test_untrusted_names_cannot_add_query_parameters(self):
        snapshot, get = self.poll(["extruder1&configfile", "extruder01", {}, "heater_generic chamber"])
        self.assertEqual(get.call_count, 2)
        self.assertIsNone(snapshot["source_metadata"]["active_tool"])

    def test_extra_query_failure_preserves_print_monitoring(self):
        snapshot, _ = self.poll(["extruder1"], PrinterConnectionError("offline"))
        self.assertEqual(snapshot["state"], "printing")
        self.assertEqual(snapshot["job"]["file_name"], "part.gcode")
        self.assertEqual(snapshot["temperatures"]["bed"]["actual_c"], 60)
        self.assertTrue(snapshot["warnings"])
        self.assertIsNone(snapshot["source_metadata"]["active_tool"])

    def test_disappearing_tool_is_not_invented(self):
        snapshot, _ = self.poll(["extruder1"], {"result": {"status": {}}})
        self.assertNotIn("tool1", snapshot["temperatures"])
        self.assertIsNone(snapshot["source_metadata"]["active_tool"])
