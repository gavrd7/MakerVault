import io
import zipfile
from unittest import TestCase
from slicer_worker.runner import WorkerError
from slicer_worker.three_mf_validation import validate_worker_3mf, MAX_TRIANGLES


class Core3MFWorkerTests(TestCase):
    def package(self, *, malformed=False):
        ns = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
        content = (f'<model xmlns="{ns}" unit="millimeter">'
                   '<resources><object id="1" type="model"><mesh>'
                   '<vertices><vertex x="0" y="0" z="0"/>'
                   '<vertex x="1" y="0" z="0"/>'
                   '<vertex x="0" y="1" z="0"/></vertices>'
                   '<triangles><triangle v1="0" v2="1" v3="2"/></triangles>'
                   '</mesh></object></resources>'
                   '<build><item objectid="1" transform="1 0 0 0 1 0 0 0 1 10 10 0"/></build>'
                   '</model>').encode()
        if malformed:
            content = content.replace(b'objectid="1"', b'objectid="999"')
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("3D/3dmodel.model", content)
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("_rels/.rels", "<Relationships/>")
        return data.getvalue()


    def with_object_metadata(self, overrides):
        """Build two core objects and a single native plate mapping."""
        ns = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
        def mesh(index):
            return (f'<object id="{index}" type="model"><mesh><vertices>'
                    '<vertex x="0" y="0" z="0"/><vertex x="1" y="0" z="0"/>'
                    '<vertex x="0" y="1" z="0"/></vertices>'
                    '<triangles><triangle v1="0" v2="1" v3="2"/></triangles>'
                    '</mesh></object>')
        model = (f'<model xmlns="{ns}" unit="millimeter"><resources>'
                 + mesh(1) + mesh(2) + '</resources><build>'
                 '<item objectid="1" transform="1 0 0 0 1 0 0 0 1 10 10 0"/>'
                 '<item objectid="2" transform="1 0 0 0 1 0 0 0 1 40 40 0"/>'
                 '</build></model>')
        metadata = ''.join(f'<metadata key="{key}" value="{value}"/>' for key, value in overrides)
        manifest = ('<config><object id="2">' + metadata + '</object>'
                    '<plate><metadata key="plater_id" value="1"/>'
                    '<model_instance><metadata key="object_id" value="1"/>'
                    '<metadata key="instance_id" value="0"/>'
                    '<metadata key="identify_id" value="1"/></model_instance>'
                    '<model_instance><metadata key="object_id" value="2"/>'
                    '<metadata key="instance_id" value="0"/>'
                    '<metadata key="identify_id" value="2"/></model_instance>'
                    '</plate></config>')
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zipfile_out:
            zipfile_out.writestr("3D/3dmodel.model", model)
            zipfile_out.writestr("Metadata/model_settings.config", manifest)
            zipfile_out.writestr("[Content_Types].xml", "<Types/>")
            zipfile_out.writestr("_rels/.rels", "<Relationships/>")
        return out.getvalue()

    def test_safe_per_object_metadata_passes_worker_validation(self):
        self.assertTrue(validate_worker_3mf(self.with_object_metadata([
            ("wall_loops", "5"), ("sparse_infill_density", "37%"),
        ])))

    def test_unsafe_per_object_metadata_is_rejected(self):
        for overrides in (
            [("machine_start_gcode", "M104 S300")],
            [("wall_loops", "999")],
            [("wall_loops", "-2")],
            [("wall_loops", "3.5")],
            [("sparse_infill_density", "50")],
            [("sparse_infill_density", "NaN%")],
            [("wall_loops", "3"), ("wall_loops", "5")],
        ):
            with self.subTest(overrides=overrides), self.assertRaises(WorkerError):
                validate_worker_3mf(self.with_object_metadata(overrides))


    def test_native_extruder_metadata_requires_matching_explicit_palette(self):
        raw = self.with_object_metadata([("extruder", "2")])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            contents = {name: archive.read(name) for name in archive.namelist()}
        manifest = contents["Metadata/model_settings.config"]
        manifest = manifest.replace(
            b'<config><object id="2">',
            b'<config><object id="1"><metadata key="extruder" value="1"/></object><object id="2">',
        )
        contents["Metadata/model_settings.config"] = manifest
        def archive(data):
            out = io.BytesIO()
            with zipfile.ZipFile(out, "w") as package:
                for name, contents_ in data.items():
                    package.writestr(name, contents_)
            return out.getvalue()
        self.assertTrue(validate_worker_3mf(archive(contents), native_tool_count=2))
        with self.assertRaisesRegex(WorkerError, "Unsupported"):
            validate_worker_3mf(archive(contents))
        with self.assertRaises(WorkerError):
            validate_worker_3mf(archive(contents), native_tool_count=1)
        for invalid in (b"0", b"3", b"-1", b"1.5"):
            with self.subTest(invalid=invalid):
                changed = dict(contents)
                changed["Metadata/model_settings.config"] = manifest.replace(
                    b'key="extruder" value="2"',
                    b'key="extruder" value="' + invalid + b'"',
                )
                with self.assertRaises(WorkerError):
                    validate_worker_3mf(archive(changed), native_tool_count=2)
        changed = dict(contents)
        changed["Metadata/model_settings.config"] = manifest.replace(
            b'<object id="1"><metadata key="extruder" value="1"/></object>', b'',
        )
        with self.assertRaisesRegex(WorkerError, "Every native object"):
            validate_worker_3mf(archive(changed), native_tool_count=2)

    def test_valid_core_model_is_admitted(self):
        self.assertTrue(validate_worker_3mf(self.package()))

    def test_larger_than_old_150k_triangle_limit_is_accepted(self):
        # Regression: MakerVault's validated STL and build-plate builder both
        # support 500,000 faces; the worker must not reject at 150,000.
        self.assertEqual(MAX_TRIANGLES, 500_000)
        ns = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
        faces = '<triangle v1="0" v2="1" v3="2"/>' * 150001
        model = (f'<model xmlns="{ns}"><resources><object id="1" type="model"><mesh>'
                 '<vertices><vertex x="0" y="0" z="0"/>'
                 '<vertex x="1" y="0" z="0"/>'
                 '<vertex x="0" y="1" z="0"/></vertices>'
                 f'<triangles>{faces}</triangles></mesh></object></resources>'
                 '<build><item objectid="1" transform="1 0 0 0 1 0 0 0 1 10 10 0"/></build>'
                 '</model>')
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("3D/3dmodel.model", model)
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("_rels/.rels", "<Relationships/>")
        self.assertTrue(validate_worker_3mf(data.getvalue()))

    def test_unknown_object_is_rejected(self):
        with self.assertRaisesRegex(WorkerError, "unknown"):
            validate_worker_3mf(self.package(malformed=True))

    def test_arbitrary_extra_zip_member_is_rejected(self):
        data = io.BytesIO(self.package())
        with zipfile.ZipFile(data, "a") as archive:
            archive.writestr("../evil.sh", "malicious")
        with self.assertRaisesRegex(WorkerError, "members"):
            validate_worker_3mf(data.getvalue())

    def test_missing_and_malformed_archive_rejected(self):
        with self.assertRaises(WorkerError):
            validate_worker_3mf(b"not a zip")
