"""Cross-engine geometry admission must not depend on identical source meshes.

These are preparation and worker-contract tests, not substitutes for native
binary slicing and placement verification on real printer profiles.
"""
import io
import zipfile
from defusedxml import ElementTree as ET
from django.test import SimpleTestCase

from core.tests.test_slicer_prusa_plate import cube, item
from core.slicer_mesh import inspect_stl
from core.slicer_creality_plate import build_creality_single_filament_plate
from core.slicer_prusa_plate import build_prusa_placed_stl
from core.slicer_plate_3mf import build_plate_3mf, NS
from core.slicer_streamed_plate_3mf import build_streamed_compound_3mf
from slicer_worker.three_mf_validation import validate_worker_3mf


def distinct_twenty():
    models = []
    for i in range(20):
        models.append((item(
            x_mm=-80+(i%5)*40,
            y_mm=-60+(i//5)*40,
            rotation_deg=(i % 4) * 15,
        ), cube(size=8+i/4)))
    return models


class CrossEngineFullPlatePreparationTests(SimpleTestCase):
    def test_twenty_distinct_sources_are_not_a_repeat_only_special_case(self):
        sources = distinct_twenty()
        self.assertEqual(len(sources), 20)
        self.assertEqual(len({raw for _, raw in sources}), 20)

    def test_creality_and_prusa_share_resource_aware_placed_stl_geometry(self):
        models = distinct_twenty()
        creality = build_creality_single_filament_plate(
            models, bed_width=260, bed_depth=260)
        prusa = build_prusa_placed_stl(
            models, bed_width=260, bed_depth=260)
        self.assertEqual(inspect_stl(creality)["triangles"], 20*12)
        self.assertEqual(inspect_stl(prusa)["triangles"], 20*12)
        self.assertEqual(creality, prusa)

    def test_standard_3mf_supports_distinct_multi_instance_bambu_geometry(self):
        source = build_plate_3mf(distinct_twenty(), bed_width=260, bed_depth=260)
        self.assertTrue(validate_worker_3mf(source))
        with zipfile.ZipFile(io.BytesIO(source)) as archive:
            root = ET.fromstring(archive.read("3D/3dmodel.model"))
        q = "{"+NS+"}"
        self.assertEqual(len(root.findall("./"+q+"resources/"+q+"object")),20)
        self.assertEqual(len(root.findall("./"+q+"build/"+q+"item")),20)

    def test_orca_streamed_3mf_keeps_all_twenty_distinct_model_shells(self):
        data = build_streamed_compound_3mf(
            distinct_twenty(), bed_width=260, bed_depth=260)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            root = ET.fromstring(archive.read("3D/3dmodel.model"))
        q = "{"+NS+"}"
        self.assertEqual(len(root.findall("./"+q+"resources/"+q+"object")),1)
        self.assertEqual(len(root.findall("./"+q+"build/"+q+"item")),1)
        self.assertEqual(len(root.findall(".//"+q+"triangle")),20*12)
