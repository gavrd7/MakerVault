"""Slicing engine registry must remain inert until a verified worker is connected."""
from django.test import SimpleTestCase

from core.slicer_engines import ENGINES, engine_catalogue, get_engine, validate_engine_selection


DIGEST = "sha256:" + "a" * 64


class SlicerEngineRegistryTests(SimpleTestCase):
    def test_catalogue_is_user_prioritised_and_does_not_claim_availability(self):
        rows = engine_catalogue()
        self.assertEqual([row["key"] for row in rows], ["orcaslicer", "crealityprint", "bambustudio", "prusaslicer", "snapmakerorca", "elegooslicer", "cura", "anycubicslicernext"])
        self.assertTrue(all(row["status"] == "candidate" for row in rows))
        self.assertTrue(all(row["available"] is False and row["enabled"] is False for row in rows))
        self.assertEqual({row["profile_format"] for row in rows}, {"orca-json", "creality-json", "bambu-json", "prusa-ini", "snapmaker-orca-json", "elegoo-native-unverified", "cura-native-unverified", "anycubic-next-native-unverified"})
        self.assertEqual(len({engine.key for engine in ENGINES}), len(ENGINES))
        self.assertEqual(rows[0]["key"], "orcaslicer")

    def test_unknown_engine_or_client_path_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            get_engine("../bin/prusa-slicer")
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            validate_engine_selection("random-cli", "1.0", {})

    def test_requires_pinned_installed_verified_and_enabled_worker_engine(self):
        for registered in (
            None, {}, {"orcaslicer": {}},
            {"orcaslicer": {"version": "1.0", "enabled": True, "verified": False, "image_digest": DIGEST}},
            {"orcaslicer": {"version": "1.0", "enabled": False, "verified": True, "image_digest": DIGEST}},
            {"orcaslicer": {"version": "1.0", "enabled": True, "verified": True, "image_digest": "latest"}},
        ):
            with self.subTest(registered=registered), self.assertRaises(ValueError):
                validate_engine_selection("orcaslicer", "1.0", registered)
        configured = {"orcaslicer": {"version": "1.0", "enabled": True, "verified": True, "image_digest": DIGEST}}
        with self.assertRaisesRegex(ValueError, "not installed"):
            validate_engine_selection("orcaslicer", "2.0", configured)
        with self.assertRaises(ValueError):
            validate_engine_selection("orcaslicer", "../host", {})
        selected = validate_engine_selection("orcaslicer", "1.0", configured)
        self.assertEqual(selected, {
            "engine": "orcaslicer", "version": "1.0", "image_digest": DIGEST,
            "profile_format": "orca-json",
        })

    def test_prusa_and_orca_keep_separate_native_profile_formats(self):
        self.assertNotEqual(get_engine("prusaslicer").profile_format, get_engine("orcaslicer").profile_format)
