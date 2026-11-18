"""Creality 7.3.1 3MF project transport contract tests."""
import io
import json
import zipfile
from unittest import TestCase
from unittest.mock import patch

from slicer_worker.creality_project_validation import validate_creality_project
from slicer_worker.runner import WorkerError


class NativeCreality3MFContractTests(TestCase):
    def project(self, *, project=None, identity=True):
        config = {"name": "project_settings", "from": "project",
                  "version": "7.3.1",
                  "filament_settings_id": ["grey", "yellow"]}
        config.update(project or {})
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for name in ("3D/3dmodel.model", "Metadata/model_settings.config",
                         "_rels/.rels", "[Content_Types].xml"):
                z.writestr(name, b"bounded structural fixture")
            if identity:
                z.writestr("Metadata/creality.config",
                           '<config><metadata key="Application" value="Creality_Print"/>'
                           '<metadata key="AppVersion" value="7.3.1"/></config>')
            z.writestr("Metadata/project_settings.config", json.dumps(config))
        return data.getvalue()

    @patch("slicer_worker.creality_project_validation.validate_worker_3mf",
           return_value=True)
    def test_native_project_has_embedded_profiles_and_original_plate(self, validate):
        self.assertTrue(validate_creality_project(self.project(), native_tool_count=2))
        validate.assert_called_once()
        self.assertEqual(validate.call_args.kwargs["native_tool_count"], 2)

    def test_missing_creality_identity_is_rejected(self):
        with self.assertRaises(WorkerError):
            validate_creality_project(self.project(identity=False))

    def test_post_processing_cannot_be_embedded_in_native_project(self):
        with self.assertRaisesRegex(WorkerError, "blocked settings"):
            validate_creality_project(
                self.project(project={"post_process": "unsafe"}))

    def test_missing_tool_palette_is_rejected(self):
        with self.assertRaisesRegex(WorkerError, "palette"):
            validate_creality_project(
                self.project(project={"filament_settings_id": ["only one"]}))
