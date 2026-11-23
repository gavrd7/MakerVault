"""Native modifier region safety and engine-neutral draft contract."""
import uuid

from django.test import SimpleTestCase
from core.slicer_modifier_volumes import (
    MAX_MODIFIERS_PER_MODEL, validate_modifier_volumes,
    refuse_unverified_native_modifiers, validate_native_modifier_execution,
)


def box(**changes):
    value = {
        "id": str(uuid.uuid4()), "shape": "box",
        "width_mm": 20, "depth_mm": 20, "height_mm": 20,
        "x_mm": 0, "y_mm": 0, "z_mm": 10,
        "settings": {"sparse_infill_density": 50},
    }
    value.update(changes)
    return value


class ModifierDraftContractTests(SimpleTestCase):
    def test_all_initial_primitive_types_are_retained_without_printable_models(self):
        for shape in ("box", "cylinder", "sphere", "cone", "disc", "torus"):
            with self.subTest(shape=shape):
                result = validate_modifier_volumes([box(shape=shape)])
                self.assertEqual(result[0]["shape"], shape)
                self.assertEqual(result[0]["settings"], {"sparse_infill_density": 50})


    def test_world_space_modifier_has_bounded_independent_pose(self):
        pose = box(coordinate_space="world",
                   rotation_xyz_deg=[12, -24, 90],
                   scale_xyz_percent=[125, 80, 200])
        result = validate_modifier_volumes([pose])[0]
        self.assertEqual(result["coordinate_space"], "world")
        self.assertEqual(result["rotation_xyz_deg"], [12.0, -24.0, 90.0])
        self.assertEqual(result["scale_xyz_percent"], [125.0, 80.0, 200.0])
        # Existing parent-local fixtures remain unchanged.
        self.assertNotIn("coordinate_space", validate_modifier_volumes([box()])[0])

    def test_rejects_partial_or_out_of_bounds_world_poses(self):
        pose = box(coordinate_space="world",
                   rotation_xyz_deg=[0, 0, 0],
                   scale_xyz_percent=[100, 100, 100])
        for candidate in (
            box(coordinate_space="world"),
            {**pose, "coordinate_space": "local"},
            {**pose, "rotation_xyz_deg": [0, 0]},
            {**pose, "rotation_xyz_deg": [0, False, 0]},
            {**pose, "rotation_xyz_deg": [0, 361, 0]},
            {**pose, "scale_xyz_percent": [100, 0, 100]},
            {**pose, "scale_xyz_percent": [100, float("inf"), 100]},
            {**pose, "scale_xyz_percent": "100%"},
        ):
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                validate_modifier_volumes([candidate])

    def test_rejects_untrusted_shapes_fields_and_ids(self):
        record = box()
        for candidate in (
            box(shape="custom_mesh"),
            box(id="not-a-uuid"),
            box(settings={}),
            box(settings={"start_gcode": "G28"}),
            box(width_mm=0),
            box(z_mm=float("nan")),
            box(height_mm=True),
            {**record, "unexpected": "ignored"},
        ):
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    validate_modifier_volumes([candidate])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            validate_modifier_volumes([record, record])
        with self.assertRaisesRegex(ValueError, "limit"):
            validate_modifier_volumes([box() for _ in range(MAX_MODIFIERS_PER_MODEL + 1)])

    def test_every_engine_rejects_slicing_modifier_drafts_until_native_proof(self):
        plate = [{"instance_id": str(uuid.uuid4()), "modifier_volumes": [box()]}]
        for engine in ("orcaslicer", "crealityprint", "bambustudio"):
            with self.subTest(engine=engine), self.assertRaisesRegex(ValueError, engine):
                refuse_unverified_native_modifiers(plate, engine)
        for engine in ("orcaslicer", "crealityprint", "bambustudio"):
            refuse_unverified_native_modifiers([{"modifier_volumes": []}], engine)


    def test_execution_requires_single_owner_and_pinned_native_version(self):
        plate = [{"modifier_volumes": [box()]}]
        for engine, version in (("orcaslicer", "2.5.0"),
                                ("crealityprint", "7.3.1"),
                                ("bambustudio", "02.09.01.70")):
            with self.subTest(engine=engine):
                self.assertTrue(validate_native_modifier_execution(
                    plate, engine=engine, version=version, settings={}))
                with self.assertRaisesRegex(ValueError, "version"):
                    validate_native_modifier_execution(
                        plate, engine=engine, version=version + ".1", settings={})
        for edited_plate, settings in (
            (plate * 2, {}),
            (plate, {"multi_material_test": True}),
            (plate, {"material_tool_bindings": [{"slot_id": "cfs", "tool_index": 0}]}),
            (plate, {"flush_settings": {"multiplier": 2}}),
            ([{**plate[0], "colour_paint": {"faces": [1]}}], {}),
            ([{**plate[0], "variable_layer_profile": {"bands": [{"height": 0.1}]}}], {}),
        ):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                validate_native_modifier_execution(
                    edited_plate, engine="orcaslicer", version="2.5.0",
                    settings=settings)
        self.assertFalse(validate_native_modifier_execution(
            [{"modifier_volumes": []}], engine="orcaslicer",
            version="2.5.0", settings={}))

    def test_missing_modifier_field_does_not_change_existing_drafts(self):
        self.assertEqual(validate_modifier_volumes(None), [])
        refuse_unverified_native_modifiers([{"process_overrides": {"wall_loops": 3}}], "orcaslicer")
