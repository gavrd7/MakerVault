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

    def test_streamed_input_matches_string_geometry_without_full_file_copy(self):
        import io
        from core.slicer_layer_preview import streamed_gcode_lines
        for mode in ({}, {"high_fidelity": True}, {"overview": True, "overview_limit": 80}):
            with self.subTest(mode=mode):
                expected = layer_batch_toolpaths(GCODE, [0.2, 0.4], **mode)
                with io.BytesIO(GCODE.encode("utf-8")) as handle:
                    actual = layer_batch_toolpaths(
                        streamed_gcode_lines(handle), [0.2, 0.4], **mode)
                self.assertEqual(actual, expected)

    def test_streamed_input_skips_oversized_lines_without_fake_commands(self):
        import io
        from core.slicer_layer_preview import streamed_gcode_lines
        extra = "; " + "x" * 9000 + "\n"
        with io.BytesIO((GCODE + extra).encode()) as handle:
            actual = layer_batch_toolpaths(streamed_gcode_lines(handle), [0.2, 0.4])
        self.assertEqual(actual, layer_batch_toolpaths(GCODE, [0.2, 0.4]))

    def test_streamed_input_rejects_binary_and_invalid_utf8(self):
        import io
        from core.slicer_layer_preview import streamed_gcode_lines
        for raw in (b"G1 X1 Y1 E1\x00\n", b"G1 X1 Y1 E1\xff\n"):
            with self.subTest(raw=raw), self.assertRaises((ValueError, UnicodeDecodeError)):
                with io.BytesIO(raw) as handle:
                    list(streamed_gcode_lines(handle))

    def test_dense_full_detail_layer_can_be_paged_without_missing_toolpaths(self):
        from unittest.mock import patch
        with patch("core.slicer_layer_preview.MAX_LAYER_SEGMENTS", 2):
            first = layer_batch_toolpaths(GCODE, [0.2], high_fidelity=True,
                                          page_start=0, max_total_segments=2)
            second = layer_batch_toolpaths(GCODE, [0.2], high_fidelity=True,
                                           page_start=2, max_total_segments=2)
        self.assertFalse(first["complete"])
        self.assertEqual(first["layers"][0]["next_offset"], 2)
        self.assertTrue(first["layers"][0]["has_more"])
        self.assertTrue(second["complete"])
        self.assertEqual(second["layers"][0]["next_offset"], 3)
        self.assertFalse(second["layers"][0]["has_more"])
        combined = first["layers"][0]["segments"] + second["layers"][0]["segments"]
        self.assertEqual(combined, exact_layer_toolpaths(GCODE, 0.2)["segments"])

    def test_non_coalesced_paged_layer_preserves_original_moves(self):
        from unittest.mock import patch
        with patch("core.slicer_layer_preview.MAX_LAYER_SEGMENTS", 2):
            first = layer_batch_toolpaths(GCODE, [0.2], page_start=0)
            second = layer_batch_toolpaths(GCODE, [0.2], page_start=2)
        self.assertFalse(first["complete"])
        self.assertTrue(second["complete"])
        self.assertEqual(first["layers"][0]["next_offset"], 2)
        self.assertEqual(second["layers"][0]["next_offset"], 3)
        self.assertEqual(
            first["layers"][0]["segments"] + second["layers"][0]["segments"],
            exact_layer_toolpaths(GCODE, 0.2)["segments"])

    def test_pagination_rejects_invalid_aggregate_requests(self):
        for kwargs in ({"page_start": -1}, {"page_start": "0"},
                       {"page_start": 0, "overview": True},
                       {"page_start": 2**53 + 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                layer_batch_toolpaths(GCODE, [0.2], **kwargs)

    def test_batched_layers_are_exact_and_ordered(self):
        result = layer_batch_toolpaths(GCODE, [0.2, 0.4])
        self.assertTrue(result["complete"])
        self.assertEqual([layer["z"] for layer in result["layers"]], [0.2, 0.4])
        self.assertEqual([layer["segment_count"] for layer in result["layers"]], [3, 1])
        self.assertEqual(result["layers"][0]["segments"],
                         exact_layer_toolpaths(GCODE, 0.2)["segments"])
        self.assertEqual(result["layers"][1]["segments"],
                         exact_layer_toolpaths(GCODE, 0.4)["segments"])

    def test_high_fidelity_preserves_geometry_and_only_merges_collinear_runs(self):
        source = (
            "G90\nM83\nG1 X0 Y0 Z0.2\n;TYPE:Outer wall\n"
            "G1 X5 Y0 E0.1\nG1 X10 Y0 E0.1\n"
            "G0 X20 Y0\nG1 X25 Y0 E0.1\n"
            "G1 X25 Y5 E0.1\n"
            ";TYPE:Support material\nG1 X25 Y10 E0.1\n"
            ";TYPE:Prime tower\nG1 X25 Y15 E0.1\n"
        )
        full = layer_batch_toolpaths(source, [0.2], high_fidelity=True)
        exact = exact_layer_toolpaths(source, 0.2)
        self.assertTrue(full["complete"])
        self.assertTrue(full["high_fidelity"])
        self.assertFalse(full["sampled"])
        self.assertEqual(full["layers"][0]["segment_count"], exact["segment_count"])
        self.assertEqual(len(exact["segments"]), 6)
        retained = full["layers"][0]["segments"]
        self.assertEqual(len(retained), 5)
        self.assertEqual(retained[0][:4], [0.0, 0.0, 10.0, 0.0])
        self.assertEqual(retained[1][:4], [20.0, 0.0, 25.0, 0.0])
        self.assertEqual([row[5] for row in retained[-2:]],
                         ["Support material", "Prime tower"])

    def test_high_fidelity_never_marks_truncated_geometry_complete(self):
        source = ("G90\nM83\nG1 X0 Y0 Z0.2\n;TYPE:Outer wall\n"
                  + "".join(f"G1 X{i+1} Y{i%2} E0.1\n" for i in range(20)))
        result = layer_batch_toolpaths(source, [0.2], high_fidelity=True,
                                       max_total_segments=2)
        self.assertFalse(result["complete"])
        self.assertTrue(result["layers"][0]["limited"])
        self.assertEqual(len(result["layers"][0]["segments"]), 2)

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
        self.assertTrue(any(row[5] == "Outer wall" for row in result))
        self.assertTrue(any(row[5] == "Sparse infill" for row in result))

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
        self.assertGreaterEqual(sum(move[5] == "Support material"
                                    for move in layer["segments"]), 16)
        self.assertTrue(any(move[5] == "Sparse infill" for move in layer["segments"]))
        self.assertEqual(layer["segments"],
                         sorted(layer["segments"], key=lambda move: move[0]))

    def test_prime_tower_keeps_its_own_geometry_budget(self):
        from core.slicer_layer_preview import _overview_segments
        from core.slicer_preview_features import is_prime_tower_feature
        assert is_prime_tower_feature("Prime tower")
        assert is_prime_tower_feature("Wipe tower")
        assert not is_prime_tower_feature("Outer wall")
        lines = ["G90", "M83", "G1 X0 Y0 Z0.2"]
        for role, count in (("Outer wall", 160), ("Support material", 150),
                            ("Prime tower", 100)):
            lines.append(f";TYPE:{role}")
            for index in range(count):
                lines.append(f"G1 X{index+1} Y{count} E0.1")
            lines.append("G1 X0 Y0")
        result = layer_batch_toolpaths("\n".join(lines), [0.2],
                                       overview=True, overview_limit=90)
        segments = result["layers"][0]["segments"]
        self.assertEqual(len(segments), 90)
        self.assertTrue(any(move[5] == "Outer wall" for move in segments))
        self.assertTrue(any(move[5] == "Support material" for move in segments))
        self.assertGreaterEqual(sum(move[5] == "Prime tower" for move in segments), 24)
        mobile = _overview_segments(segments, 80)
        self.assertGreaterEqual(sum(move[5] == "Prime tower" for move in mobile), 24)
        self.assertTrue(any(move[5] == "Support material" for move in mobile))
        self.assertTrue(any(move[5] == "Outer wall" for move in mobile))
        # Native G-code inspection never uses the reduced overview.
        self.assertEqual(exact_layer_toolpaths("\n".join(lines), 0.2)["segment_count"], 410)

    def test_mixed_object_sections_survive_every_layer_of_bounded_overview(self):
        from core.slicer_layer_preview import _overview_segments
        """A roof or tower must not replace the object's walls/inner geometry."""
        heights = [0.2, 0.4, 0.6, 0.8]
        source = ["G90", "M83"]
        for height in heights:
            source.append(f"G1 X0 Y0 Z{height}")
            for role, xbase, ybase in (
                ("Outer wall", 10, 10), ("Inner wall", 40, 20),
                ("Top surface", 70, 30), ("Sparse infill", 100, 40),
                ("Support material", 130, 50), ("Prime tower", 160, 60),
            ):
                source.append(f";TYPE:{role}")
                source.append(f"G1 X{xbase} Y{ybase}")
                for i in range(80):
                    source.append(f"G1 X{xbase+i+1} Y{ybase} E0.1")
        gcode = "\n".join(source)
        result = layer_batch_toolpaths(gcode, heights, overview=True, overview_limit=80)
        self.assertTrue(result["complete"])
        for row in result["layers"]:
            self.assertEqual(len(row["segments"]), 80)
            types = {move[5] for move in row["segments"]}
            self.assertEqual(types, {"Outer wall", "Inner wall", "Top surface",
                                     "Sparse infill", "Support material", "Prime tower"})
            # Each physically separate area retains its own original extrusion.
            self.assertTrue(all(any(move[5] == name for move in row["segments"])
                                for name in types))
            self.assertEqual(row["segments"], sorted(row["segments"],
                             key=lambda move: ("Outer wall", "Inner wall",
                             "Top surface", "Sparse infill",
                             "Support material", "Prime tower").index(move[5])))
            mobile = _overview_segments(row["segments"], 80)
            self.assertEqual(mobile, row["segments"])

    def test_balancer_never_exceeds_budget_with_all_six_feature_groups(self):
        from core.slicer_preview_features import balanced_overview_indices
        groups = {group: list(range(i*100, (i+1)*100))
                  for i, group in enumerate(("tower", "support", "shell",
                                             "skin", "inner", "body"))}
        selection = balanced_overview_indices(groups, 80)
        self.assertEqual(len(selection), 80)
        for values in groups.values():
            self.assertTrue(any(index in values for index in selection))
        self.assertGreaterEqual(sum(index in groups["tower"] for index in selection), 24)
        self.assertGreaterEqual(sum(index in groups["support"] for index in selection), 16)

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
        gcode=("G90\nM83\nG1 X10 Y0 Z20\n"
               ";TYPE:Outer wall\nG3 X0 Y10 I-10 J0 E0.5\n"
               "G3 X-10 Y0 I0 J-10 E0.5\n")
        result=exact_layer_toolpaths(gcode,20)
        self.assertGreater(result["segment_count"], 40)
        self.assertTrue(result["complete"])
        self.assertEqual(result["segments"][-1][2:4],[-10.0,0.0])
        self.assertTrue(all(abs(math.hypot(a[2],a[3])-10)<0.01
                            for a in result["segments"]))

    def test_preview_preserves_unextruded_travel_arc_without_fake_strand(self):
        gcode=("G90\nM83\nG1 X10 Y0 Z0.2\n"
               "G3 X0 Y10 I-10 J0\n"
               "G1 X0 Y20 E0.5\n")
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

    def test_large_source_streaming_preserves_selected_and_full_batch_toolpaths(self):
        from unittest.mock import patch
        from core.slicer_preview import generated_preview
        self.client.force_login(self.owner)
        with patch("core.slicer_layer_preview.MAX_LAYER_SOURCE_BYTES", 64):
            direct = self.client.get(
                f"/api/files/{self.asset.pk}/gcode/layers/?zs=0.2,0.4&quality=full&direct=1")
            self.assertEqual(direct.status_code, 200, direct.content)
            self.assertTrue(direct.json()["complete"])
            self.assertEqual([r["segment_count"] for r in direct.json()["layers"]], [3, 1])
            exact = self.client.get(self.url)
            self.assertEqual(exact.status_code, 200, exact.content)
            self.assertEqual(exact.json()["segment_count"], 3)

    def test_large_source_skips_unavailable_warmer_and_streams_directly(self):
        from unittest.mock import patch
        self.client.force_login(self.owner)
        with (patch("core.slicer_layer_preview.MAX_LAYER_SOURCE_BYTES", 64),
              patch("core.tasks.warm_gcode_preview_task.delay") as schedule):
            response = self.client.get(
                f"/api/files/{self.asset.pk}/gcode/layers/?zs=0.2,0.4&quality=full&warm=1")
            self.assertEqual(response.status_code, 200, response.content)
            self.assertTrue(response.json()["complete"])
            schedule.assert_not_called()

    def test_selected_layer_endpoint_can_return_every_unmerged_movement(self):
        from unittest.mock import patch
        self.client.force_login(self.owner)
        with patch("core.slicer_layer_preview.MAX_LAYER_SEGMENTS", 2):
            first = self.client.get(self.url + "&page_start=0")
            second = self.client.get(self.url + "&page_start=2")
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(second.status_code, 200, second.content)
        self.assertTrue(first.json()["has_more"])
        self.assertFalse(second.json()["has_more"])
        self.assertEqual(
            first.json()["segments"] + second.json()["segments"],
            exact_layer_toolpaths(GCODE, 0.2)["segments"])

    def test_full_detail_endpoint_paginates_dense_layers_and_keeps_owner_scope(self):
        from unittest.mock import patch
        self.client.force_login(self.owner)
        base = f"/api/files/{self.asset.pk}/gcode/layers/?quality=full&zs=0.2"
        with patch("core.slicer_layer_preview.MAX_LAYER_SEGMENTS", 2):
            first = self.client.get(base + "&page_start=0")
            second = self.client.get(base + "&page_start=2")
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(second.status_code, 200, second.content)
        self.assertTrue(first.json()["layers"][0]["has_more"])
        self.assertFalse(second.json()["layers"][0]["has_more"])
        self.assertEqual(first.json()["layers"][0]["next_offset"], 2)
        self.assertEqual(second.json()["layers"][0]["next_offset"], 3)
        self.assertEqual(self.client.get(base + "&page_start=-1").status_code, 400)
        self.assertEqual(self.client.get(base + "&page_start=oops").status_code, 400)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(base + "&page_start=0").status_code, 404)

    def test_large_slicer_preview_inventory_scans_past_metadata_prefix(self):
        from unittest.mock import patch
        from core.gcode_analysis import inspect_asset
        with patch("core.gcode_analysis.MAX_SCAN_BYTES", 60):
            result = inspect_asset(self.asset)
        self.assertTrue(result["preview_truncated"])
        self.assertEqual(result["analysis"]["slicer_preview"]["layer_count"], 2)
        self.assertEqual(result["analysis"]["slicer_preview"]["layers"], [0.2, 0.4])
        self.assertTrue(result["analysis"]["slicer_preview"]["complete"])

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

    def test_cold_preview_enqueues_once_and_does_not_parse_in_http_request(self):
        from unittest.mock import patch
        from django.core.cache.backends.locmem import LocMemCache
        backend=LocMemCache("preview-nonblocking-test", {})
        self.client.force_login(self.owner)
        url=f"/api/files/{self.asset.pk}/gcode/layers/?zs=0.2,0.4&overview=1&detail=80&warm=1"
        with (patch("django.core.cache.cache", backend),
              patch("core.slicer_preview_cache.cache", backend),
              patch("core.tasks.warm_gcode_preview_task.delay") as queued,
              patch("core.slicer_layer_preview.layer_batch_toolpaths") as parser):
            first=self.client.get(url)
            second=self.client.get(url)
            self.assertEqual(first.status_code, 202, first.content)
            self.assertEqual(second.status_code, 202, second.content)
            self.assertEqual(queued.call_count, 1)
            parser.assert_not_called()
        self.assertEqual(self.client.get(url + "&direct=1").status_code, 200)

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

    def test_post_slice_cache_prepares_both_resolutions_without_extra_parses(self):
        from unittest.mock import patch
        from django.core.cache.backends.locmem import LocMemCache
        from core.slicer_preview_cache import (
            warm_asset_overviews, cached_batch, preview_index_key,
        )
        from core.slicer_layer_preview import layer_batch_toolpaths
        backend = LocMemCache("preview-warmup-variants", {})
        with patch("core.slicer_preview_cache.cache", backend):
            with patch("core.slicer_preview_cache.layer_batch_toolpaths",
                       wraps=layer_batch_toolpaths) as parse:
                self.assertTrue(warm_asset_overviews(self.asset, GCODE.encode("utf-8")))
                self.assertEqual(parse.call_count, 1)
                for detail in (110, 220):
                    result = cached_batch(preview_index_key(self.asset, detail),
                                          [0.2, 0.4])
                    self.assertIsNotNone(result)
                    self.assertTrue(result["cached"])
                self.assertTrue(warm_asset_overviews(self.asset, GCODE.encode("utf-8")))
                self.assertEqual(parse.call_count, 1)

    def test_preview_cache_response_exposes_timing_and_hit(self):
        from unittest.mock import patch
        from django.core.cache.backends.locmem import LocMemCache
        backend = LocMemCache("preview-response-timing", {})
        self.client.force_login(self.owner)
        url = f"/api/files/{self.asset.pk}/gcode/layers/?overview=1&detail=80&zs=0.2,0.4"
        with patch("core.slicer_preview_cache.cache", backend):
            self.assertEqual(self.client.get(url + "&all_zs=0.2,0.4").status_code, 200)
            cached = self.client.get(url)
            self.assertEqual(cached.status_code, 200)
            self.assertEqual(cached["X-MakerVault-Preview-Cache"], "hit")
            self.assertIn("preview;dur=", cached["Server-Timing"])

    def test_large_file_warmer_streams_bounded_batches_and_publishes_exact_cache(self):
        from unittest.mock import patch
        from django.core.cache.backends.locmem import LocMemCache
        from core.slicer_preview_cache import (
            warm_streamed_high_fidelity, cached_batch, preview_index_key,
        )
        backend = LocMemCache("streamed-large-preview-cache", {})
        with patch("core.slicer_preview_cache.cache", backend):
            self.assertTrue(warm_streamed_high_fidelity(self.asset))
            key = preview_index_key(self.asset, "full-v1")
            result = cached_batch(key, [0.2, 0.4])
            self.assertIsNotNone(result)
            self.assertTrue(result["complete"])
            self.assertEqual(
                result["layers"][0]["segment_count"],
                exact_layer_toolpaths(GCODE, 0.2)["segment_count"])

    def test_streamed_warmer_does_not_publish_incomplete_geometry(self):
        from unittest.mock import patch
        from django.core.cache.backends.locmem import LocMemCache
        from core.slicer_preview_cache import (
            warm_streamed_high_fidelity, cached_batch, preview_index_key,
        )
        backend = LocMemCache("streamed-incomplete-preview-cache", {})
        with (patch("core.slicer_preview_cache.cache", backend),
              patch("core.slicer_layer_preview.MAX_LAYER_SEGMENTS", 1)):
            self.assertFalse(warm_streamed_high_fidelity(self.asset))
            self.assertIsNone(cached_batch(
                preview_index_key(self.asset, "full-v1"), [0.2, 0.4]))

    def test_full_render_cache_uses_smaller_blocks_without_losing_paths(self):
        from unittest.mock import patch
        from django.core.cache.backends.locmem import LocMemCache
        from core.slicer_preview_cache import (
            warm_streamed_high_fidelity, cached_batch, preview_index_key,
            FULL_RENDER_CACHE_LAYERS,
        )
        backend = LocMemCache("render-block-size-preview", {})
        with patch("core.slicer_preview_cache.cache", backend):
            self.assertTrue(warm_streamed_high_fidelity(self.asset))
            key = preview_index_key(self.asset, "full-v1")
            self.assertEqual(backend.get(key + ":block_size"), FULL_RENDER_CACHE_LAYERS)
            self.assertEqual(
                cached_batch(key, [0.2, 0.4])["layers"][0]["segments"],
                layer_batch_toolpaths(GCODE, [0.2], high_fidelity=True)["layers"][0]["segments"])

    def test_successful_cold_exact_request_is_reused_without_gcode_scan(self):
        from unittest.mock import patch
        from django.core.cache.backends.locmem import LocMemCache
        from core.slicer_layer_preview import layer_batch_toolpaths
        backend = LocMemCache("direct-owner-preview", {})
        self.client.force_login(self.owner)
        url = f"/api/files/{self.asset.pk}/gcode/layers/?quality=full&zs=0.2,0.4&direct=1"
        with patch("core.slicer_preview_cache.cache", backend):
            with patch("core.slicer_layer_preview.layer_batch_toolpaths", wraps=layer_batch_toolpaths) as parser:
                first = self.client.get(url)
                second = self.client.get(url)
                self.assertEqual(first.status_code, 200, first.content)
                self.assertEqual(second.status_code, 200, second.content)
                self.assertEqual(first.json()["layers"], second.json()["layers"])
                self.assertEqual(second["X-MakerVault-Preview-Cache"], "direct-hit")
                self.assertEqual(parser.call_count, 1)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_cached_full_preview_serves_unaligned_mobile_batches_across_blocks(self):
        import json
        import zlib
        from unittest.mock import patch
        from django.core.cache.backends.locmem import LocMemCache
        from core.slicer_preview_cache import cached_batch
        backend = LocMemCache("preview-mobile-unaligned-cache", {})
        key = "unaligned-64-layer-blocks"
        heights = [round((i + 1) * 0.2, 3) for i in range(130)]
        backend.set(key + ":manifest", heights)
        for block in range(3):
            data = {
                "complete": True, "cached": True,
                "layers": [{"z": z, "segments": [[index]]}
                           for index, z in enumerate(
                               heights[block * 64:(block + 1) * 64],
                               start=block * 64)],
            }
            backend.set(
                key + ":batch:" + str(block),
                zlib.compress(json.dumps(data).encode("utf-8")))
        with patch("core.slicer_preview_cache.cache", backend):
            for start, count in ((0, 15), (15, 15), (60, 15),
                                 (120, 10), (64, 1)):
                with self.subTest(start=start, count=count):
                    result = cached_batch(key, heights[start:start + count])
                    self.assertIsNotNone(result)
                    self.assertEqual(len(result["layers"]), count)
                    self.assertEqual(
                        [row["segments"][0][0] for row in result["layers"]],
                        list(range(start, start + count)))

    def test_full_quality_cached_response_and_original_selected_layer(self):
        from unittest.mock import patch
        from django.core.cache.backends.locmem import LocMemCache
        from core.slicer_preview_cache import (
            warm_asset_high_fidelity, cached_batch, preview_index_key,
        )
        backend = LocMemCache("gcode-full-quality-test", {})
        self.client.force_login(self.owner)
        url = f"/api/files/{self.asset.pk}/gcode/layers/?quality=full&zs=0.2,0.4"
        with patch("core.slicer_preview_cache.cache", backend):
            self.assertTrue(warm_asset_high_fidelity(self.asset, GCODE.encode("utf-8")))
            expected = cached_batch(preview_index_key(self.asset, "full-v1"), [0.2, 0.4])
            self.assertIsNotNone(expected)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response["X-MakerVault-Preview-Cache"], "hit")
            self.assertTrue(response.json()["high_fidelity"])
            self.assertFalse(response.json()["sampled"])
            self.assertEqual(response.json()["layers"], expected["layers"])
            self.assertEqual(self.client.get(self.url).json()["segment_count"], 3)

    def test_other_user_cannot_inspect_unpublished_output(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.get(
            f"/api/files/{self.asset.pk}/gcode/layers/?zs=0.2").status_code, 404)

    def test_invalid_layer_and_binary_are_rejected(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url.replace("0.2", "nan")).status_code, 400)
