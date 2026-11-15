"""Provider-neutral physical slot vs native toolhead routing contracts."""
import io
import zipfile
from defusedxml import ElementTree as ET
from django.test import SimpleTestCase

from core.slicer_approval import fixture_stl
from core.slicer_material_routing import (
    MaterialRoutingError, plan_material_routes, single_material_slice_assignment,
)
from core.slicer_plate_3mf import build_plate_3mf, NS
from core.slicer_profiles import SlicerProfileError


class MaterialRoutingTests(SimpleTestCase):
    def setUp(self):
        self.rows = [
            {"instance_id": "a", "material_slot": {
                "printer_id": "printer-1", "slot_id": "bay-2", "slot_index": 1}},
            {"instance_id": "b", "material_slot": {
                "printer_id": "printer-1", "slot_id": "bay-1", "slot_index": 0}},
        ]

    def test_changer_uses_explicit_palette_indices_not_physical_order(self):
        planned = plan_material_routes(
            self.rows, printer_id="printer-1",
            topology="single_nozzle_changer",
            tool_bindings={"bay-2": 0, "bay-1": 2},
        )
        self.assertEqual([row.tool_index for row in planned], [0, 2])
        self.assertEqual([row.slot_index for row in planned], [1, 0])

    def test_independent_heads_cannot_reuse_one_tool_for_two_physical_slots(self):
        with self.assertRaisesRegex(MaterialRoutingError, "one independent printhead"):
            plan_material_routes(
                self.rows, printer_id="printer-1",
                topology="independent_toolheads",
                tool_bindings={"bay-2": 0, "bay-1": 0},
            )
        planned = plan_material_routes(
            self.rows, printer_id="printer-1",
            topology="independent_toolheads",
            tool_bindings={"bay-2": 3, "bay-1": 1},
        )
        self.assertEqual([row.tool_index for row in planned], [3, 1])

    def test_missing_or_foreign_mapping_fails_closed(self):
        for bindings, rows in (
            ({}, self.rows),
            ({"bay-2": 0, "bay-1": True}, self.rows),
            ({"bay-2": 0, "bay-1": -1}, self.rows),
            ({"bay-2": 0, "bay-1": 1},
             [{**self.rows[0], "material_slot": {
                 **self.rows[0]["material_slot"], "printer_id": "other"}}]),
            ({"bay-2": 0, "bay-1": 1},
             [{**self.rows[0], "material_slot": None}]),
        ):
            with self.subTest(bindings=bindings, rows=rows):
                with self.assertRaises(MaterialRoutingError):
                    plan_material_routes(rows, printer_id="printer-1",
                                         topology="single_nozzle_changer",
                                         tool_bindings=bindings)

    def test_native_3mf_writes_one_based_extruders_without_merging_objects(self):
        model = fixture_stl()
        items = [
            ({"x_mm": -30, "y_mm": 0, "rotation_deg": 0,
              "scale_percent": 100}, model),
            ({"x_mm": 30, "y_mm": 0, "rotation_deg": 0,
              "scale_percent": 100}, model),
        ]
        data = build_plate_3mf(
            items, bed_width=220, bed_depth=220, native_tool_indices=[0, 3])
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            root = ET.fromstring(archive.read("3D/3dmodel.model"))
            config = ET.fromstring(archive.read("Metadata/model_settings.config"))
        self.assertEqual(len(root.findall(".//{%s}object" % NS)), 2)
        ids = [node.attrib["id"] for node in config.findall("object")]
        self.assertEqual(ids, ["1", "2"])
        values = [
            next(meta.attrib["value"] for meta in node.findall("metadata")
                 if meta.attrib["key"] == "extruder")
            for node in config.findall("object")
        ]
        self.assertEqual(values, ["1", "4"])

    def test_native_3mf_requires_valid_index_for_every_object(self):
        items = [({"x_mm": 0, "y_mm": 0, "rotation_deg": 0,
                   "scale_percent": 100}, fixture_stl())]
        for invalid in ([], [True], [-1], [64], ["1"]):
            with self.subTest(invalid=invalid):
                with self.assertRaises(SlicerProfileError):
                    build_plate_3mf(items, bed_width=220, bed_depth=220,
                                    native_tool_indices=invalid)


class SingleMaterialSliceAnnotationTests(SimpleTestCase):
    def setUp(self):
        self.slot = {"printer_id": "printer-1", "slot_id": "cfs-bay-4", "slot_index": 3}
        self.models = [
            {"instance_id": "a", "material_slot": dict(self.slot)},
            {"instance_id": "b", "material_slot": dict(self.slot)},
        ]
        self.options = {
            "printer_id": "printer-1",
            "selected_filament_profile_id": "native-pla",
        }

    def test_same_slot_slices_as_logical_tool_zero_not_bay_index(self):
        result = single_material_slice_assignment(
            self.models, **self.options,
            slot_filament_profiles=[{"slot_id": "cfs-bay-4", "profile_id": "native-pla"}],
        )
        self.assertEqual(result, {
            "slot_id": "cfs-bay-4", "slot_index": 3, "logical_tool": 0,
        })

    def test_no_assignment_preserves_single_filament_flow(self):
        self.assertIsNone(single_material_slice_assignment(
            [{"instance_id": "a"}], **self.options))
        with self.assertRaisesRegex(MaterialRoutingError, "unused"):
            single_material_slice_assignment(
                [{"instance_id": "a"}], **self.options,
                slot_filament_profiles=[{"slot_id": "cfs-bay-4", "profile_id": "native-pla"}])

    def test_mismatched_or_missing_assignments_fail_closed(self):
        cases = [
            [{**self.models[0]}, {"instance_id": "b"}],
            [self.models[0], {"instance_id": "b", "material_slot": {
                "printer_id": "printer-1", "slot_id": "cfs-bay-1", "slot_index": 0}}],
            [{"instance_id": "a", "material_slot": {
                **self.slot, "printer_id": "someone-else"}}],
            [{"instance_id": "a", "material_slot": {
                **self.slot, "slot_index": True}}],
        ]
        for models in cases:
            with self.subTest(models=models):
                with self.assertRaises(MaterialRoutingError):
                    single_material_slice_assignment(models, **self.options)
        with self.assertRaisesRegex(MaterialRoutingError, "must match"):
            single_material_slice_assignment(
                self.models, **self.options,
                slot_filament_profiles=[{"slot_id": "cfs-bay-4", "profile_id": "wrong"}])

