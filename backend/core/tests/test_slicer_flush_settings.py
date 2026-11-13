"""Orca flushing matrix: no invented defaults, no cross-topology leaks."""
import json
from types import SimpleNamespace
from django.test import SimpleTestCase
from core.slicer_flush_settings import validate_flush_settings, apply_orca_flush_settings
from core.slicer_material_routing import MaterialRoutingError


class FlushSettingsTests(SimpleTestCase):
    def setUp(self):
        self.routes = [
            SimpleNamespace(slot_id="bay-blue", tool_index=1),
            SimpleNamespace(slot_id="bay-black", tool_index=0),
        ]
        self.native = json.dumps({
            "flush_multiplier": ["0.65"],
            "flush_volumes_matrix": [0, 215, 330, 0],
            "enable_prime_tower": "1",
            "prime_tower_width": "45",
            "printer_start_gcode": "M117 native printer profile",
        }).encode()
        self.settings = {
            "multiplier": None, "prime_tower": "native",
            "transitions": [
                {"from_slot_id": "bay-blue", "to_slot_id": "bay-black", "volume_mm3": 370},
            ],
        }

    def apply(self, settings=None, native=None, topology="single_nozzle_changer"):
        return json.loads(apply_orca_flush_settings(
            self.native if native is None else native,
            self.settings if settings is None else settings,
            routes=self.routes, tool_count=2, topology=topology))

    def test_directional_mapping_uses_native_tool_indices_not_bay_order(self):
        data = self.apply()
        self.assertEqual(data["flush_volumes_matrix"], ["0", "215", "370", "0"])
        self.assertEqual(data["flush_multiplier"], ["0.65"])
        self.assertEqual(data["enable_prime_tower"], "1")
        self.assertEqual(data["prime_tower_width"], "45")
        self.assertEqual(data["printer_start_gcode"], "M117 native printer profile")

    def test_explicit_multiplier_and_tower_setting(self):
        data = self.apply({**self.settings, "multiplier": 1.2,
                           "prime_tower": "enabled"})
        self.assertEqual(data["flush_multiplier"], ["1.2"])
        self.assertEqual(data["enable_prime_tower"], "1")

    def test_missing_native_matrix_requires_all_directional_volumes(self):
        no_matrix = b'{"enable_prime_tower":"1"}'
        with self.assertRaisesRegex(MaterialRoutingError, "Missing native flush"):
            self.apply(native=no_matrix)
        complete = {**self.settings, "transitions": [
            *self.settings["transitions"],
            {"from_slot_id": "bay-black", "to_slot_id": "bay-blue", "volume_mm3": 220},
        ]}
        data = self.apply(settings=complete, native=no_matrix)
        self.assertEqual(data["flush_volumes_matrix"], ["0", "220", "370", "0"])

    def test_no_cfs_flushing_on_independent_toolheads(self):
        with self.assertRaisesRegex(MaterialRoutingError, "independent toolheads"):
            self.apply(topology="independent_toolheads")

    def test_rejects_invalid_overrides_and_stale_slot_ids(self):
        invalid = (
            {**self.settings, "multiplier": float("nan")},
            {**self.settings, "transitions": [
                {"from_slot_id": "bay-black", "to_slot_id": "bay-blue", "volume_mm3": 20001}]},
            {**self.settings, "transitions": [
                {"from_slot_id": "stale-bay", "to_slot_id": "bay-blue", "volume_mm3": 250}]},
            {**self.settings, "transitions": [self.settings["transitions"][0]] * 2},
        )
        for entry in invalid:
            with self.subTest(entry=entry):
                with self.assertRaises(MaterialRoutingError):
                    self.apply(settings=entry)

    def test_no_settings_leaves_original_profile_bytes_untouched(self):
        self.assertEqual(apply_orca_flush_settings(
            self.native, None, routes=self.routes, tool_count=2,
            topology="single_nozzle_changer"), self.native)
