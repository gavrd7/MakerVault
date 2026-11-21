"""Offline tests for pinned Bambu candidate acquisition (no network calls)."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

from scripts import prepare_bambu_staging as staging
from slicer_worker.engine_registry import SUPPORTED
from slicer_worker.stage_engines import stage_engines


class BambuStagingTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_release_metadata_checks_exact_asset_digest_and_size(self):
        asset = {
            "name": staging.ASSET,
            "browser_download_url": staging.ASSET_URL,
            "digest": "sha256:" + staging.SHA256,
            "size": 255000000,
        }
        response = MagicMock()
        response.status = 200
        response.geturl.return_value = staging.API_URL
        response.read.return_value = json.dumps({"assets": [asset]}).encode("utf-8")
        response.__enter__.return_value = response
        with patch.object(staging, "urlopen", return_value=response):
            self.assertEqual(staging.official_asset(), staging.ASSET_URL)
            asset["digest"] = "sha256:" + "0" * 64
            response.read.return_value = json.dumps({"assets": [asset]}).encode("utf-8")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                staging.official_asset()

    def test_bambu_appimage_can_be_staged_without_enabling_engine(self):
        asset = self.root / "BambuStudio_fixture.AppImage"
        asset.write_bytes(b"\\x7fELF test-only Bambu asset")
        sha = hashlib.sha256(asset.read_bytes()).hexdigest()
        result = stage_engines(
            [("bambustudio", staging.VERSION, str(asset), sha)],
            self.root / "stage",
        )
        self.assertEqual(result["status"], "staged_not_tested")
        self.assertTrue((self.root / "stage" / "bambustudio.AppImage").exists())
        self.assertEqual(
            json.loads((self.root / "stage" / "manifest.json").read_text())["fixture_approved"], False)
        self.assertNotIn("bambustudio", SUPPORTED)

    def test_staging_existing_engine_assets_is_refused(self):
        target = self.root / "slicer-engine-assets"
        target.mkdir()
        (target / "orcaslicer.AppImage").write_bytes(b"existing-orca")
        with self.assertRaisesRegex(ValueError, "existing"):
            staging.fetch_candidate(target)
        self.assertEqual((target / "orcaslicer.AppImage").read_bytes(), b"existing-orca")

    def test_symlinked_destination_is_refused(self):
        target = self.root / "stage"
        target.mkdir()
        link = self.root / "link"
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlinked"):
            staging.fetch_candidate(link)
