from django.test import SimpleTestCase
from core.slicer_approval import fixture_stl
from core.slicer_plate_validation import validate_plate_collisions, PlateCollisionError


class PlateCollisionTests(SimpleTestCase):
    def test_two_separated_solids_can_slice(self):
        mesh = fixture_stl()
        base = {"x_mm": -30, "y_mm": 0, "z_mm": 0,
                "rotation_deg": 0, "scale_percent": 100}
        second = {**base, "x_mm": 30}
        self.assertTrue(validate_plate_collisions([(base, mesh), (second, mesh)]))

    def test_overlapping_footprints_at_same_height_are_rejected(self):
        mesh = fixture_stl()
        base = {"x_mm": 0, "y_mm": 0, "z_mm": 0,
                "rotation_deg": 0, "scale_percent": 100}
        with self.assertRaises(PlateCollisionError):
            validate_plate_collisions([(base, mesh), ({**base, "x_mm": 0.1}, mesh)])

    def test_rotated_disjoint_envelopes_with_overlapping_aabbs_can_slice(self):
        # Two 40 x 4 mm source envelopes rotated 45 degrees. Their world-
        # axis bounding boxes overlap, but their oriented footprints do not.
        source = (fixture_stl()
                  .replace(b"10 0 0", b"40 0 0")
                  .replace(b"0 10 0", b"0 4 0"))
        left = {"x_mm": -12.5, "y_mm": 0, "z_mm": 0,
                "rotation_deg": 45, "scale_percent": 100}
        right = {**left, "x_mm": 12.5}
        self.assertTrue(validate_plate_collisions(
            [(left, source), (right, source)]))

    def test_rotated_models_with_actual_overlapping_footprints_still_fail(self):
        source = (fixture_stl()
                  .replace(b"10 0 0", b"40 0 0")
                  .replace(b"0 10 0", b"0 4 0"))
        model = {"x_mm": 0, "y_mm": 0, "z_mm": 0,
                 "rotation_deg": 45, "scale_percent": 100}
        with self.assertRaises(PlateCollisionError):
            validate_plate_collisions(
                [(model, source), ({**model, "x_mm": 1}, source)])

    def test_surface_contact_is_not_a_collision(self):
        mesh = fixture_stl()
        base = {"x_mm": 0, "y_mm": 0, "z_mm": 0,
                "rotation_deg": 0, "scale_percent": 100}
        from core.slicer_mesh import inspect_stl
        top = {**base, "z_mm": inspect_stl(mesh)["size_mm"][2]}
        self.assertTrue(validate_plate_collisions([(base, mesh), (top, mesh)]))
