"""Provider-neutral physical slot vs native toolhead routing contracts."""
import io
import zipfile
from defusedxml import ElementTree as ET
from django.test import SimpleTestCase
from types import SimpleNamespace

from core.slicer_approval import fixture_stl
from core.slicer_material_routing import (
    MaterialRoutingError, plan_material_routes, single_material_slice_assignment,
    detect_material_system, derive_native_tool_order,
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
        # An imported preset for a loaded but unused slot is metadata, not a
        # printer tool selection and must not block an otherwise normal slice.
        self.assertIsNone(single_material_slice_assignment(
            [{"instance_id": "a"}], **self.options,
            slot_filament_profiles=[{"slot_id": "cfs-bay-4", "profile_id": "native-pla"}]))

    def test_multiple_loaded_slot_presets_do_not_force_multimaterial(self):
        result = single_material_slice_assignment(
            self.models, **self.options, slot_filament_profiles=[
                {"slot_id": "cfs-bay-1", "profile_id": "unused-abs"},
                {"slot_id": "cfs-bay-4", "profile_id": "native-pla"},
                {"slot_id": "cfs-bay-3", "profile_id": "unused-petg"},
            ])
        self.assertEqual(result["logical_tool"], 0)
        self.assertEqual(result["slot_id"], "cfs-bay-4")

    def test_one_assigned_material_is_independent_of_feeder_bay_index(self):
        for topology in ("single_nozzle_changer", "independent_toolheads",
                         "toolchanger", "idex", "manual_filament_change"):
            with self.subTest(topology=topology):
                # Single-filament slicing always uses the sole native palette
                # entry (logical tool zero), never a physical bay/toolhead ID.
                for physical_slot_index in (0, 1, 3, 15):
                    objects = [
                        {"instance_id": item["instance_id"],
                         "material_slot": {**self.slot, "slot_index": physical_slot_index}}
                        for item in self.models
                    ]
                    result = single_material_slice_assignment(
                        objects, **self.options,
                        slot_filament_profiles=[
                            {"slot_id": "unassigned-bay", "profile_id": "other"},
                            {"slot_id": "cfs-bay-4", "profile_id": "native-pla"},
                        ])
                    self.assertEqual(result["logical_tool"], 0)
                    self.assertEqual(result["slot_index"], physical_slot_index)

    def test_explicit_profile_must_match_selected_engine_resolved_preset(self):
        for material in ("PLA", "ABS", "PETG", "TPU", "PA", "ASA"):
            with self.subTest(material=material):
                main = "main-" + material
                slot = "slot-" + material
                with self.assertRaisesRegex(MaterialRoutingError, "must match"):
                    single_material_slice_assignment(
                        self.models, printer_id="printer-1",
                        selected_filament_profile_id=main,
                        slot_filament_profiles=[
                            {"slot_id": "cfs-bay-4", "profile_id": slot},
                        ])
                self.assertEqual(
                    single_material_slice_assignment(
                        self.models, printer_id="printer-1",
                        selected_filament_profile_id=slot,
                        slot_filament_profiles=[
                            {"slot_id": "cfs-bay-4", "profile_id": slot},
                        ])["logical_tool"], 0)

    def test_duplicate_loaded_slot_presets_still_fail_closed(self):
        with self.assertRaisesRegex(MaterialRoutingError, "duplicate"):
            single_material_slice_assignment(
                self.models, **self.options, slot_filament_profiles=[
                    {"slot_id": "cfs-bay-4", "profile_id": "native-pla"},
                    {"slot_id": "cfs-bay-4", "profile_id": "other"},
                ])

    def test_assigned_slot_without_native_profile_cannot_fall_back_to_main(self):
        with self.assertRaisesRegex(MaterialRoutingError, "no native filament profile"):
            single_material_slice_assignment(self.models, **self.options)
        with self.assertRaisesRegex(MaterialRoutingError, "no native filament profile"):
            single_material_slice_assignment(
                self.models, **self.options,
                slot_filament_profiles=[{"slot_id": "cfs-bay-1", "profile_id": "unused-abs"}])

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



class PersistedToolRouteTests(SimpleTestCase):
    def test_draft_serialization_retains_explicit_native_tool_bindings(self):
        from core.slicer_api import _draft_plate_settings
        settings = _draft_plate_settings(None, None, {
            "material_tool_bindings": [
                {"slot_id": "bay-4", "tool_index": 1},
                {"slot_id": "bay-1", "tool_index": 0},
            ],
            "material_topology": "single_nozzle_changer",
        })
        self.assertEqual(settings["material_tool_bindings"], [
            {"slot_id": "bay-4", "tool_index": 1},
            {"slot_id": "bay-1", "tool_index": 0},
        ])
        self.assertEqual(settings["material_topology"], "single_nozzle_changer")

    def test_draft_rejects_duplicate_and_bool_native_tool_indices(self):
        from core.slicer_api import _draft_plate_settings
        bad = [
            [{"slot_id": "bay-4", "tool_index": 0},
             {"slot_id": "bay-1", "tool_index": 0}],
            [{"slot_id": "bay-4", "tool_index": True}],
            [{"slot_id": "bay-4", "tool_index": -1}],
        ]
        for bindings in bad:
            with self.subTest(bindings=bindings):
                with self.assertRaises(ValueError):
                    _draft_plate_settings(None, None, {
                        "material_tool_bindings": bindings,
                    })


    def test_model_assignment_and_tool_bindings_survive_full_draft_validation(self):
        import uuid
        from types import SimpleNamespace
        from unittest.mock import patch
        from core.slicer_api import _draft_plate_settings

        asset_id = uuid.uuid4()
        printer_id = uuid.uuid4()
        asset = SimpleNamespace(
            pk=asset_id, name="benchy.stl", metadata={"extension": ".stl"},
        )
        model = {
            "instance_id": str(uuid.uuid4()),
            "asset_id": str(asset_id),
            "x_mm": 0, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100,
            "color": "#aabbcc",
            "material_slot": {
                "printer_id": str(printer_id),
                "slot_id": "manual-slot-1", "slot_index": 0,
            },
        }
        with patch("core.slicer_api.FileAsset.objects.filter") as lookup:
            lookup.return_value.first.return_value = asset
            result = _draft_plate_settings(None, asset, {
                "plate_objects": [model],
                "material_tool_bindings": [
                    {"slot_id": "manual-slot-1", "tool_index": 0},
                ],
                "material_topology": "manual_filament_change",
            })
        self.assertEqual(result["plate_objects"][0]["material_slot"],
                         model["material_slot"])
        self.assertEqual(result["material_tool_bindings"],
                         [{"slot_id": "manual-slot-1", "tool_index": 0}])
        self.assertEqual(result["material_topology"], "manual_filament_change")


class AutomaticAdapterMaterialRoutingTests(SimpleTestCase):
    def connection(self, adapter, topology, *, available=True, status="connected"):
        return SimpleNamespace(
            adapter=adapter, enabled=True, status=status,
            capabilities={"material_system": {
                "available": available, "topology": topology,
                "physical_toolchange_verified": False,
            }},
        )

    def test_adapter_declares_architecture_without_authorising_printing(self):
        for adapter, topology in [
            ("creality_local", "single_nozzle_changer"),
            ("bambu_local", "single_nozzle_changer"),
            ("prusa", "toolchanger"),
            ("moonraker", "idex"),
            ("snapmaker", "toolchanger"),
            ("octoprint", "manual_filament_change"),
        ]:
            with self.subTest(adapter=adapter):
                self.assertEqual(
                    detect_material_system([self.connection(adapter, topology)]),
                    topology,
                )

    def test_unknown_unsupported_or_conflicting_system_requires_verification(self):
        cases = [
            [],
            [self.connection("creality_local", "toolchanger")],
            [self.connection("bambu_local", "single_nozzle_changer", available=False)],
            [self.connection("creality_local", "single_nozzle_changer", status="disconnected")],
            [self.connection("moonraker", "idex"), self.connection("octoprint", "toolchanger")],
        ]
        for connections in cases:
            with self.subTest(connections=connections):
                with self.assertRaisesRegex(MaterialRoutingError, "could not be confirmed"):
                    detect_material_system(connections)

    def test_tool_assignment_uses_filament_selection_not_physical_bay_number(self):
        models = [
            {"instance_id": "a", "material_slot": {
                "printer_id": "printer", "slot_id": "cfs-4", "slot_index": 3}},
            {"instance_id": "b", "material_slot": {
                "printer_id": "printer", "slot_id": "cfs-1", "slot_index": 0}},
            {"instance_id": "c", "material_slot": {
                "printer_id": "printer", "slot_id": "cfs-4", "slot_index": 3}},
        ]
        self.assertEqual(
            derive_native_tool_order(
                models, printer_id="printer", topology="single_nozzle_changer",
            ), {"cfs-4": 0, "cfs-1": 1},
        )
