"""Prusa native MMU colour candidate uses the real application exporter.

Never infer approval for the authenticated worker from a valid research 3MF.
"""
import io
import struct
import zipfile
from unittest import TestCase
from defusedxml import ElementTree as SafeET

from core.slicer_prusa_colour_project import build_prusa_colour_candidate
from core.slicer_profiles import SlicerProfileError
from core.tests.test_slicer_prusa_machine_topology import ini
from scripts.prusa_generate_mmu_paint import fixture
from slicer_worker.prusa_material_validation import validate_prusa_material_candidate
from slicer_worker.runner import WorkerError

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

    def test_five_tool_prusa_leaf_states_are_verified_by_independent_worker(self):
        machine = ini("0.4,0.4,0.4,0.4,0.4", "1")
        for selected, state in ((1, "8"), (2, "0C"), (3, "1C"), (4, "2C")):
            with self.subTest(native_tool=selected):
                data = self.candidate(tool_map={1:selected})
                with zipfile.ZipFile(io.BytesIO(data)) as source:
                    model = source.read("3D/3dmodel.model")
                self.assertIn(('slic3rpe:mmu_segmentation="' + state + '"').encode(), model)
                receipt = validate_prusa_material_candidate(
                    data, printer_ini=machine, colour=True)
                self.assertEqual(receipt["tools"], (1, selected+1))
                self.assertGreater(receipt["colour_facets"], 0)

    def test_painted_tools_outside_native_printer_capacity_are_blocked(self):
        candidate = self.candidate(tool_map={1:4})
        for count in (2,3,4):
            with self.subTest(logical_count=count), self.assertRaises(WorkerError):
                validate_prusa_material_candidate(
                    candidate, printer_ini=ini(",".join(["0.4"]*count), "1"),
                    colour=True)

    def test_malformed_or_recursive_painted_leaf_states_fail_closed(self):
        data = self.candidate(tool_map={1:2})
        with zipfile.ZipFile(io.BytesIO(data)) as source:
            parts = {name:source.read(name) for name in source.namelist()}
        for invalid in (b'9', b'3C', b'8C', b'0c', b''):
            with self.subTest(state=invalid):
                altered = dict(parts)
                altered["3D/3dmodel.model"] = altered["3D/3dmodel.model"].replace(
                    b'slic3rpe:mmu_segmentation="0C"',
                    b'slic3rpe:mmu_segmentation="' + invalid + b'"')
                output = io.BytesIO()
                with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target:
                    for name, content in altered.items():
                        target.writestr(name, content)
                with self.assertRaises(WorkerError):
                    validate_prusa_material_candidate(
                        output.getvalue(),
                        printer_ini=ini("0.4,0.4,0.4,0.4,0.4", "1"), colour=True)

    def test_invalid_tool_mapping_and_mixed_features_refused(self):
        for mapping in ({1:5},{1:True},{True:1},{}, {1:0}, {1:-1}, {1:"2"}):
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
        # Change actual facet vertex geometry, not the unused STL normal.
        tampered = stl[:96] + struct.pack('<f', 4.0) + stl[100:]
        with self.assertRaises((SlicerProfileError,ValueError)):
            self.candidate(source=tampered)
