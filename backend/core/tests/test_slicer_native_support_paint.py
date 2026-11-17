"""Native support-paint conversion must preserve clipped areas, not colour whole STL facets."""
from django.test import SimpleTestCase

from core.slicer_native_support_paint import native_support_triangles, _fingerprint, _area


class NativeOrcaSupportPaintTests(SimpleTestCase):
    def setUp(self):
        self.source = [
            [(0., 0., 0.), (4., 0., 0.), (0., 4., 0.)],
            [(0., 0., 1.), (4., 0., 1.), (0., 4., 1.)],
        ]

    def paint(self, slot=0, patches=None):
        # Browser STLLoader recentres XY (-2,-2) before painting.
        local = [
            [tuple(p[axis] - ([2., 2., 0.][axis]) for axis in range(3))
             for p in tri]
            for tri in self.source
        ]
        return {"version": 2, "signature": _fingerprint(local),
                "regions": [{"slot": slot, "patches": patches or [{
                    "face": 0,
                    "polygon": [[-2., -2., 0.], [0., -2., 0.], [-2., 0., 0.]],
                }]}]}

    def test_small_enforcer_patch_splits_only_its_source_triangle(self):
        result = native_support_triangles(self.source, self.paint())
        self.assertGreater(len(result), 2)
        self.assertEqual(result[-1][0], tuple(self.source[1]))
        self.assertIsNone(result[-1][1])
        self.assertIn("4", [value for _, value in result])
        self.assertTrue(any(value is None for _, value in result[:-1]))
        original_area = _area(self.source[0], (0., 0., 1.))
        subdivided_area = sum(_area(tri, (0., 0., 1.)) for tri, _ in result[:-1])
        painted_area = sum(_area(tri, (0., 0., 1.)) for tri, attr in result if attr=="4")
        self.assertAlmostEqual(subdivided_area, original_area, places=5)
        self.assertAlmostEqual(painted_area, 2., places=5)

    def test_blocker_preserves_its_distinct_native_state(self):
        result = native_support_triangles(self.source, self.paint(slot=1))
        self.assertIn("8", [value for _, value in result])
        self.assertNotIn("4", [value for _, value in result])

    def test_native_seam_facets_preserve_clipped_enforcer_and_blocker(self):
        for slot, state in ((0, "4"), (1, "8")):
            with self.subTest(slot=slot):
                result = native_support_triangles(
                    self.source, self.paint(slot=slot), kind="seam")
                self.assertIn(state, [value for _, value in result])
                self.assertEqual(result[-1][0], tuple(self.source[1]))
                self.assertIsNone(result[-1][1])
                area = sum(_area(tri, (0., 0., 1.))
                           for tri, value in result if value == state)
                self.assertAlmostEqual(area, 2., places=5)

    def test_stale_seam_mask_cannot_export(self):
        paint = self.paint()
        paint["signature"] = "changed"
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            native_support_triangles(self.source, paint, kind="seam")

    def test_selective_fuzzy_skin_uses_only_orca_painted_state(self):
        painted = native_support_triangles(self.source, self.paint(), kind="fuzzy")
        self.assertGreater(len(painted), len(self.source))
        self.assertIn("4", [state for _, state in painted])
        self.assertNotIn("8", [state for _, state in painted])
        self.assertEqual(painted[-1][0], tuple(self.source[1]))
        self.assertIsNone(painted[-1][1])
        painted_area = sum(_area(tri, (0., 0., 1.))
                           for tri, state in painted if state == "4")
        self.assertAlmostEqual(painted_area, 2., places=5)
        with self.assertRaisesRegex(ValueError, "only the painted state"):
            native_support_triangles(self.source, self.paint(slot=1), kind="fuzzy")

    def test_selective_fuzzy_skin_rejects_stale_source_mesh(self):
        stale = self.paint()
        stale["signature"] = "outdated"
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            native_support_triangles(self.source, stale, kind="fuzzy")

    def test_stale_or_off_face_patches_fail_closed(self):
        paint = self.paint()
        paint["signature"] = "2:abcdef01"
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            native_support_triangles(self.source, paint)
        paint = self.paint()
        paint["regions"][0]["patches"][0]["polygon"][0][2] = 2
        with self.assertRaisesRegex(ValueError, "coplanar"):
            native_support_triangles(self.source, paint)
        paint = self.paint()
        paint["regions"][0]["patches"][0]["polygon"][0][0] = 8
        with self.assertRaisesRegex(ValueError, "outside"):
            native_support_triangles(self.source, paint)
