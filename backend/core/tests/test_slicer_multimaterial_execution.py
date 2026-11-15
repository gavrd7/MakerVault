"""Offline multi-material preflight: no printer commands or network transport."""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from core.slicer_material_routing import MaterialRoutingError
from core.slicer_multimaterial_execution import plan_native_multimaterial


class MultiMaterialPreflightTests(SimpleTestCase):
    def setUp(self):
        self.slots = [
            {"printer_id": "printer", "slot_id": "cfs-bay-4", "slot_index": 3},
            {"printer_id": "printer", "slot_id": "cfs-bay-1", "slot_index": 0},
        ]
        self.settings = {
            "multi_material_test": True,
            "plate_objects": [
                {"instance_id": "a", "material_slot": self.slots[0]},
                {"instance_id": "b", "material_slot": self.slots[1]},
            ],
            "slot_filament_profiles": [
                {"slot_id": "cfs-bay-4", "profile_id": "blue"},
                {"slot_id": "cfs-bay-1", "profile_id": "red"},
            ],
        }
        self.job = SimpleNamespace(
            engine="orcaslicer", engine_version="2.5.0",
            printer_id="printer", owner_id="owner",
            filament_profile_id="red", settings=self.settings,
        )
        self.presets = [
            SimpleNamespace(pk="red", status="verified", engine="orcaslicer",
                            engine_version="2.5.0", kind="filament"),
            SimpleNamespace(pk="blue", status="verified", engine="orcaslicer",
                            engine_version="2.5.0", kind="filament"),
        ]
        self.connection = SimpleNamespace(
            enabled=True, status="connected", adapter="creality_local",
            capabilities={"material_system": {"available": True,
                "topology": "single_nozzle_changer",
                "physical_toolchange_verified": False}},
        )

    @patch("core.slicer_multimaterial_execution.SlicerProfile.objects.filter")
    @patch("core.slicer_multimaterial_execution.PrinterConnection.objects.filter")
    def test_material_mapping_is_derived_from_main_filament_not_cfs_slot_order(self, sources, profiles):
        sources.return_value = [self.connection]
        profiles.return_value = self.presets
        topology, bindings, palette = plan_native_multimaterial(self.job)
        self.assertEqual(topology, "single_nozzle_changer")
        self.assertEqual(bindings, {"cfs-bay-1": 0, "cfs-bay-4": 1})
        self.assertEqual([p.pk for p in palette], ["red", "blue"])

    @patch("core.slicer_multimaterial_execution.PrinterConnection.objects.filter")
    def test_missing_live_capability_blocks_multicolour(self, sources):
        sources.return_value = []
        with self.assertRaisesRegex(MaterialRoutingError, "could not be confirmed"):
            plan_native_multimaterial(self.job)

    @patch("core.slicer_multimaterial_execution.SlicerProfile.objects.filter")
    @patch("core.slicer_multimaterial_execution.PrinterConnection.objects.filter")
    def test_unverified_filament_preset_fails_closed(self, sources, profiles):
        sources.return_value = [self.connection]
        self.presets[1].status = "draft"
        profiles.return_value = self.presets
        with self.assertRaisesRegex(MaterialRoutingError, "not verified"):
            plan_native_multimaterial(self.job)
