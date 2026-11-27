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
            # Orca, Creality and Bambu now participate in normal catalogue refresh.
            # In addition to the three existing engine providers, the
            # separately pinned Prusa runtime has one fixed release lookup.
            self.assertEqual(request.call_count, 4)

    def test_bambu_is_listed_normally_with_verified_upstream_digest(self):
        from io import BytesIO

        def github(url, **kwargs):
            if "bambulab/BambuStudio" in url:
                payload = {
                    "tag_name": "v" + installer.BAMBU_VERSION,
                    "draft": False, "prerelease": False,
                    "assets": [{
                        "name": installer.BAMBU_ASSET,
                        "size": 270000000,
                        "digest": "sha256:" + installer.BAMBU_APPIMAGE_SHA256,
                        "browser_download_url":
                            "https://github.com/bambulab/BambuStudio/releases/download/v"
                            + installer.BAMBU_VERSION + "/" + installer.BAMBU_ASSET,
                    }],
                }
                return BytesIO(json.dumps(payload).encode())
            return BytesIO(json.dumps(release()).encode())
        with patch.object(installer.platform, "machine", return_value="x86_64"), \
             patch.object(installer, "_request", side_effect=github):
            rows = installer.release_catalogue()
        bambu = [row for row in rows if row["engine"] == "bambustudio"]
        self.assertEqual(len(bambu), 1)
        self.assertEqual(bambu[0]["version"], installer.BAMBU_VERSION)
        self.assertEqual(bambu[0]["bundle_sha256"], installer.BAMBU_APPIMAGE_SHA256)
        self.assertEqual(bambu[0]["binary_sha256"], installer.BAMBU_RUNTIME_SHA256)
        self.assertIn("crealityprint", {row["engine"] for row in rows})
        installer.RELEASE_CACHE["items"] = []
        installer.RELEASE_CACHE["time"] = 0
        def altered(url, **kwargs):
            response = github(url, **kwargs)
            if "bambulab/BambuStudio" not in url:
                return response
            payload = json.loads(response.read())
            payload["assets"][0]["digest"] = "sha256:" + "0" * 64
            return BytesIO(json.dumps(payload).encode())
        with patch.object(installer.platform, "machine", return_value="x86_64"), \
             patch.object(installer, "_request", side_effect=altered):
            rows = installer.release_catalogue()
        self.assertNotIn("bambustudio", {row["engine"] for row in rows})
        self.assertIn("crealityprint", {row["engine"] for row in rows})

    def test_only_sha_verified_bundled_orca_250_is_offered_for_k2(self):
        from io import BytesIO
        from unittest.mock import patch as mock_patch

        def upstream(url, **kwargs):
            if url.endswith("/releases/tags/v2.4.2"):
                asset = "OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.2.AppImage"
                return BytesIO(json.dumps({
                    "tag_name": "v2.4.2", "draft": False, "prerelease": False,
                    "assets": [{
                        "name": asset,
                        "digest": "sha256:" + installer.APPROVED_ORCA["2.4.2"],
                        "size": 180000000,
                        "browser_download_url":
                            "https://github.com/OrcaSlicer/OrcaSlicer/releases/download/v2.4.2/" + asset,
                    }],
                }).encode())
            return BytesIO(json.dumps(release()).encode())

        with TemporaryDirectory() as tmp:
            image = Path(tmp) / "orcaslicer.AppImage"
            image.write_bytes(b"reviewed fixture")
            appdir = Path(tmp) / "squashfs-root"
            appdir.mkdir()
            (appdir / "AppRun").write_text("verified fixture runtime")
            with mock_patch.object(installer, "REVIEWED_ORCA_SOURCE", image), \
                 mock_patch.object(installer, "REVIEWED_ORCA_APPDIR", appdir), \
                 mock_patch.object(installer, "_sha256", return_value=installer.REVIEWED_ORCA_SHA256), \
                 mock_patch.object(installer.platform, "machine", return_value="x86_64"), \
                 mock_patch.object(installer, "_request", side_effect=upstream):
                releases = installer.release_catalogue()
            orca = {row["version"]: row for row in releases if row["engine"] == "orcaslicer"}
            self.assertEqual(set(orca), {"2.4.2", "2.5.0"})
            self.assertEqual(orca["2.5.0"]["bundle_sha256"], installer.EXPECTED_ORCA_SHA)
            self.assertEqual(orca["2.5.0"]["source"], "bundled-reviewed-image")
            self.assertIsNone(orca["2.5.0"]["bundle_url"])
            self.assertNotEqual(orca["2.5.0"]["bundle_sha256"],
                                "d13eb0a9cd618ed080ab6b82c64c0a60c4501aac91e88d5ac2c3b526fb141a7c")

    def test_missing_or_tampered_bundled_orca_never_falls_back_to_upstream(self):
        from io import BytesIO
        with TemporaryDirectory() as tmp:
            image = Path(tmp) / "orcaslicer.AppImage"
            image.write_bytes(b"invalid")
            appdir = Path(tmp) / "squashfs-root"
            appdir.mkdir()
            (appdir / "AppRun").write_text("fixture")
            for variant in ("bad-hash", "missing-appimage", "symlink"):
                with self.subTest(variant=variant):
                    installer.RELEASE_CACHE["items"] = []
                    image.unlink(missing_ok=True)
                    if variant == "bad-hash":
                        image.write_bytes(b"stock upstream")
                    elif variant == "symlink":
                        image.symlink_to(appdir / "AppRun")
                    def upstream(url, **kwargs):
                        if "/releases/tags/v2.4.2" in url:
                            return BytesIO(json.dumps({"assets": []}).encode())
                        return BytesIO(json.dumps(release()).encode())
                    with patch.object(installer, "REVIEWED_ORCA_SOURCE", image), \
                         patch.object(installer, "REVIEWED_ORCA_APPDIR", appdir), \
                         patch.object(installer.platform, "machine", return_value="x86_64"), \
                         patch.object(installer, "_request", side_effect=upstream):
                        choices = installer.release_catalogue()
                    self.assertFalse(any(row["engine"] == "orcaslicer"
                                         and row["version"] == "2.5.0" for row in choices))

    def test_bundled_orca_cannot_download_stock_250(self):
        from inspect import getsource
        source = getsource(installer._install)
        self.assertIn('release.get("bundle_sha256") != REVIEWED_ORCA_SHA256', source)
        self.assertIn('_sha256(REVIEWED_ORCA_SOURCE) != REVIEWED_ORCA_SHA256', source)
        self.assertIn('_sha256(image) != REVIEWED_ORCA_SHA256', source)
        self.assertIn('shutil.copyfile(REVIEWED_ORCA_SOURCE, image)', source)
        self.assertIn('if bundled_orca:', source)

    def test_existing_verified_bambu_runtime_is_repaired_without_store_write_access(self):
        import stat
        from slicer_worker.engine_registry import BAMBU_RUNTIME_SHA256, BAMBU_VERSION
        with TemporaryDirectory() as temp:
            store = Path(temp)
            root = store / "versions" / "bambustudio" / BAMBU_VERSION / "squashfs-root"
            inner = root / "bin" / "bambu-studio"
            inner.parent.mkdir(parents=True)
            inner.write_bytes(b"fixture verified binary")
            inner.chmod(0o700)
            (root / "AppRun").write_text("#!/bin/sh\n")
            resources = root / "resources" / "profiles"
            resources.mkdir(parents=True)
            resources.chmod(0o700)
            resource = resources / "BBL.json"
            resource.write_text("{}")
            resource.chmod(0o600)
            usr_share = root / "usr" / "share"
            usr_share.mkdir(parents=True)
            usr_share.chmod(0o700)
            (store / "active.json").write_text("{}")
            manifest = {"engines": {"bambustudio": {
                "version": BAMBU_VERSION, "binary": str(root / "AppRun"),
                "binary_sha256": BAMBU_RUNTIME_SHA256,
            }}}
            with patch.object(installer, "STORE", store), \
                 patch.object(installer, "_manifest", return_value=manifest), \
                 patch.object(installer, "_sha256", return_value=BAMBU_RUNTIME_SHA256):
                installer.repair_active_bambu_runtime_permissions()
            for directory in (root, resources, usr_share):
                mode = stat.S_IMODE(directory.stat().st_mode)
                self.assertEqual(mode & 0o055, 0o055)
                self.assertEqual(mode & 0o022, 0)
            self.assertEqual(stat.S_IMODE(resource.stat().st_mode) & 0o044, 0o044)
            self.assertEqual(stat.S_IMODE(resource.stat().st_mode) & 0o022, 0)
            self.assertEqual(stat.S_IMODE(inner.stat().st_mode) & 0o111, 0o111)

    def test_bambu_repair_refuses_unverified_runtime(self):
        from slicer_worker.engine_registry import BAMBU_RUNTIME_SHA256, BAMBU_VERSION
        with TemporaryDirectory() as temp:
            store = Path(temp)
            root = store / "versions" / "bambustudio" / BAMBU_VERSION / "squashfs-root"
            inner = root / "bin" / "bambu-studio"
            inner.parent.mkdir(parents=True)
            inner.write_text("not the pinned runtime")
            (root / "AppRun").write_text("fixture")
            (store / "active.json").write_text("{}")
            manifest = {"engines": {"bambustudio": {
                "version": BAMBU_VERSION, "binary": str(root / "AppRun"),
                "binary_sha256": BAMBU_RUNTIME_SHA256,
            }}}
            with patch.object(installer, "STORE", store), \
                 patch.object(installer, "_manifest", return_value=manifest):
                with self.assertLogs(installer.LOGGER, level="WARNING") as captured:
                    installer.repair_active_bambu_runtime_permissions()
                self.assertIn("Skipping Bambu runtime permissions repair",
                              "\\n".join(captured.output))
                # Never grant access or change the active manifest if its
                # runtime has not passed the pinned binary identity check.
                self.assertEqual((store / "active.json").read_text(), "{}")

    def test_published_version_directory_is_worker_traversable(self):
        # mkdtemp starts at 0700; worker UID 10001 must be able to
        # traverse a version published by installer UID 10002.
        from inspect import getsource
        source = getsource(installer._install)
        self.assertIn("stage.chmod(0o755)\n        os.rename(stage, target)", source)

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
