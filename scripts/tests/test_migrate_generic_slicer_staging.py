"""Generic one-container staging migration guards (no Docker invocation)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import migrate_generic_slicer_staging as migration
from scripts import install_slicer_staging as staging

OLD_IMAGE = "sha256:" + "a" * 64
NEW_IMAGE = "sha256:" + "b" * 64


def previous_env():
    return "\n".join([
        "# staging-only secrets are never printed",
        "MAKERVAULT_SLICER_EXECUTION_ENABLED=1",
        "MAKERVAULT_SLICER_WORKER_TOKEN=keep-me-secret",
        "MAKERVAULT_SLICER_WORKER_IMAGE=" + OLD_IMAGE,
        "MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST=" + OLD_IMAGE,
        "MAKERVAULT_SLICER_ENGINES_JSON='" + json.dumps({
            "orcaslicer": {"version": "2.5.0", "binary_sha256": migration.ENGINE_SHA}
        }, separators=(",", ":")) + "'",
        "SLICER_ENGINES_JSON='" + json.dumps({
            "orcaslicer": {
                "binary": "/opt/engines/orcaslicer.AppImage",
                "version": "2.5.0", "binary_sha256": migration.ENGINE_SHA,
            }
        }, separators=(",", ":")) + "'",
        "",
    ])


class GenericStagingMigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.env = self.root / ".slicer-staging.env"
        self.env.write_text(previous_env())
        self.env.chmod(0o600)
        self.overlay = self.root / "compose.slicer.staging.yaml"
        self.overlay.write_text("volumes:\n  makervault_slicer_engines:\n")
        self.backup = self.root / ".slicer-staging.env.pre-generic"
        patches = [
            patch.multiple(staging, ROOT=self.root, DOTENV=self.env, OVERLAY=self.overlay),
            patch.object(migration, "BACKUP", self.backup),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_preflight_retains_old_secret_and_checks_rollback_image(self):
        calls = []
        def fake_run(args, **_):
            calls.append(args)
            return "image inspected"
        with patch.object(migration, "_safe_run", side_effect=fake_run):
            raw = migration.preflight()
        self.assertEqual(raw, previous_env())
        self.assertEqual(self.env.read_text(), raw)
        self.assertTrue(any("image" in c and "inspect" in c and OLD_IMAGE in c for c in calls))

    def test_replacement_updates_only_the_image_identity(self):
        result = migration._replace_approval(previous_env(), NEW_IMAGE)
        self.assertIn("MAKERVAULT_SLICER_WORKER_IMAGE=" + NEW_IMAGE, result)
        self.assertIn("MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST=" + NEW_IMAGE, result)
        self.assertIn("MAKERVAULT_SLICER_WORKER_TOKEN=keep-me-secret", result)
        self.assertIn(migration.ENGINE_SHA, result)
        self.assertNotIn("MAKERVAULT_SLICER_WORKER_IMAGE=" + OLD_IMAGE, result)

    def test_preflight_refuses_existing_backup(self):
        self.backup.write_text(previous_env())
        with patch.object(migration, "_safe_run") as command:
            with self.assertRaisesRegex(ValueError, "Existing generic migration backup"):
                migration.preflight()
        command.assert_not_called()

    def test_preflight_refuses_wrong_engine_digest(self):
        self.env.write_text(previous_env().replace(migration.ENGINE_SHA, "0" * 64))
        with patch.object(migration, "_safe_run") as command:
            with self.assertRaisesRegex(ValueError, "not the independently reviewed"):
                migration.preflight()
        command.assert_not_called()

    def test_rollback_reuses_previously_pinned_image(self):
        self.backup.write_text(previous_env())
        self.backup.chmod(0o600)
        self.env.write_text(migration._replace_approval(previous_env(), NEW_IMAGE))
        with patch.object(migration, "_restart") as restart:
            migration.rollback()
        restart.assert_called_once()
        self.assertEqual(self.env.read_text(), previous_env())
        self.assertTrue(self.backup.exists())

    def test_rollback_refuses_insecure_backup(self):
        self.backup.write_text(previous_env())
        self.backup.chmod(0o644)
        with patch.object(migration, "_restart") as restart:
            with self.assertRaisesRegex(ValueError, "backup is missing or unsafe"):
                migration.rollback()
        restart.assert_not_called()


if __name__ == "__main__":
    unittest.main()
