"""Native modifier region safety and engine-neutral draft contract."""
import uuid

from django.test import SimpleTestCase
from core.slicer_modifier_volumes import (
    MAX_MODIFIERS_PER_MODEL, validate_modifier_volumes,
    refuse_unverified_native_modifiers,
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

    def test_missing_modifier_field_does_not_change_existing_drafts(self):
        self.assertEqual(validate_modifier_volumes(None), [])
        refuse_unverified_native_modifiers([{"process_overrides": {"wall_loops": 3}}], "orcaslicer")
