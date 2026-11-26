"""Conservative engine capability contracts; upstream similarity is not approval."""
from django.test import SimpleTestCase

from core.slicer_capabilities import (
    FEATURES, annotated_features, native_capabilities, native_compatibility_errors,
)


class SlicerCapabilityTests(SimpleTestCase):
    def test_orca_editor_does_not_claim_native_export(self):
        for version in ("2.4.2", "2.5.0"):
            result = native_capabilities("orcaslicer", version)
            self.assertEqual(set(result), set(FEATURES))
            self.assertTrue(all(item["status"] == "draft_only" for key, item in result.items()
                                if key not in ("variable_layer_profile", "support_paint", "seam_paint", "fuzzy_skin_paint")))
            self.assertEqual(result["support_paint"]["status"],
                             "test_only" if version == "2.5.0" else "draft_only")
            self.assertEqual(result["seam_paint"]["status"],
                             "test_only" if version == "2.5.0" else "draft_only")
            self.assertEqual(result["fuzzy_skin_paint"]["status"],
                             "test_only" if version == "2.5.0" else "draft_only")
            self.assertEqual(result["variable_layer_profile"]["status"],
                             "test_only" if version == "2.5.0" else "draft_only")

    def test_unreviewed_versions_and_cura_are_not_executable(self):
        self.assertTrue(all(
            item["status"] == "unverified"
            for item in native_capabilities("orcaslicer", "9.9.9").values()))
        self.assertTrue(all(
            item["status"] == "incompatible"
            for item in native_capabilities("cura", "5.0").values()))
        for engine in ("bambustudio", "crealityprint", "prusaslicer", "snapmakerorca"):
            self.assertTrue(all(
                item["status"] == "unverified"
                for item in native_capabilities(engine, "2.5.0").values()))

    def test_pinned_prusa_verified_features_and_restricted_offline_painting(self):
        caps = native_capabilities("prusaslicer", "2.9.7")
        self.assertEqual(caps["variable_layer_profile"]["status"], "verified")
        self.assertEqual(caps["colour_paint"]["status"], "test_only")
        self.assertEqual(caps["seam_paint"]["status"], "test_only")
        self.assertIn("T1–T4", caps["colour_paint"]["reason"])
        self.assertIn("front-face", caps["seam_paint"]["reason"])
        self.assertIn("offline", caps["colour_paint"]["reason"])
        self.assertTrue(all(caps[name]["status"] == "verified" for name in (
            "support_paint", "fuzzy_skin_paint")))
        self.assertEqual(native_capabilities("prusaslicer", "2.9.6")["variable_layer_profile"]["status"],
                         "unverified")

    def test_creality_colour_paint_experimental_only_on_native_73(self):
        caps = native_capabilities("crealityprint", "7.3.1")
        self.assertEqual(caps["colour_paint"]["status"], "test_only")
        for feature in ("support_paint", "seam_paint",
                        "fuzzy_skin_paint", "variable_layer_profile"):
            self.assertEqual(caps[feature]["status"], "test_only")
            self.assertIn("one", caps[feature]["reason"])
        self.assertEqual(
            native_capabilities("crealityprint", "8.0")["colour_paint"]["status"],
            "unverified",
        )

    def test_engine_api_advertises_installed_creality_colour_paint(self):
        from unittest.mock import patch
        from django.test import RequestFactory
        from core.slicer_api import engines
        import json

        request = RequestFactory().get("/api/printing/slicer/engines/")
        request.user = type("User", (), {"is_authenticated": True, "is_superuser": False})()
        with patch("core.slicer_api.verified_installation", return_value={
            "crealityprint": {"version": "7.3.1.6378"}
        }):
            response = engines(request)
        self.assertEqual(response.status_code, 200)
        rows = json.loads(response.content)["engines"]
        creality = next(row for row in rows if row["key"] == "crealityprint")
        caps = creality["feature_capabilities"]
        self.assertEqual(caps["7.3.1.6378"]["colour_paint"]["status"], "test_only")
        self.assertEqual(caps["7.3.1"]["colour_paint"]["status"], "test_only")
        self.assertEqual(caps["default"]["colour_paint"]["status"], "unverified")
        self.assertEqual(caps["7.3.1.6378"]["support_paint"]["status"], "test_only")

    def test_detects_used_edits_without_falsely_flagging_empty_metadata(self):
        plates = [
            {"objects": [
                {"colour_paint": {"version": 2, "regions": []},
                 "support_paint": {"regions": [{"slot": 0}]},
                 "variable_layer_profile": {"bands": [{"from_mm": 0, "to_mm": 3}]}},
                {"seam_paint": {"regions": []},
                 "fuzzy_skin_paint": {"regions": [{"slot": 0}]}},
            ]},
            {"objects": [{"colour_paint": {"faces": {"2": 1}}}]},
        ]
        self.assertEqual(annotated_features(plates), [
            "colour_paint", "fuzzy_skin_paint", "support_paint", "variable_layer_profile"
        ])
        issues = native_compatibility_errors("cura", "5.0", plates)
        self.assertEqual(len(issues), 4)
        self.assertTrue(all(row["status"] == "incompatible" for row in issues))
