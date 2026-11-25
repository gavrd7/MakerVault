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
        modified = [(item(x_mm=-35,process_overrides={"wall_loops":3}), cube()),
                    rows[1]]
        with self.assertRaisesRegex(SlicerProfileError, "advanced edits"):
            build_prusa_multitool_candidate(
                modified, printer_ini=printer_ini, tools=[1,2],
                bed_width=250, bed_depth=210)
