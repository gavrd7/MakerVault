import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from slicer_worker.stage_engines import stage_engines


class StageSlicerEngineTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.orca = self.root / "OrcaSlicer.AppImage"
        self.creality = self.root / "CrealityPrint.AppImage"
        for path in (self.orca, self.creality):
            path.write_bytes(b"test-only appimage fixture: " + path.name.encode())

    def item(self, name, version, path):
        return (name, version, str(path), hashlib.sha256(path.read_bytes()).hexdigest())

    def test_both_engines_are_independent_and_produce_config(self):
        results = stage_engines([
            self.item("orcaslicer", "2.4.2", self.orca),
            self.item("crealityprint", "7.3.0", self.creality),
        ], self.root / "stage")
        self.assertEqual(results["status"], "staged_not_tested")
        self.assertEqual(set(__import__("json").loads(results["worker_engines_json"])), {
            "orcaslicer", "crealityprint"
        })
        self.assertEqual(set(__import__("json").loads(results["app_approvals_json"])), {
            "orcaslicer", "crealityprint"
        })
        self.assertTrue((self.root / "stage" / "orcaslicer.AppImage").is_file())
        self.assertTrue((self.root / "stage" / "crealityprint.AppImage").is_file())

    def test_creality_only_is_not_blocked_by_missing_orca(self):
        result = stage_engines([
            self.item("crealityprint", "7.3.0", self.creality),
        ], self.root / "creality-stage")
        self.assertIn("crealityprint", result["worker_engines_json"])
        self.assertNotIn("orcaslicer", result["worker_engines_json"])

    def test_wrong_checksum_fails_before_writing_any_assets(self):
        dest = self.root / "wrong-sha"
        bad = ("orcaslicer", "2.4.2", str(self.orca), "0" * 64)
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            stage_engines([bad], dest)
        self.assertFalse(dest.exists())

    def test_rejects_duplicate_engine_and_nonempty_destination(self):
        original = self.item("orcaslicer", "2.4.2", self.orca)
        with self.assertRaisesRegex(ValueError, "unique"):
            stage_engines([original, original], self.root / "duplicates")
        occupied = self.root / "occupied"
        occupied.mkdir()
        (occupied / "existing.txt").write_text("retain this")
        with self.assertRaisesRegex(ValueError, "empty"):
            stage_engines([original], occupied)
        self.assertTrue((occupied / "existing.txt").is_file())

    def test_symlink_executable_is_not_staged(self):
        link = self.root / "link.AppImage"
        link.symlink_to(self.orca)
        with self.assertRaisesRegex(ValueError, "regular"):
            stage_engines([self.item("orcaslicer", "2.4.2", self.orca)[:2]
                           + (str(link), hashlib.sha256(self.orca.read_bytes()).hexdigest())],
                          self.root / "links")
