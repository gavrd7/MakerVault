"""Offline tests for the isolated browser engine-installer service."""
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from slicer_worker import engine_installer_service as installer


def release():
    return [{
        "tag_name": "v7.3.1", "name": "Creality Print 7.3.1",
        "draft": False, "prerelease": False,
        "assets": [{
            "name": "CrealityPrint-V7.3.1.6378-x86_64-Release.AppImage",
            "size": 191511032, "digest": "sha256:" + "b" * 64,
            "browser_download_url":
                "https://github.com/CrealityOfficial/CrealityPrint/releases/"
                "download/v7.3.1/CrealityPrint-V7.3.1.6378-x86_64-Release.AppImage",
        }],
    }]


class InstallerTests(unittest.TestCase):
    def setUp(self):
        installer.RELEASE_CACHE["items"] = []
        installer.RELEASE_CACHE["time"] = 0

    def test_official_github_release_digest_is_required(self):
        with patch.object(installer.platform, "machine", return_value="x86_64"), \
             patch.object(installer, "_request",
                          return_value=io.BytesIO(json.dumps(release()).encode())):
            result = installer.release_catalogue()
        self.assertEqual(result[0]["engine"], "crealityprint")
        self.assertEqual(result[0]["version"], "7.3.1")
        self.assertEqual(result[0]["bundle_sha256"], "b" * 64)
        self.assertEqual(result[0]["architecture"], "linux/amd64")
        self.assertEqual(len(result), 1)

    def test_external_host_and_missing_digest_cannot_be_installed(self):
        invalid = release()
        invalid[0]["assets"][0]["browser_download_url"] = "https://evil.example/fake.AppImage"
        with patch.object(installer.platform, "machine", return_value="x86_64"), \
             patch.object(installer, "_request",
                          return_value=io.BytesIO(json.dumps(invalid).encode())):
            self.assertEqual(installer.release_catalogue(), [])
        invalid = release()
        invalid[0]["assets"][0]["digest"] = None
        with patch.object(installer, "_request",
                          return_value=io.BytesIO(json.dumps(invalid).encode())):
            self.assertEqual(installer.release_catalogue(), [])

    def test_catalogue_refresh_uses_cache_during_progress_polling(self):
        with patch.object(installer.platform, "machine", return_value="x86_64"), \
             patch.object(installer, "_request",
                          return_value=io.BytesIO(json.dumps(release()).encode())) as request:
            self.assertEqual(installer.release_catalogue(), installer.release_catalogue())
            self.assertEqual(request.call_count, 3)

    def test_orca_releases_are_only_offered_with_exact_pinned_sha(self):
        from io import BytesIO
        def upstream(url, **kwargs):
            if "/releases/tags/v2." in url:
                version = url.rsplit("v", 1)[-1]
                digest = installer.APPROVED_ORCA[version]
                asset = f"OrcaSlicer_Linux_AppImage_Ubuntu2404_V{version}.AppImage"
                release = {"tag_name": "v" + version, "draft": False,
                           "prerelease": False, "assets": [{
                               "name": asset, "digest": "sha256:" + digest,
                               "size": 180000000,
                               "browser_download_url":
                                   f"https://github.com/OrcaSlicer/OrcaSlicer/releases/download/v{version}/{asset}",
                           }]}
                return BytesIO(json.dumps(release).encode())
            return BytesIO(json.dumps([]).encode())
        with patch.object(installer.platform, "machine", return_value="x86_64"), \\
             patch.object(installer, "_request", side_effect=upstream):
            releases = installer.release_catalogue()
        self.assertEqual({x["version"] for x in releases if x["engine"] == "orcaslicer"},
                         {"2.4.2", "2.5.0"})
        installer.RELEASE_CACHE["items"] = []
        def altered(url, **kwargs):
            data = json.loads(upstream(url).read())
            if isinstance(data, dict):
                data["assets"][0]["digest"] = "sha256:" + "0" * 64
            return BytesIO(json.dumps(data).encode())
        with patch.object(installer.platform, "machine", return_value="x86_64"), \\
             patch.object(installer, "_request", side_effect=altered):
            self.assertEqual(installer.release_catalogue(), [])

    def test_creality_cli_probe_uses_explicit_cli_switch(self):
        # Upstream requires --cli to avoid launching the wxWidgets GUI.
        from inspect import getsource
        source = getsource(installer._install)
        self.assertIn('str(app_run), "--cli", "--help"', source)

    def test_arbitrary_download_urls_and_commands_not_accepted(self):
        with self.assertRaises(ValueError):
            installer.start_install("../crealityprint", "7.3.1", "b" * 64)
        with self.assertRaises(ValueError):
            installer.start_install("crealityprint", "../7.3.1", "b" * 64)
        with self.assertRaises(ValueError):
            installer.start_install("crealityprint", "7.3.1", "https://example.com/")

    def test_incomplete_status_journal_fails_safely_on_restart(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "operations.json"
            with patch.object(installer, "OPERATION_FILE", path):
                with installer.LOCK:
                    installer.OPERATIONS.clear()
                    installer.OPERATIONS["e8dd1df5-e218-4db5-a254-03c3642f2772"] = {
                        "id": "e8dd1df5-e218-4db5-a254-03c3642f2772",
                        "engine": "crealityprint", "version": "7.3.1",
                        "status": "downloading", "progress": 32, "message": "Downloading",
                    }
                    installer._persist_operations()
                    installer.OPERATIONS.clear()
                installer._restore_operations()
                with installer.LOCK:
                    self.assertEqual(next(iter(installer.OPERATIONS.values()))["status"], "failed")
                    installer.OPERATIONS.clear()


if __name__ == "__main__":
    unittest.main()
