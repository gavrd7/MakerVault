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
        self.assertIn("bambustudio", SUPPORTED)
        # Recognised beta code is not permission to activate the unreviewed staged fixture.
        from slicer_worker.engine_registry import configured_engines
        with patch.dict("os.environ", {"SLICER_WORKER_ENABLED": "0"}, clear=True):
            self.assertNotIn("bambustudio", configured_engines())

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

    def test_real_bambu_probe_rejects_unverified_version_and_multimaterial(self):
        from slicer_worker.probe import run_probe
        from slicer_worker.runner import WorkerError
        common = dict(engine="bambustudio", version=staging.VERSION,
                      binary="/nonexistent", printer="/nonexistent",
                      filament="/nonexistent", process="/nonexistent")
        with self.assertRaisesRegex(WorkerError, "pinned"):
            run_probe(**{**common, "version": "02.08.01.55"})
        with self.assertRaisesRegex(WorkerError, "single STL or fixed 3MF"):
            run_probe(**{**common, "second_filament": "/nonexistent"})
        with self.assertRaisesRegex(WorkerError, "single STL"):
            run_probe(**{**common, "model": "/nonexistent.3mf"})

    def test_fixed_core_3mf_is_one_object_and_not_an_arbitrary_vendor_project(self):
        import io
        import zipfile
        from slicer_worker.probe import fixture_bambu_core_3mf, run_probe
        from slicer_worker.three_mf_validation import validate_worker_3mf
        from slicer_worker.runner import WorkerError
        package = fixture_bambu_core_3mf()
        self.assertTrue(validate_worker_3mf(package))
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            self.assertEqual(set(archive.namelist()),
                             {"3D/3dmodel.model", "_rels/.rels", "[Content_Types].xml"})
            self.assertIn(b'<item objectid="1"', archive.read("3D/3dmodel.model"))
        common = dict(engine="bambustudio", version=staging.VERSION,
                      binary="/nonexistent", printer="/nonexistent",
                      filament="/nonexistent", process="/nonexistent")
        with self.assertRaisesRegex(WorkerError, "no external model"):
            run_probe(**common, model="untrusted.3mf", bambu_core_3mf=True)
        with self.assertRaisesRegex(WorkerError, "only for Bambu"):
            run_probe(**{**common, "engine": "orcaslicer"}, bambu_core_3mf=True)
