"""Installed slicer version switching/removal must never cross engine boundaries."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from slicer_worker.engine_store_admin import _manifest, _write
from slicer_worker.engine_store_lifecycle import (
    IDENTITY, activate_installed, installed_versions, uninstall_engine,
)


class EngineLifecycleTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Path(self.temp.name)
        (self.store / "versions").mkdir()
        self.orca_current = self.make_engine("orcaslicer", "2.5.0")
        self.orca_old = self.make_engine("orcaslicer", "2.4.2")
        self.creality = self.make_engine("crealityprint", "7.3.1")
        _write(self.store, {"schema_version": 1, "engines": {
            "orcaslicer": self.orca_current,
            "crealityprint": self.creality,
        }})

    def make_engine(self, engine, version):
        root = self.store / "versions" / engine / version
        root.mkdir(parents=True)
        binary = root / (engine + ".AppImage")
        binary.write_bytes((engine + ":" + version).encode())
        binary.chmod(0o555)
        digest = hashlib.sha256(binary.read_bytes()).hexdigest()
        identity = {"engine": engine, "version": version, "binary": str(binary),
                    "binary_sha256": digest}
        (root / IDENTITY).write_text(json.dumps(identity))
        return {"version": version, "binary": str(binary), "binary_sha256": digest}

    def test_installed_version_inventory_is_engine_specific(self):
        versions = installed_versions(self.store)
        self.assertEqual({x["version"] for x in versions["orcaslicer"]}, {"2.4.2", "2.5.0"})
        self.assertEqual([x["version"] for x in versions["crealityprint"]], ["7.3.1"])
        self.assertTrue(next(x for x in versions["orcaslicer"] if x["version"] == "2.5.0")["active"])

    def test_downgrade_and_reupgrade_only_change_selected_engine(self):
        activate_installed(self.store, "orcaslicer", "2.4.2")
        active = _manifest(self.store)["engines"]
        self.assertEqual(active["orcaslicer"]["version"], "2.4.2")
        self.assertEqual(active["crealityprint"], self.creality)
        activate_installed(self.store, "orcaslicer", "2.5.0")
        self.assertEqual(_manifest(self.store)["engines"]["orcaslicer"]["version"], "2.5.0")
        self.assertTrue((self.store / "versions" / "orcaslicer" / "2.4.2").is_dir())

    def test_inactive_binary_tamper_fails_closed(self):
        binary = Path(self.orca_old["binary"])
        binary.chmod(0o755)
        binary.write_bytes(b"unexpected binary replacement")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            activate_installed(self.store, "orcaslicer", "2.4.2")
        self.assertEqual(_manifest(self.store)["engines"]["orcaslicer"], self.orca_current)

    def test_uninstall_one_engine_preserves_other_and_models(self):
        models = self.store / "models.gcode"
        models.write_text("G1 X1")
        result = uninstall_engine(self.store, "orcaslicer")
        self.assertNotIn("orcaslicer", result["engines"])
        self.assertEqual(_manifest(self.store)["engines"], {"crealityprint": self.creality})
        self.assertFalse((self.store / "versions" / "orcaslicer").exists())
        self.assertTrue(Path(self.creality["binary"]).exists())
        self.assertEqual(models.read_text(), "G1 X1")
        self.assertFalse((self.store / "previous.json").exists())

    def test_uninstall_unknown_engine_or_symlinked_version_refused(self):
        with self.assertRaises(ValueError):
            uninstall_engine(self.store, "../crealityprint")
        root = self.store / "versions" / "orcaslicer"
        link = root / "2.3.0"
        link.symlink_to(self.store / "versions" / "crealityprint", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "unsafe"):
            uninstall_engine(self.store, "orcaslicer")
        self.assertEqual(_manifest(self.store)["engines"]["orcaslicer"], self.orca_current)
        self.assertTrue(Path(self.creality["binary"]).exists())
