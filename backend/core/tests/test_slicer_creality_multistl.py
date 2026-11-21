"""Offline Creality 7.3.1 two-STL preparation safety checks."""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from core.slicer_multimaterial_execution import (
    MaterialRoutingError, prepare_creality_multistl,
)


class CrealityMultiStlPreparationTests(SimpleTestCase):
    def _job(self):
        objects = [
            {"instance_id": "first", "material_slot": {"slot_id": "slot-a"}},
            {"instance_id": "second", "material_slot": {"slot_id": "slot-b"}},
        ]
        return SimpleNamespace(
            engine="crealityprint",
            settings={"plate_objects": objects, "creality_auto_arrange_offline": True},
        )

    @patch("core.slicer_native_resolution.resolved_native_profile",
           side_effect=[b'{"name":"A"}', b'{"name":"B"}'])
    @patch("core.slicer_multimaterial_execution.plan_native_multimaterial",
           return_value=("single_nozzle_changer", {"slot-a": 0, "slot-b": 1},
                         [object(), object()]))
    def test_two_cfs_slots_resolve_to_logical_creality_ids(self, planner, resolve):
        job = self._job()
        source = [(job.settings["plate_objects"][0], b"first-stl"),
                  (job.settings["plate_objects"][1], b"second-stl")]
        prepared = prepare_creality_multistl(job, source)
        self.assertEqual(prepared["tool_ids"], (1, 2))
        self.assertEqual(prepared["model_stls"], (b"first-stl", b"second-stl"))
        self.assertEqual(prepared["expected_tools"], {0, 1})
        self.assertEqual(prepared["filament_profiles"], (b'{"name":"A"}', b'{"name":"B"}'))

    def test_auto_arrangement_requires_explicit_acknowledgement(self):
        job = self._job()
        source = [(obj, b"stl") for obj in job.settings["plate_objects"]]
        del job.settings["creality_auto_arrange_offline"]
        with self.assertRaisesRegex(MaterialRoutingError, "explicit offline"):
            prepare_creality_multistl(job, source)

    def test_transforms_and_paint_are_not_silently_lost(self):
        job = self._job()
        source = [(obj, b"stl") for obj in job.settings["plate_objects"]]
        job.settings["plate_objects"][0]["rotation_deg"] = 45
        with self.assertRaisesRegex(MaterialRoutingError, "transformed models"):
            prepare_creality_multistl(job, source)
        job.settings["plate_objects"][0]["rotation_deg"] = 0
        job.settings["plate_objects"][0]["colour_paint"] = {"regions": [{"slot": 1}]}
        with self.assertRaisesRegex(MaterialRoutingError, "painted"):
            prepare_creality_multistl(job, source)
