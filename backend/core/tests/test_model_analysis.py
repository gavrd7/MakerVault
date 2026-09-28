import json
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
from core.models import FileAsset, Model3D, ModelRevision


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


def open_triangle_stl():
    return b"""solid open
facet normal 0 0 1
outer loop
vertex 0 0 0
vertex 20 0 0
vertex 0 20 0
endloop
endfacet
endsolid open
"""


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


def slicer_3mf():
    model_xml = """<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
  <metadata name="Application">OrcaSlicer 2.3.0</metadata>
  <resources>
    <object id="1" type="model">
      <mesh>
        <vertices>
          <vertex x="0" y="0" z="0"/>
          <vertex x="20" y="0" z="0"/>
          <vertex x="0" y="20" z="0"/>
          <vertex x="0" y="0" z="20"/>
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
    project_settings = {
        "layer_height": "0.20",
        "initial_layer_print_height": "0.28",
        "nozzle_diameter": ["0.4"],
        "sparse_infill_density": "15%",
        "sparse_infill_pattern": "gyroid",
        "wall_loops": "3",
        "top_shell_layers": "5",
        "bottom_shell_layers": "4",
        "enable_support": "1",
        "brim_type": "outer_only",
        "brim_width": "5",
        "printer_settings_id": "Creality K2 0.4 nozzle",
        "print_settings_id": "0.20mm Standard",
        "filament_settings_id": ["Generic PLA @K2"],
    }
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("3D/3dmodel.model", model_xml)
        project_settings["filament_colour"] = ["#00AEEF", "#FFFFFF"]
        project_settings["filament_type"] = ["PLA", "PLA"]
        archive.writestr("Metadata/project_settings.config", json.dumps(project_settings))
        archive.writestr(
            "Metadata/model_settings.config",
            """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <object id="1"><metadata key="name" value="Brake body"/><metadata key="extruder" value="1"/></object>
  <object id="2"><metadata key="name" value="Brake legend"/><metadata key="extruder" value="2"/></object>
  <plate>
    <metadata key="plater_id" value="1"/>
    <metadata key="plater_name" value="Body"/>
    <model_instance><metadata key="object_id" value="1"/><metadata key="instance_id" value="0"/></model_instance>
  </plate>
  <plate>
    <metadata key="plater_id" value="2"/>
    <metadata key="plater_name" value="Legend"/>
    <model_instance><metadata key="object_id" value="2"/><metadata key="instance_id" value="0"/></model_instance>
  </plate>
</config>""",
        )
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
        self.assertEqual(result["analysis_version"], 2)
        self.assertTrue(result["mesh_quality"]["watertight"])
        self.assertEqual(result["mesh_quality"]["boundary_edges"], 0)
        self.assertEqual(result["mesh_quality"]["non_manifold_edges"], 0)
        self.assertEqual(len(result["orientation"]["candidates"]), 6)
        self.assertIn(result["orientation"]["recommended"]["key"], {"x+", "x-", "y+", "y-", "z+", "z-"})
        self.assertGreaterEqual(result["orientation"]["recommended"]["support_risk_pct"], 0)
        self.assertLessEqual(result["orientation"]["recommended"]["support_risk_pct"], 100)
        self.assertIn("assumes millimetres", result["warnings"][0])

    def test_open_mesh_reports_boundary_edges_and_orientation_estimate(self):
        result = analyse_stl(open_triangle_stl())
        self.assertFalse(result["mesh_quality"]["watertight"])
        self.assertEqual(result["mesh_quality"]["status"], "open")
        self.assertEqual(result["mesh_quality"]["boundary_edges"], 3)
        self.assertEqual(result["mesh_quality"]["non_manifold_edges"], 0)
        self.assertEqual(len(result["orientation"]["candidates"]), 6)
        self.assertTrue(any("boundary edge" in warning for warning in result["warnings"]))

    def test_3mf_extracts_slicer_profiles_and_settings(self):
        result = analyse_3mf(slicer_3mf())
        self.assertEqual(result["analysis_version"], 4)
        slicer = result["slicer_metadata"]
        self.assertTrue(slicer["detected"])
        self.assertEqual(slicer["application"], "OrcaSlicer")
        self.assertEqual(slicer["profiles"]["printer"], "Creality K2 0.4 nozzle")
        self.assertEqual(slicer["profiles"]["print"], "0.20mm Standard")
        self.assertEqual(slicer["profiles"]["filament"], ["Generic PLA @K2"])
        self.assertEqual(slicer["settings"]["layer_height_mm"], 0.2)
        self.assertEqual(slicer["settings"]["first_layer_height_mm"], 0.28)
        self.assertEqual(slicer["settings"]["nozzle_diameter_mm"], 0.4)
        self.assertEqual(slicer["settings"]["infill_density"], "15%")
        self.assertEqual(slicer["settings"]["infill_pattern"], "gyroid")
        self.assertEqual(slicer["settings"]["perimeters"], 3.0)
        self.assertEqual(slicer["settings"]["supports_enabled"], True)
        self.assertEqual(slicer["settings"]["brim_type"], "outer_only")
        self.assertIn("Metadata/project_settings.config", slicer["metadata_files"])

    def test_3mf_extracts_multi_plate_project_structure(self):
        result = analyse_3mf(slicer_3mf())
        project = result["project_structure"]
        self.assertTrue(project["detected"])
        self.assertTrue(project["multi_plate"])
        self.assertTrue(project["multicolour"])
        self.assertEqual(project["plate_count"], 2)
        self.assertEqual(project["object_count"], 2)
        self.assertEqual(project["used_material_slots"], [1, 2])
        self.assertEqual(project["plates"][0]["name"], "Body")
        self.assertEqual(project["plates"][0]["object_count"], 1)
        self.assertEqual(project["plates"][0]["material_slots"], [1])
        self.assertEqual(project["plates"][1]["material_slots"], [2])
        self.assertEqual(project["materials"][0]["colour"], "#00AEEF")
        self.assertEqual(project["materials"][0]["profile"], "Generic PLA @K2")

    def test_3mf_analysis_uses_declared_units_and_objects(self):
        result = analyse_3mf(simple_3mf())
        self.assertEqual(result["format"], "3mf")
        self.assertEqual(result["source_units"], "millimeter")
        self.assertEqual(result["object_count"], 1)
        self.assertEqual(result["triangle_count"], 4)
        self.assertEqual(result["vertex_count"], 4)
        self.assertEqual(result["dimensions_mm"], {"x": 15.0, "y": 25.0, "z": 35.0})
        self.assertGreater(result["volume_cm3"], 0)
        self.assertTrue(result["mesh_quality"]["watertight"])
        self.assertEqual(len(result["orientation"]["candidates"]), 6)


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

    def test_model_manager_can_upload_new_immutable_revision(self):
        created = self.client.post(
            "/api/printing/models/",
            data={
                "name": "Versioned enclosure",
                "revision_version": "1.0",
                "file": SimpleUploadedFile("enclosure-v1.stl", binary_stl_boxish(), content_type="model/stl"),
            },
        )
        self.assertEqual(created.status_code, 201, created.content)
        model = Model3D.objects.get(name="Versioned enclosure")
        first_revision = model.revisions.get(version="1.0")
        first_asset = first_revision.assets.get(is_primary=True).file_asset
        first_stored_name = first_asset.file.name

        updated = self.client.post(
            f"/api/printing/models/{model.id}/revisions/upload/",
            data={
                "version": "1.1",
                "notes": "Updated mounting tabs",
                "file": SimpleUploadedFile("enclosure-v1.1.stl", binary_stl_boxish(), content_type="model/stl"),
            },
        )
        self.assertEqual(updated.status_code, 201, updated.content)

        model.refresh_from_db()
        self.assertEqual(model.revisions.count(), 2)
        second_revision = model.revisions.get(version="1.1")
        second_asset = second_revision.assets.get(is_primary=True).file_asset
        self.assertEqual(second_asset.supersedes_id, first_asset.id)
        self.assertEqual(second_asset.version, "1.1")
        self.assertTrue(first_asset.file.storage.exists(first_stored_name))
        self.assertTrue(second_asset.file.storage.exists(second_asset.file.name))
        self.assertEqual(second_revision.geometry_metadata["analysis_status"], "ready")

        library = self.client.get("/api/files/")
        self.assertEqual(library.status_code, 200)
        self.assertEqual([row["id"] for row in library.json()["rows"]], [str(second_asset.id)])
        self.assertEqual(FileAsset.objects.count(), 2)

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
