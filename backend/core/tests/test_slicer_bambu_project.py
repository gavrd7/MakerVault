"""Pure Bambu 3MF native project-vector builder tests (no Django/database/network)."""
import io
import json
import zipfile
from unittest import TestCase
from xml.etree import ElementTree as ET

from scripts.probe_bambu_multicolour import make_bambu_material_fixture
from slicer_worker.three_mf_validation import validate_worker_3mf
from slicer_worker.runner import WorkerError

# Backend has Django dependencies; these tests run inside the backend suite.
from core.slicer_bambu_project import (
    add_bambu_project_settings, selected_bambu_tool_colours,
    apply_bambu_prime_tower_position,
)
from core.slicer_profiles import SlicerProfileError


class BambuNativeProjectVectorTests(TestCase):
    printer = b'{"type":"machine","name":"Bambu Lab X1 Carbon 0.4 nozzle","nozzle_diameter":["0.4"],"printable_height":["256"]}'
    process = b'{"type":"process","name":"0.20mm Standard @BBL X1C"}'
    filament = b'{"type":"filament","name":"Bambu PLA Basic @BBL X1C","filament_diameter":["1.75"],"filament_type":["PLA"],"filament_id":"GFA00","filament_extruder_variant":["Direct Drive Standard","Direct Drive High Flow"],"filament_flow_ratio":["0.98","0.98"],"nozzle_temperature":["220","220"],"nozzle_temperature_initial_layer":["220","220"],"filament_max_volumetric_speed":["21","29"],"filament_retraction_length":["nil","0.4"]}'

    def _base_project(self):
        original = make_bambu_material_fixture()
        with zipfile.ZipFile(io.BytesIO(original)) as zf:
            with io.BytesIO() as dest:
                with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as out:
                    for member in zf.namelist():
                        if member != "Metadata/project_settings.config":
                            out.writestr(member, zf.read(member))
                return dest.getvalue()

    def test_adds_exact_native_vectors_without_changing_model_or_tool_assignments(self):
        source = self._base_project()
        result = add_bambu_project_settings(
            source, printer=self.printer, process=self.process,
            filaments=[self.filament, self.filament],
            tool_colours=("#FF0000", "#0000FF"))
        self.assertTrue(validate_worker_3mf(result, native_tool_count=2,
                                            allow_bambu_project=True))
        with zipfile.ZipFile(io.BytesIO(source)) as original, \
             zipfile.ZipFile(io.BytesIO(result)) as modified:
            self.assertEqual(original.read("3D/3dmodel.model"),
                             modified.read("3D/3dmodel.model"))
            self.assertEqual(original.read("Metadata/model_settings.config"),
                             modified.read("Metadata/model_settings.config"))
            ids = json.loads(modified.read("Metadata/project_settings.config"))
        self.assertEqual(ids["filament_settings_id"],
                         ["Bambu PLA Basic @BBL X1C"] * 2)
        self.assertEqual(ids["filament_colour"], ["#FF0000", "#0000FF"])
        self.assertEqual(ids["nozzle_diameter"], ["0.4"])
        self.assertEqual(ids["printable_height"], "256")
        self.assertEqual(ids["filament_ids"], ["GFA00", "GFA00"])
        self.assertEqual(ids["filament_is_support"], ["0", "0"])
        self.assertEqual(ids["filament_flow_ratio"], ["0.98"] * 4)
        self.assertEqual(ids["nozzle_temperature"], ["220"] * 4)
        self.assertEqual(ids["filament_max_volumetric_speed"],
                         ["21", "29", "21", "29"])
        self.assertEqual(ids["filament_retraction_length"],
                         ["nil", "0.4", "nil", "0.4"])
        self.assertEqual(ids["filament_self_index"], ["1", "1", "2", "2"])
        self.assertEqual(ids["filament_extruder_variant"],
                         ["Direct Drive Standard", "Direct Drive High Flow"] * 2)

    def test_rejects_incomplete_profiles_and_colour_conflicts(self):
        project = self._base_project()
        with self.assertRaises(SlicerProfileError):
            add_bambu_project_settings(project, printer=self.printer,
                                       process=self.process, filaments=[self.filament],
                                       tool_colours=["#FF0000"])
        with self.assertRaises(SlicerProfileError):
            add_bambu_project_settings(project, printer=self.printer,
                                       process=self.process, filaments=[self.filament]*2,
                                       tool_colours=["#FF0000","invalid"])
        with self.assertRaises(SlicerProfileError):
            add_bambu_project_settings(project, printer=b'{"name":"invalid"}',
                                       process=self.process, filaments=[self.filament]*2,
                                       tool_colours=["#FF0000","#0000FF"])

    def test_prime_tower_position_uses_same_bounded_native_process_keys(self):
        result = json.loads(apply_bambu_prime_tower_position(
            self.process, {"x": 43, "y": 51.5},
            bed_width=256, bed_depth=256))
        self.assertEqual(result["wipe_tower_x"], ["43"])
        self.assertEqual(result["wipe_tower_y"], ["51.5"])
        with self.assertRaises(SlicerProfileError):
            apply_bambu_prime_tower_position(
                self.process, {"x": 250, "y": 50},
                bed_width=256, bed_depth=256)
        with self.assertRaises(SlicerProfileError):
            apply_bambu_prime_tower_position(
                self.process, {"x": True, "y": 50},
                bed_width=256, bed_depth=256)

    def test_selected_colour_tools_use_explicit_material_slot_not_bay_index(self):
        models = [
            {"material_slot":{"slot_id":"a","slot_index":7}, "color":"#FF0000"},
            {"material_slot":{"slot_id":"b","slot_index":0}, "color":"#0000FF"},
        ]
        self.assertEqual(selected_bambu_tool_colours(models, {"a":0,"b":1}, 2),
                         ("#FF0000","#0000FF"))
        with self.assertRaises(SlicerProfileError):
            selected_bambu_tool_colours(models, {"a":0,"b":0}, 2)
