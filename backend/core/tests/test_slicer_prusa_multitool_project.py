"""Bounded, research-only Prusa MMU/XL model assignments stay fail-closed."""
import io
import zipfile
from unittest import TestCase
from defusedxml import ElementTree as SafeET

from core.slicer_prusa_multitool_project import build_prusa_multitool_candidate
from core.tests.test_slicer_prusa_plate import cube, item
from core.slicer_profiles import SlicerProfileError
from slicer_worker.prusa_3mf_validation import validate_prusa_native_3mf
from slicer_worker.runner import WorkerError


def printer(n, changer):
    return ("printer_technology = FFF\n"
            "nozzle_diameter = "+",".join(["0.4"]*n)+"\n"
            "bed_shape = 0x0,250x0,250x210,0x210\n"
            "binary_gcode = 0\n"
            "single_extruder_multi_material = "+str(changer)+"\n").encode()


class PrusaMultiToolCandidateTests(TestCase):
    def test_native_tool_assignments_are_one_based_for_both_topologies(self):
        rows = [(item(x_mm=-35), cube()), (item(x_mm=35), cube())]
        for count, changer, expected in ((5, 1, "single_nozzle_changer"),
                                         (2, 0, "independent_tools")):
            with self.subTest(topology=expected):
                project, info = build_prusa_multitool_candidate(
                    rows, printer_ini=printer(count, changer), tools=[1,2],
                    bed_width=250, bed_depth=210)
                self.assertEqual(info["kind"], expected)
                with zipfile.ZipFile(io.BytesIO(project)) as z:
                    root = SafeET.fromstring(z.read(
                        "Metadata/Slic3r_PE_model.config"))
                self.assertEqual([
                    meta.get("value") for obj in root.findall("object")
                    for meta in obj.findall("metadata")
                    if meta.get("key") == "extruder"], ["1","2"])
                # This candidate is deliberately *not* admissible to the
                # normal authenticated single-material worker.
                with self.assertRaises(WorkerError):
                    validate_prusa_native_3mf(project)

    def test_rejects_implicit_material_mapping_and_unverified_combinations(self):
        rows = [(item(x_mm=-35), cube()), (item(x_mm=35), cube())]
        printer_ini = printer(2, 0)
        for tools in ([0,2], [1,3], [1,1], [True,2], [1]):
            with self.subTest(tools=tools), self.assertRaises(SlicerProfileError):
                build_prusa_multitool_candidate(
                    rows, printer_ini=printer_ini, tools=tools,
                    bed_width=250, bed_depth=210)
        # Research permits only the two verified Prusa native object keys.
        for advanced in (
                {"travel_speed": 123}, {"support_material":1},
                {"wall_loops":True}, {"sparse_infill_density":500}):
            modified = [(item(x_mm=-35,process_overrides=advanced), cube()),
                        rows[1]]
            with self.subTest(advanced=advanced), self.assertRaises(
                    (SlicerProfileError,ValueError)):
                build_prusa_multitool_candidate(
                    modified, printer_ini=printer_ini, tools=[1,2],
                    bed_width=250, bed_depth=210)

    def test_native_object_wall_and_infill_metadata_survives_mmu_tool_mapping(self):
        from slicer_worker.prusa_material_validation import validate_prusa_material_candidate
        for changer in (0,1):
            with self.subTest(changer=changer):
                rows = [
                    (item(x_mm=-35, process_overrides={
                        "wall_loops":1,"sparse_infill_density":15}), cube()),
                    (item(x_mm=35, process_overrides={
                        "wall_loops":5,"sparse_infill_density":35}), cube()),
                ]
                machine=printer(2,changer)
                project,_=build_prusa_multitool_candidate(
                    rows,printer_ini=machine,tools=[1,2],
                    bed_width=250,bed_depth=210)
                receipt=validate_prusa_material_candidate(
                    project,printer_ini=machine,tools=[1,2])
                self.assertEqual(receipt["objects"],2)
                with zipfile.ZipFile(io.BytesIO(project)) as z:
                    root=SafeET.fromstring(z.read("Metadata/Slic3r_PE_model.config"))
                metadata=[{node.get("key"):node.get("value")
                           for node in obj.findall("metadata")}
                          for obj in root.findall("object")]
                self.assertEqual([m["extruder"] for m in metadata],["1","2"])
                self.assertEqual([m["perimeters"] for m in metadata],["1","5"])
                self.assertEqual([m["fill_density"] for m in metadata],["15%","35%"])


    def test_xl_independent_heads_preserve_local_modifier_negative_and_layer_ranges(self):
        from core.tests.test_slicer_prusa_3mf import volume
        from slicer_worker.prusa_material_validation import validate_prusa_material_candidate
        modified = volume("modifier", {"sparse_infill_density": 80})
        modified.update(width_mm=3, depth_mm=3, height_mm=5,
                        x_mm=-35, y_mm=0, z_mm=4)
        cavity = volume("negative")
        cavity.update(width_mm=3, depth_mm=3, height_mm=5,
                      x_mm=35, y_mm=0, z_mm=4)
        rows = [
            (item(x_mm=-35, modifier_volumes=[modified],
                  variable_layer_profile={"version": 1, "bands": [
                      {"from_mm": 2, "to_mm": 6, "layer_mm": .12}]}), cube()),
            (item(x_mm=35, modifier_volumes=[cavity]), cube()),
        ]
        for count in (2, 5):
            with self.subTest(xl_heads=count):
                machine = printer(count, 0)
                project, topology = build_prusa_multitool_candidate(
                    rows, printer_ini=machine, tools=[1, count],
                    bed_width=250, bed_depth=210)
                self.assertEqual(topology["kind"], "independent_tools")
                receipt = validate_prusa_material_candidate(
                    project, printer_ini=machine, tools=[1, count])
                self.assertEqual(receipt["objects"], 2)
                self.assertEqual(receipt["tools"], (1, count))
                with zipfile.ZipFile(io.BytesIO(project)) as archive:
                    self.assertIn(
                        "Metadata/Prusa_Slicer_layer_config_ranges.xml",
                        archive.namelist())
                    root = SafeET.fromstring(
                        archive.read("Metadata/Slic3r_PE_model.config"))
                self.assertEqual(
                    [[node.get("value") for node in obj.findall("metadata")
                      if node.get("key") == "extruder"]
                     for obj in root.findall("object")],
                    [["1"], [str(count)]])
                self.assertEqual(
                    [len(obj.findall("volume")) for obj in root.findall("object")],
                    [2, 2])
                with self.assertRaises(WorkerError):
                    validate_prusa_native_3mf(project)

        # MMU and independent heads use the same upstream typed native
        # Object/Volume/layer-range project dialect. Its MMU-specific wipe
        # tower and material routing are checked separately by the worker.
        mmu_project, mmu_topology = build_prusa_multitool_candidate(
            rows, printer_ini=printer(5, 1), tools=[1, 5],
            bed_width=250, bed_depth=210)
        self.assertEqual(mmu_topology["kind"], "single_nozzle_changer")
        with zipfile.ZipFile(io.BytesIO(mmu_project)) as archive:
            self.assertIn("Metadata/Prusa_Slicer_layer_config_ranges.xml",
                          archive.namelist())
            obj = SafeET.fromstring(
                archive.read("Metadata/Slic3r_PE_model.config"))
        self.assertEqual([len(entry.findall("volume"))
                          for entry in obj.findall("object")], [2, 2])
        self.assertEqual([
            next(meta.get("value") for meta in entry.findall("metadata")
                 if meta.get("key") == "extruder")
            for entry in obj.findall("object")], ["1", "5"])

        from core.slicer_prusa_wipe_tower import add_prusa_native_wipe_tower
        mmu_tower = add_prusa_native_wipe_tower(
            mmu_project, x_mm=55, y_mm=150, rotation_deg=0,
            bed_width=250, bed_depth=210)
        receipt = validate_prusa_material_candidate(
            mmu_tower, printer_ini=printer(5, 1), tools=[1, 5],
            tower=(55, 150, 0, 250, 210))
        self.assertEqual(receipt["objects"], 2)
        self.assertEqual(receipt["tools"], (1, 5))
        self.assertTrue(receipt["wipe_tower"])


    def test_independent_native_object_shell_layers_reach_3mf_and_worker(self):
        from slicer_worker.prusa_material_validation import validate_prusa_material_candidate
        rows = [
            (item(x_mm=-35, process_overrides={
                "top_shell_layers": 0, "bottom_shell_layers": 1}), cube()),
            (item(x_mm=35, process_overrides={
                "top_shell_layers": 8, "bottom_shell_layers": 7}), cube()),
        ]
        for changer, count in ((1, 2), (0, 5), (0, 8)):
            with self.subTest(changer=changer, heads=count):
                raw = printer(count, changer)
                project, topology = build_prusa_multitool_candidate(
                    rows, printer_ini=raw, tools=[1, count],
                    bed_width=250, bed_depth=210)
                checked = validate_prusa_material_candidate(
                    project, printer_ini=raw, tools=[1, count])
                self.assertEqual(checked["tools"], (1, count))
                with zipfile.ZipFile(io.BytesIO(project)) as archive:
                    root = SafeET.fromstring(
                        archive.read("Metadata/Slic3r_PE_model.config"))
                self.assertEqual([
                    {m.get("key"): m.get("value") for m in obj.findall("metadata")}
                    for obj in root.findall("object")],
                    [{"top_solid_layers": "0", "bottom_solid_layers": "1",
                      "extruder": "1"},
                     {"top_solid_layers": "8", "bottom_solid_layers": "7",
                      "extruder": str(count)}])
        for value in (-1, 21, 1.5, True, "5"):
            with self.subTest(invalid_shell=value):
                bad = [(item(x_mm=-35, process_overrides={
                    "top_shell_layers": value}), cube()), rows[1]]
                with self.assertRaises((SlicerProfileError, ValueError)):
                    build_prusa_multitool_candidate(
                        bad, printer_ini=printer(5, 0), tools=[1, 2],
                        bed_width=250, bed_depth=210)
