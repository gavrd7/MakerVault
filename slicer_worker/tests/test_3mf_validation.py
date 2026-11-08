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
