"""Offline installer contract tests: no real downloads, Docker or engine launch."""
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from scripts import install_slicer_staging as installer


class ReleaseMetadataTests(unittest.TestCase):
    def test_reject_wrong_publisher_or_missing_digest(self):
        response = MagicMock()
        response.status = 200
        response.headers = {}
        response.read.return_value = b'{"assets":[{"name":"' + installer.ASSET.encode() + b'","digest":"", "browser_download_url":"https://github.com/evil/release"}]}'
        response.__enter__ = MagicMock(return_value=response)
        response.__exit__ = MagicMock(return_value=False)
        with patch.object(installer, "urlopen", return_value=response):
            with self.assertRaisesRegex(ValueError, "pinned path"):
                installer._github_asset()

    def test_official_matching_release_requires_sha256(self):
        url = "https://github.com/OrcaSlicer/OrcaSlicer/releases/download/" + installer.TAG + "/" + installer.ASSET
        payload = ('{"assets":[{"name":"' + installer.ASSET +
                   '","digest":"sha256:' + installer.APPROVED_ORCA_RELEASES[installer.VERSION] + '","browser_download_url":"' + url + '"}]}')
        response = MagicMock()
        response.status = 200
        response.headers = {}
        response.read.return_value = payload.encode()
        response.__enter__ = MagicMock(return_value=response)
        response.__exit__ = MagicMock(return_value=False)
        with patch.object(installer, "urlopen", return_value=response):
            self.assertEqual(installer._github_asset(), (url, installer.APPROVED_ORCA_RELEASES[installer.VERSION]))

    def test_engine_asset_name_remains_pinned(self):
        self.assertEqual(installer.TAG, "v2.5.0")
        self.assertIn("Ubuntu2404", installer.ASSET)
        self.assertEqual(installer.VERSION, "2.5.0")


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = self.root / ".slicer-staging.env"
        self.env.write_text("MAKERVAULT_SLICER_EXECUTION_ENABLED=0\n")
        self.env.chmod(0o600)
        self.variables = patch.multiple(installer, ROOT=self.root,
                                        DOTENV=self.env, BUNDLE=self.root / "slicer-engine-assets",
                                        OVERLAY=self.root / "compose.slicer.staging.yaml")
        self.variables.start()
        self.addCleanup(self.variables.stop)

    def test_exclusive_config_file_is_private_and_can_be_reloaded(self):
        installer._save_env("MAKERVAULT_SLICER_EXECUTION_ENABLED=1\n")
        self.assertEqual(installer._read_env().strip(), "MAKERVAULT_SLICER_EXECUTION_ENABLED=1")
        self.assertFalse(self.env.stat().st_mode & 0o077)

    def test_world_readable_secret_file_is_refused(self):
        self.env.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "insecure"):
            installer._read_env()

    def test_compose_uses_staging_overlay_without_profiles(self):
        (self.root / "compose.staging.yaml").touch()
        args = installer._compose_args()
        self.assertIn("compose.slicer.staging.yaml", args)
        self.assertIn("compose.staging.yaml", args)
        self.assertNotIn("--profile", args)
        self.assertIn("--env-file", args)

    def test_interrupted_build_can_resume_only_checksum_verified_assets(self):
        import hashlib
        import json
        bundle = self.root / "slicer-engine-assets"
        bundle.mkdir()
        binary = bundle / "orcaslicer.AppImage"
        binary.write_bytes(b"test-only candidate bytes")
        digest = hashlib.sha256(binary.read_bytes()).hexdigest()
        (bundle / "manifest.json").write_text(json.dumps({
            "engines": {"orcaslicer": {
                "version": installer.VERSION,
                "binary": "/opt/engines/orcaslicer.AppImage",
                "binary_sha256": digest,
            }}
        }))
        result = installer._resume_staged_bundle()
        self.assertIn(digest, result["app_approvals_json"])
        binary.write_bytes(b"tampered candidate bytes")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            installer._resume_staged_bundle()

    def test_update_retains_slicer_worker_compose_and_existing_private_config(self):
        (self.root / "compose.slicer.staging.yaml").touch()
        calls = []
        before = self.env.read_bytes()
        with patch.object(installer, "_run", side_effect=lambda args, **kwargs: calls.append(args)):
            installer.update()
        self.assertEqual(before, self.env.read_bytes())
        self.assertTrue(any(cmd[-2:] == ["config", "--quiet"] for cmd in calls))
        updater = next(cmd for cmd in calls if "up" in cmd)
        self.assertEqual(updater[-4:], ["up", "-d", "--build", "makervault"])
        self.assertIn("compose.slicer.staging.yaml", updater)
        self.assertIn(".slicer-staging.env", updater)
        self.assertNotIn("slicer-worker", updater[-4:])

    def test_upgrade_retains_secret_and_rollback_bundle(self):
        import hashlib
        from slicer_worker.stage_engines import stage_engines
        old = self.root / "old.AppImage"
        old.write_bytes(b"old fixture")
        stage_engines([("orcaslicer", "2.4.2", str(old),
                       hashlib.sha256(old.read_bytes()).hexdigest())],
                      self.root / "slicer-engine-assets")
        old_image = "sha256:" + "a" * 64
        env = "\n".join([
            "MAKERVAULT_SLICER_EXECUTION_ENABLED=1",
            "MAKERVAULT_SLICER_WORKER_TOKEN=retain-secret",
            "MAKERVAULT_SLICER_WORKER_IMAGE=" + old_image,
            "MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST=" + old_image,
            "MAKERVAULT_SLICER_ENGINES_JSON='{}'",
            "SLICER_ENGINES_JSON='{}'", "",
        ])
        self.env.write_text(env)
        candidate = b"new fixture"
        digest = hashlib.sha256(candidate).hexdigest()
        new_image = "sha256:" + "b" * 64
        def download(_url, _sha, dest):
            dest.write_bytes(candidate)
        def run(args, **kwargs):
            return new_image if "inspect" in args else ""
        with (
            patch.object(installer, "_github_asset", return_value=("https://example.invalid/file", digest)),
            patch.object(installer, "_download_verified", side_effect=download),
            patch.object(installer, "_run", side_effect=run),
        ):
            installer.upgrade_orca("2.5.0")
        self.assertIn("retain-secret", self.env.read_text())
        self.assertIn('"version":"2.5.0"', self.env.read_text())
        self.assertIn(new_image, self.env.read_text())
        self.assertEqual((self.root / ".slicer-staging.env.pre-upgrade").read_text(), env)
        self.assertTrue((self.root / "slicer-engine-assets.pre-upgrade" / "orcaslicer.AppImage").is_file())

    def test_upgrade_refuses_previous_backup(self):
        (self.root / ".slicer-staging.env.pre-upgrade").touch()
        with patch.object(installer, "_resume_staged_bundle", return_value={
            "worker_engines_json": '{"orcaslicer":{"version":"2.4.2"}}'
        }), patch.object(installer, "_github_asset") as download:
            with self.assertRaisesRegex(ValueError, "backup exists"):
                installer.upgrade_orca("2.5.0")
        download.assert_not_called()

    def test_update_requires_private_slicer_config(self):
        self.env.unlink()
        with patch.object(installer, "_run") as run:
            with self.assertRaisesRegex(ValueError, "No prepared"):
                installer.update()
        run.assert_not_called()

    def test_enable_and_disable_are_explicit_and_reversible(self):
        (self.root / "slicer-engine-assets").mkdir()
        calls = []
        with patch.object(installer, "_run", side_effect=lambda cmd, **kwargs: calls.append(cmd)):
            installer.enable()
            self.assertIn("MAKERVAULT_SLICER_EXECUTION_ENABLED=1", self.env.read_text())
            self.assertTrue(any(cmd[-3:] == ["up", "-d", "--build"] for cmd in calls))
            installer.disable()
            self.assertIn("MAKERVAULT_SLICER_EXECUTION_ENABLED=0", self.env.read_text())
            self.assertTrue(any(cmd[-2:] == ["stop", "slicer-worker"] for cmd in calls))


if __name__ == "__main__":
    unittest.main()
