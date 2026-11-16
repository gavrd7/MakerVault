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
                                if key not in ("variable_layer_profile", "support_paint")))
            self.assertEqual(result["support_paint"]["status"],
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
