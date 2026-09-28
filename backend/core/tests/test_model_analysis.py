import shutil
import struct
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from core.model_analysis import analyse_3mf, analyse_stl
from core.models import Model3D, ModelRevision


def binary_stl_boxish():
    # Four triangles forming a tetrahedron with extents 10 x 20 x 30 mm.
    vertices = [
        ((0, 0, 0), (0, 20, 0), (10, 0, 0)),
        ((0, 0, 0), (10, 0, 0), (0, 0, 30)),
        ((0, 0, 0), (0, 0, 30), (0, 20, 0)),
        ((10, 0, 0), (0, 20, 0), (0, 0, 30)),
    ]
    data = bytearray(b"MakerVault test STL".ljust(80, b"\0"))
    data.extend(struct.pack("<I", len(vertices)))
    for triangle in vertices:
        values = [0.0, 0.0, 0.0]
        for point in triangle:
            values.extend(float(value) for value in point)
        data.extend(struct.pack("<12fH", *values, 0))
    return bytes(data)


def simple_3mf():
    model_xml = """<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
  <resources>
    <object id="1" type="model">
      <mesh>
        <vertices>
          <vertex x="0" y="0" z="0"/>
          <vertex x="15" y="0" z="0"/>
          <vertex x="0" y="25" z="0"/>
          <vertex x="0" y="0" z="35"/>
        </vertices>
        <triangles>
          <triangle v1="0" v2="2" v3="1"/>
          <triangle v1="0" v2="1" v3="3"/>
          <triangle v1="0" v2="3" v3="2"/>
          <triangle v1="1" v2="2" v3="3"/>
        </triangles>
      </mesh>
    </object>
  </resources>
  <build><item objectid="1"/></build>
</model>"""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("3D/3dmodel.model", model_xml)
    return buffer.getvalue()


class ModelGeometryAnalysisTests(TestCase):
    def test_binary_stl_analysis_reports_geometry(self):
        result = analyse_stl(binary_stl_boxish())
        self.assertEqual(result["format"], "stl")
        self.assertEqual(result["encoding"], "binary")
        self.assertEqual(result["triangle_count"], 4)
        self.assertEqual(result["vertex_count"], 4)
        self.assertEqual(result["dimensions_mm"], {"x": 10.0, "y": 20.0, "z": 30.0})
        self.assertEqual(result["complexity"], "low")
        self.assertGreater(result["surface_area_mm2"], 0)
        self.assertGreater(result["volume_mm3"], 0)
        self.assertIn("assumes millimetres", result["warnings"][0])

    def test_3mf_analysis_uses_declared_units_and_objects(self):
        result = analyse_3mf(simple_3mf())
        self.assertEqual(result["format"], "3mf")
        self.assertEqual(result["source_units"], "millimeter")
        self.assertEqual(result["object_count"], 1)
        self.assertEqual(result["triangle_count"], 4)
        self.assertEqual(result["vertex_count"], 4)
        self.assertEqual(result["dimensions_mm"], {"x": 15.0, "y": 25.0, "z": 35.0})
        self.assertGreater(result["volume_cm3"], 0)


class ModelAnalysisApiTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="makervault-model-intelligence-")
        self.override = override_settings(MEDIA_ROOT=Path(self.media_root))
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, True)

        self.user = get_user_model().objects.create_superuser(
            username="model-intelligence-admin",
            email="models@example.com",
            password="test-password",
        )
        self.client.force_login(self.user)

    def test_uploaded_stl_is_analysed_automatically_and_serialised(self):
        upload = SimpleUploadedFile(
            "tetrahedron.stl",
            binary_stl_boxish(),
            content_type="model/stl",
        )
        response = self.client.post(
            "/api/printing/models/",
            data={
                "name": "Analysed tetrahedron",
                "revision_version": "1.0",
                "file": upload,
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        revision = response.json()["item"]["revisions"][0]
        self.assertEqual(revision["analysis_status"], "ready")
        self.assertEqual(revision["geometry_analysis"]["format"], "stl")
        self.assertEqual(
            revision["geometry_analysis"]["dimensions_mm"],
            {"x": 10.0, "y": 20.0, "z": 30.0},
        )

        stored = ModelRevision.objects.get(pk=revision["id"])
        self.assertEqual(stored.geometry_metadata["analysis"]["triangle_count"], 4)
        self.assertTrue(stored.geometry_metadata["analysis"]["source_asset_id"])

    def test_existing_revision_can_be_reanalysed(self):
        upload = SimpleUploadedFile(
            "package.3mf",
            simple_3mf(),
            content_type="application/vnd.ms-package.3dmanufacturing-3dmodel+xml",
        )
        created = self.client.post(
            "/api/printing/models/",
            data={
                "name": "3MF analysis",
                "revision_version": "A",
                "file": upload,
            },
        )
        self.assertEqual(created.status_code, 201, created.content)
        model = Model3D.objects.get(name="3MF analysis")
        revision = model.revisions.get(version="A")
        revision.geometry_metadata = {}
        revision.save(update_fields=["geometry_metadata"])

        analysed = self.client.post(
            f"/api/printing/models/{model.id}/revisions/{revision.id}/analyse/",
            data={},
            content_type="application/json",
        )
        self.assertEqual(analysed.status_code, 200, analysed.content)
        self.assertEqual(analysed.json()["analysis"]["format"], "3mf")
        self.assertEqual(
            analysed.json()["analysis"]["dimensions_mm"],
            {"x": 15.0, "y": 25.0, "z": 35.0},
        )
