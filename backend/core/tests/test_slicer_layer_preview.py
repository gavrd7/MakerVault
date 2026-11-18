"""Full-resolution selected-layer inspection and ownership regression tests."""
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase

from core.models import FileAsset
from core.slicer_layer_preview import exact_layer_toolpaths, layer_batch_toolpaths


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

    def test_batched_layers_are_exact_and_ordered(self):
        result = layer_batch_toolpaths(GCODE, [0.2, 0.4])
        self.assertTrue(result["complete"])
        self.assertEqual([layer["z"] for layer in result["layers"]], [0.2, 0.4])
        self.assertEqual([layer["segment_count"] for layer in result["layers"]], [3, 1])
        self.assertEqual(result["layers"][0]["segments"],
                         exact_layer_toolpaths(GCODE, 0.2)["segments"])
        self.assertEqual(result["layers"][1]["segments"],
                         exact_layer_toolpaths(GCODE, 0.4)["segments"])

    def test_batch_rejects_duplicates_nonfinite_and_excess_layers(self):
        for zs in ([0.2, 0.2], [float("nan")], [-1], [2001],
                   [i / 10 for i in range(65)], []):
            with self.subTest(zs=zs), self.assertRaises(ValueError):
                layer_batch_toolpaths(GCODE, zs)

    def test_batch_limit_never_claims_missing_paths_are_complete(self):
        from unittest.mock import patch
        with patch("core.slicer_layer_preview.MAX_BATCH_SEGMENTS", 2):
            result = layer_batch_toolpaths(GCODE, [0.2, 0.4])
        self.assertFalse(result["complete"])
        self.assertEqual(len(result["layers"][0]["segments"]), 2)
        self.assertEqual(result["layers"][0]["segment_count"], 3)
        self.assertTrue(result["layers"][0]["limited"])
        self.assertTrue(result["layers"][1]["limited"])

    def test_overview_keeps_full_height_without_claiming_full_resolution(self):
        gcode = ("G90\nM83\n" +
                 "".join(f";TYPE:Outer wall\nG1 Z{z:.1f} X0 Y0\n"
                         + "".join(f"G1 X{i+1} Y0 E0.1\n" for i in range(20))
                         for z in (0.2, 0.4, 0.6)))
        result = layer_batch_toolpaths(gcode, [0.2, 0.4, 0.6],
                                       overview=True, overview_limit=80)
        self.assertTrue(result["complete"])
        self.assertEqual([row["z"] for row in result["layers"]], [0.2, 0.4, 0.6])
        self.assertTrue(result["overview"])
        self.assertEqual(len(result["layers"]), 3)
        self.assertEqual(len(result["layers"][2]["segments"]), 20)
        with self.assertRaises(ValueError):
            layer_batch_toolpaths(GCODE, [0.2], overview=True, overview_limit=1000)

    def test_overview_prioritises_shell_supports_and_has_honest_reduction(self):
        from core.slicer_layer_preview import _overview_segments
        segments = []
        for index in range(200):
            kind = "Sparse infill" if index < 100 else "Outer wall"
            segments.append([index, 0, index + 1, 0, 0.2, kind, 0.4, 0])
        result = _overview_segments(segments, per_layer_limit=80)
        self.assertEqual(len(result), 80)
        self.assertTrue(all(row[5] == "Outer wall" for row in result))

    def test_streaming_overview_bounds_storage_without_losing_support_priority(self):
        lines = ["G90", "M83", "G1 X0 Y0 Z0.2"]
        for index in range(300):
            kind = "Sparse infill" if index < 150 else "Support material"
            lines.extend((f";TYPE:{kind}", f"G1 X{index + 1} Y0 E0.1"))
        result = layer_batch_toolpaths("\n".join(lines), [0.2],
                                       overview=True, overview_limit=80)
        layer = result["layers"][0]
        self.assertTrue(result["complete"])
        self.assertTrue(layer["sampled"])
        self.assertEqual(layer["segment_count"], 300)
        self.assertEqual(len(layer["segments"]), 80)
        self.assertTrue(all(move[5] == "Support material"
                            for move in layer["segments"]))
        self.assertEqual(layer["segments"],
                         sorted(layer["segments"], key=lambda move: move[0]))

    def test_cached_index_retrieves_later_page_of_long_print(self):
        from unittest.mock import patch
        from django.core.cache.backends.locmem import LocMemCache
        from core.slicer_preview_cache import cached_batch, index_overview
        heights = [round((i + 1) * .2, 3) for i in range(70)]
        lines = ["G90", "M83"]
        for height in heights:
            lines.extend((f"G1 X0 Y0 Z{height}", ";TYPE:Outer wall",
                          "G1 X1 Y0 E0.1"))
        backend = LocMemCache("preview-index-multiple-pages", {})
        with patch("core.slicer_preview_cache.cache", backend):
            first = index_overview("cache-test-70-layers", "\n".join(lines), heights, 80)
            self.assertIsNotNone(first)
            self.assertEqual(len(first["layers"]), 64)
            second = cached_batch("cache-test-70-layers", heights[64:])
            self.assertIsNotNone(second)
            self.assertEqual(len(second["layers"]), 6)
            self.assertEqual(second["layers"][-1]["z"], heights[-1])

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

    def test_batch_endpoint_preserves_original_and_owner_scope(self):
        self.client.force_login(self.owner)
        response = self.client.get(
            f"/api/files/{self.asset.pk}/gcode/layers/?zs=0.2,0.4")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["complete"])
        self.assertEqual([row["segment_count"] for row in response.json()["layers"]], [3, 1])
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(self.client.get(
            f"/api/files/{self.asset.pk}/gcode/layers/?zs=0.2,0.2").status_code, 400)
        self.assertEqual(self.client.get(
            f"/api/files/{self.asset.pk}/gcode/layers/?zs=nan").status_code, 400)

    def test_surface_overview_endpoint_does_not_change_exact_layer_api(self):
        self.client.force_login(self.owner)
        overview_url=f"/api/files/{self.asset.pk}/gcode/layers/?zs=0.2,0.4&overview=1&detail=80"
        response=self.client.get(overview_url)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["overview"])
        self.assertEqual(len(response.json()["layers"]), 2)
        self.assertEqual(self.client.get(overview_url.replace("detail=80", "detail=900")).status_code, 400)
        exact=self.client.get(self.url)
        self.assertEqual(exact.status_code, 200)
        self.assertEqual(exact.json()["segment_count"], 3)
        self.assertFalse(exact.json()["sampled"])

    def test_cached_overview_is_reused_without_reparsing_and_remains_private(self):
        from unittest.mock import patch
        from django.core.cache.backends.locmem import LocMemCache
        from core.slicer_preview_cache import layer_batch_toolpaths as parser
        self.client.force_login(self.owner)
        cache = LocMemCache("gcode-preview-test", {})
        url = f"/api/files/{self.asset.pk}/gcode/layers/?overview=1&detail=80&zs=0.2,0.4"
        with patch("core.slicer_preview_cache.cache", cache):
            with patch("core.slicer_preview_cache.layer_batch_toolpaths",
                       wraps=parser) as parse:
                first = self.client.get(url + "&all_zs=0.2,0.4")
                self.assertEqual(first.status_code, 200, first.content)
                self.assertTrue(first.json()["cached"])
                second = self.client.get(url)
                self.assertEqual(second.status_code, 200, second.content)
                self.assertTrue(second.json()["cached"])
                self.assertEqual(first.json()["layers"], second.json()["layers"])
                self.assertEqual(parse.call_count, 1)
            self.client.force_login(self.other)
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_bad_index_inventory_is_rejected_without_polluting_cache(self):
        self.client.force_login(self.owner)
        url = f"/api/files/{self.asset.pk}/gcode/layers/?overview=1&detail=80&zs=0.2,0.4&all_zs="
        for invalid in ("0.2,0.2", "0.4,0.2", "nan,0.4", "0.2,2001"):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.client.get(url + invalid).status_code, 400)

    def test_other_user_cannot_inspect_unpublished_output(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.get(
            f"/api/files/{self.asset.pk}/gcode/layers/?zs=0.2").status_code, 404)

    def test_invalid_layer_and_binary_are_rejected(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url.replace("0.2", "nan")).status_code, 400)
