"""Full-resolution selected-layer inspection and ownership regression tests."""
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase

from core.models import FileAsset
from core.slicer_layer_preview import exact_layer_toolpaths


GCODE = (
    ";TYPE:Outer wall\n"
    "G90\nM82\nG1 X0 Y0 Z0.2 E0\n"
    "G1 X10 Y0 E0.2\n"
    "G1 X10 Y10 E0.4\n"
    ";TYPE:Support material\n"
    "G1 X8 Y10 E0.6\n"
    "G1 Z0.4\n"
    "G1 X8 Y8 E0.8\n"
    "G1 X3 Y3 E0.7\n"
)


class FullLayerParserTests(SimpleTestCase):
    def test_returns_all_consecutive_moves_only_on_selected_layer(self):
        result = exact_layer_toolpaths(GCODE, 0.2)
        self.assertEqual(result["segment_count"], 3)
        self.assertEqual(len(result["segments"]), 3)
        self.assertEqual(result["segments"][0][:5], [0.0, 0.0, 10.0, 0.0, 0.2])
        self.assertEqual(result["segments"][2][5], "Support material")
        self.assertTrue(result["complete"])
        self.assertFalse(result["sampled"])
        self.assertEqual(exact_layer_toolpaths(GCODE, 0.4)["segment_count"], 1)

    def test_relative_extrusion_and_g92_are_supported(self):
        text = (
            "G90\nM83\nG1 Z0.25 X0 Y0\n"
            "G1 X5 Y0 E0.1\nG1 X5 Y5 E0.1\n"
            "G92 E0\nG1 X0 Y5 E0.1\n"
        )
        self.assertEqual(exact_layer_toolpaths(text, 0.25)["segment_count"], 3)

    def test_exact_layer_restores_smokestack_arc_extrusions(self):
        import math
        gcode=("G90\\nM83\\nG1 X10 Y0 Z20\\n"
               ";TYPE:Outer wall\\nG3 X0 Y10 I-10 J0 E0.5\\n"
               "G3 X-10 Y0 I0 J-10 E0.5\\n")
        result=exact_layer_toolpaths(gcode,20)
        self.assertGreater(result["segment_count"], 40)
        self.assertTrue(result["complete"])
        self.assertEqual(result["segments"][-1][2:4],[-10.0,0.0])
        self.assertTrue(all(abs(math.hypot(a[2],a[3])-10)<0.01
                            for a in result["segments"]))

    def test_preview_preserves_unextruded_travel_arc_without_fake_strand(self):
        gcode=("G90\\nM83\\nG1 X10 Y0 Z0.2\\n"
               "G3 X0 Y10 I-10 J0\\n"
               "G1 X0 Y20 E0.5\\n")
        result=exact_layer_toolpaths(gcode,0.2)
        self.assertEqual(result["segment_count"],1)
        self.assertEqual(result["segments"][0][:4],[0.0,10.0,0.0,20.0])

    def test_exact_layer_preserves_native_filament_tool_sequence(self):
        text = ("G90\nM83\nG1 X0 Y0 Z0.2\n"
                "T0\nG1 X10 Y0 E1\n"
                "T1\nG1 X10 Y10 E1\n")
        result = exact_layer_toolpaths(text, 0.2)
        self.assertEqual(result["segment_count"], 2)
        self.assertEqual([row[7] for row in result["segments"]], [0, 1])

    def test_unsafe_nonfinite_z_is_rejected(self):
        for value in ("nan", "inf", -1, 2001):
            with self.subTest(value=value), self.assertRaises(ValueError):
                exact_layer_toolpaths(GCODE, value)


class FullLayerEndpointTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="layer-owner", password="test")
        self.other = get_user_model().objects.create_user(username="layer-other", password="test")
        asset = FileAsset(
            owner=self.owner, category="other", name="internal.gcode",
            metadata={"extension": ".gcode", "generated_by": "makervault-slicer"},
        )
        asset.file = ContentFile(GCODE.encode(), name="test-layer.gcode")
        asset.save()
        self.asset = asset
        self.addCleanup(lambda: asset.file.delete(save=False))
        self.url = f"/api/files/{asset.pk}/gcode/layer/?z=0.2"

    def test_private_unsaved_output_remains_inspectable_by_owner(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["segment_count"], 3)
        self.assertEqual(response.json()["feature_counts"]["Support material"], 1)

    def test_other_user_cannot_inspect_unpublished_output(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_invalid_layer_and_binary_are_rejected(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url.replace("0.2", "nan")).status_code, 400)
