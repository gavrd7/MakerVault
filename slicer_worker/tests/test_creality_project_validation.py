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
            z.writestr("3D/3dmodel.model",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
                'unit="millimeter"><metadata name="Application">'
                'Creality_Print V7.3.1</metadata><resources/><build/></model>')
            z.writestr("Metadata/model_settings.config",
                       '<config><object id="1"><metadata key="extruder" value="1"/>'
                       '<part id="1" subtype="normal_part">'
                       '<metadata key="name" value="Model 1"/>'
                       '<metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>'
                       '</part></object><object id="2">'
                       '<metadata key="extruder" value="2"/>'
                       '<part id="1" subtype="normal_part"/>'
                       '</object><plate><metadata key="plater_id" value="1"/>'
                       '<metadata key="locked" value="false"/>'
                       '<model_instance><metadata key="object_id" value="1"/>'
                       '<metadata key="instance_id" value="0"/>'
                       '<metadata key="identify_id" value="1"/></model_instance>'
                       '<model_instance><metadata key="object_id" value="2"/>'
                       '<metadata key="instance_id" value="0"/>'
                       '<metadata key="identify_id" value="2"/></model_instance>'
                       '</plate><assemble>'
                       '<assemble_item object_id="1" instance_id="0" '
                       'transform="1 0 0 0 1 0 0 0 1 0 0 0" offset="0 0 0"/>'
                       '<assemble_item object_id="2" instance_id="0" '
                       'transform="1 0 0 0 1 0 0 0 1 0 0 0" offset="0 0 0"/>'
                       '</assemble></config>')
            for name in ("_rels/.rels", "[Content_Types].xml"):
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

    @patch("slicer_worker.creality_project_validation.validate_worker_3mf",
           return_value=True)
    def test_missing_generator_version_fails_before_engine(self, validate):
        data = self.project()
        import io
        import zipfile
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(
                output, "w", compression=zipfile.ZIP_DEFLATED) as dest:
            for name in source.namelist():
                blob = source.read(name)
                if name == "3D/3dmodel.model":
                    blob = blob.replace(
                        b"Creality_Print V7.3.1", b"MakerVault")
                dest.writestr(name, blob)
        with self.assertRaisesRegex(WorkerError, "generator version"):
            validate_creality_project(output.getvalue())
        validate.assert_not_called()

    def test_missing_creality_identity_is_rejected(self):
        with self.assertRaises(WorkerError):
            validate_creality_project(self.project(identity=False))

    def test_post_processing_cannot_be_embedded_in_native_project(self):
        with self.assertRaisesRegex(WorkerError, "blocked settings"):
            validate_creality_project(
                self.project(project={"post_process": "unsafe"}))

    @patch("slicer_worker.creality_project_validation.validate_worker_3mf",
           return_value=True)
    def test_four_bay_palette_with_two_used_tools(self, validate):
        payload = self.project(project={
            "filament_settings_id": ["grey", "yellow", "grey", "yellow"],
            "filament_map": ["1", "1", "1", "1"],
            "flush_volumes_matrix": ["0"] * 16,
            "flush_volumes_vector": ["140"] * 8,
        })
        self.assertTrue(validate_creality_project(payload, native_tool_count=2))
        validate.assert_called_once()

    def test_inconsistent_native_palette_matrix_is_rejected(self):
        with self.assertRaisesRegex(WorkerError, "purge matrix"):
            validate_creality_project(self.project(project={
                "filament_settings_id": ["grey", "yellow", "grey", "yellow"],
                "flush_volumes_matrix": ["0"] * 4,
            }))

    def test_assembly_cannot_reposition_prepared_models(self):
        data = self.project()
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as inp, zipfile.ZipFile(out, "w") as dst:
            for name in inp.namelist():
                raw = inp.read(name)
                if name == "Metadata/model_settings.config":
                    raw = raw.replace(b'transform="1 0 0 0 1 0 0 0 1 0 0 0"',
                                      b'transform="1 0 0 0 1 0 0 0 1 15 0 0"')
                dst.writestr(name, raw)
        with self.assertRaisesRegex(WorkerError, "assembly would modify"):
            validate_creality_project(out.getvalue())

    def test_missing_tool_palette_is_rejected(self):
        with self.assertRaisesRegex(WorkerError, "palette"):
            validate_creality_project(
                self.project(project={"filament_settings_id": ["only one"]}))
