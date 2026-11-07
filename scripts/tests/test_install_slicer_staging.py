"""Offline installer contract tests: no real downloads, Docker or engine launch."""
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from scripts import install_slicer_staging as installer


class ReleaseMetadataTests(unittest.TestCase):
    def test_reject_wrong_publisher_or_missing_digest(self):
        response = Mock()
        response.status = 200
        response.headers = {}
        response.read.return_value = b'{"assets":[{"name":"' + installer.ASSET.encode() + b'","digest":"", "browser_download_url":"https://github.com/evil/release"}]}'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch.object(installer, "urlopen", return_value=response):
            with self.assertRaisesRegex(ValueError, "pinned path"):
                installer._github_asset()

    def test_official_matching_release_requires_sha256(self):
        url = "https://github.com/OrcaSlicer/OrcaSlicer/releases/download/" + installer.TAG + "/" + installer.ASSET
        payload = ('{"assets":[{"name":"' + installer.ASSET +
                   '","digest":"sha256:' + "a" * 64 + '","browser_download_url":"' + url + '"}]}')
        response = Mock()
        response.status = 200
        response.headers = {}
        response.read.return_value = payload.encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch.object(installer, "urlopen", return_value=response):
            self.assertEqual(installer._github_asset(), (url, "a" * 64))

    def test_engine_asset_name_remains_pinned(self):
        self.assertEqual(installer.TAG, "v2.4.2")
        self.assertIn("Ubuntu2404", installer.ASSET)
        self.assertEqual(installer.VERSION, "2.4.2")


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
