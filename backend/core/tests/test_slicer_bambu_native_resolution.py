"""No-I/O unit tests for Bambu native owned-profile flattening."""
import json
from django.test import SimpleTestCase

from core.slicer_bambu_native_resolution import flatten_bambu_preset
from core.slicer_profiles import SlicerProfileError


class BambuNativeResolutionTests(SimpleTestCase):
    def setUp(self):
        self.machine = "Bambu Lab X1 Carbon 0.4 nozzle"
        self.docs = {
            self.machine: {
                "type": "machine", "name": self.machine,
                "instantiation": "true",
                "inherits": "fdm_bbl_common",
                "include": ["X1_start_gcode", "X1_end_gcode"],
                "nozzle_diameter": ["0.4"],
            },
            "fdm_bbl_common": {
                "type": "machine", "name": "fdm_bbl_common",
                "instantiation": "false", "gcode_flavor": "bbl",
            },
            "X1_start_gcode": {
                "name": "X1_start_gcode", "instantiation": "false",
                "machine_start_gcode": "G28",
            },
            "X1_end_gcode": {
                "name": "X1_end_gcode", "instantiation": "false",
                "machine_end_gcode": "M400",
            },
            "0.20mm Standard @BBL X1C": {
                "type": "process", "name": "0.20mm Standard @BBL X1C",
                "instantiation": "true", "layer_height": "0.2",
            },
            "Bambu PLA Basic @BBL X1C": {
                "type": "filament", "name": "Bambu PLA Basic @BBL X1C",
                "instantiation": "true", "filament_type": ["PLA"],
            },
        }

    def fetch(self, name):
        return json.dumps(self.docs[name], separators=(",", ":")).encode()

    def test_machine_includes_and_inheritance_resolve_without_leaking_template_identity(self):
        obj = json.loads(flatten_bambu_preset(self.machine, "printer", self.fetch))
        self.assertEqual(obj["name"], self.machine)
        self.assertEqual(obj["type"], "machine")
        self.assertEqual(obj["machine_start_gcode"], "G28")
        self.assertEqual(obj["machine_end_gcode"], "M400")
        self.assertEqual(obj["gcode_flavor"], "bbl")
        self.assertNotIn("inherits", obj)
        self.assertNotIn("include", obj)

    def test_process_and_filament_are_separate_native_families(self):
        process = json.loads(flatten_bambu_preset("0.20mm Standard @BBL X1C", "process", self.fetch))
        filament = json.loads(flatten_bambu_preset("Bambu PLA Basic @BBL X1C", "filament", self.fetch))
        self.assertEqual(process["layer_height"], "0.2")
        self.assertEqual(filament["filament_type"], ["PLA"])

    def test_missing_and_cyclic_dependency_fail_closed(self):
        def absent(name):
            if name == "fdm_bbl_common":
                raise SlicerProfileError("Pinned parent absent.")
            return self.fetch(name)
        with self.assertRaisesRegex(SlicerProfileError, "absent"):
            flatten_bambu_preset(self.machine, "printer", absent)
        self.docs["fdm_bbl_common"]["inherits"] = self.machine
        with self.assertRaisesRegex(SlicerProfileError, "cycle"):
            flatten_bambu_preset(self.machine, "printer", self.fetch)

    def test_cannot_recast_typeless_template_as_full_preset(self):
        with self.assertRaisesRegex(SlicerProfileError, "type"):
            flatten_bambu_preset("X1_start_gcode", "printer", self.fetch)
        self.docs["fdm_bbl_common"]["inherits"] = "X1_start_gcode"
        with self.assertRaisesRegex(SlicerProfileError, "type"):
            flatten_bambu_preset(self.machine, "printer", self.fetch)

    def test_wrong_family_or_scripts_are_rejected(self):
        self.docs["fdm_bbl_common"]["type"] = "filament"
        with self.assertRaisesRegex(SlicerProfileError, "type"):
            flatten_bambu_preset(self.machine, "printer", self.fetch)
        self.docs["fdm_bbl_common"]["type"] = "machine"
        self.docs[self.machine]["post_processing_scripts"] = "curl http://localhost"
        with self.assertRaisesRegex(SlicerProfileError, "Post-processing"):
            flatten_bambu_preset(self.machine, "printer", self.fetch)

    def test_parent_is_not_trusted_outside_bounded_import(self):
        self.docs[self.machine]["inherits"] = "../outside"
        def indexed(name):
            if name == "../outside":
                raise SlicerProfileError("Pinned parent outside reviewed vendor index.")
            return self.fetch(name)
        with self.assertRaisesRegex(SlicerProfileError, "outside"):
            flatten_bambu_preset(self.machine, "printer", indexed)
