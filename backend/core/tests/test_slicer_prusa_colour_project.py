"""Prusa native MMU colour candidate uses the real application exporter.

Never infer approval for the authenticated worker from a valid research 3MF.
"""
import io
import zipfile
from unittest import TestCase
from defusedxml import ElementTree as SafeET

from core.slicer_prusa_colour_project import build_prusa_colour_candidate
from core.slicer_profiles import SlicerProfileError
from core.tests.test_slicer_prusa_machine_topology import ini
from scripts.prusa_generate_mmu_paint import fixture

NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"


class PrusaNativeColourProjectTests(TestCase):
    def candidate(self, *, settings=None, source=None, tool_map=None):
        stl, _painted, _states, paint = fixture(include_paint=True)
        row = {
            "asset_id": "synthetic-mm3-painted",
            "x_mm": 0, "y_mm": 0, "z_mm": 0,
            "rotation_deg": 0, "scale_percent": 100,
            "colour_paint": paint,
        }
        row.update(settings or {})
        return build_prusa_colour_candidate(
            row, source if source is not None else stl,
            printer_ini=ini("0.4,0.4,0.4,0.4,0.4", "1"),
            colour_tool_indices=tool_map if tool_map is not None else {1: 1},
            bed_width=250, bed_depth=210)

    def test_native_colour_structure_and_tool_selection(self):
        project = self.candidate()
        with zipfile.ZipFile(io.BytesIO(project)) as archive:
            self.assertEqual(len(archive.namelist()), len(set(archive.namelist())))
            xml = archive.read("3D/3dmodel.model")
            config = SafeET.fromstring(archive.read("Metadata/Slic3r_PE_model.config"))
        self.assertIn(b'xmlns:slic3rpe="http://schemas.slic3r.org/3mf/2017/06"', xml)
        self.assertIn(b'slic3rpe:mmu_segmentation="8"', xml)
        self.assertIn(b'name="slic3rpe:MmPaintingVersion"', xml)
        root = SafeET.fromstring(xml)
        metadata = root.findall(NS+"metadata")
        self.assertEqual(sum(x.get("name")=="slic3rpe:MmPaintingVersion"
                             for x in metadata),1)
        self.assertEqual(config.find("./object/volume/metadata[@key='extruder']").get("value"),"1")

    def test_invalid_tool_mapping_and_mixed_features_refused(self):
        for mapping in ({1:2},{1:True},{True:1},{}, {1:0}):
            with self.subTest(mapping=mapping):
                if mapping == {1:0}:
                    # A painting assignment to T0 cannot prove a second tool.
                    with self.assertRaises((SlicerProfileError,ValueError)):
                        self.candidate(tool_map=mapping)
                else:
                    with self.assertRaises((SlicerProfileError,ValueError)):
                        self.candidate(tool_map=mapping)
        for field,value in (("modifier_volumes",[{"id":"unsafe"}]),
                            ("process_overrides",{"wall_loops":3}),
                            ("support_paint",{"regions":[{"slot":0}]}),
                            ("material_slot",1)):
            with self.subTest(field=field),self.assertRaises(SlicerProfileError):
                self.candidate(settings={field:value})

    def test_source_fingerprint_must_match(self):
        stl, *_ = fixture()
        tampered = stl[:84] + bytes([stl[84]^1]) + stl[85:]
        with self.assertRaises((SlicerProfileError,ValueError)):
            self.candidate(source=tampered)
