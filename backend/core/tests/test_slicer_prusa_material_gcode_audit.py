from unittest import TestCase

from core.slicer_prusa_3mf import build_prusa_native_3mf
from core.slicer_prusa_material_project import add_prusa_native_model_tools
from core.tests.test_slicer_prusa_machine_topology import ini
from core.tests.test_slicer_prusa_plate import item,cube
from slicer_worker.prusa_material_gcode_audit import audit_prusa_material_model_gcode
from slicer_worker.runner import WorkerError


PRINTER=ini("0.4,0.4","1")


def project():
    source=build_prusa_native_3mf(
        [(item(x_mm=-35),cube()),(item(x_mm=35),cube())],
        bed_width=250,bed_depth=210)
    return add_prusa_native_model_tools(source,PRINTER,[1,2])["project"]


def toolpaths(*,swap=False,leak=False,include_tower=False):
    commands=["M83","T0"]
    commands.extend(["G1 X90 Y105 E0.03"]*32)
    if include_tower:
        commands.extend(["G1 X65 Y155 E0.03"]*32)
    if leak:
        commands.extend(["G1 X160 Y105 E0.03"]*8)
    commands.append("T1" if not swap else "T0")
    commands.extend(["G1 X160 Y105 E0.03"]*32)
    if include_tower:
        commands.extend(["G1 X65 Y155 E0.03"]*32)
    return ("\n".join(commands)+"\n").encode()


class PrusaNativeToolpathAuditTests(TestCase):
    def test_material_tools_follow_native_mesh_footprints(self):
        result=audit_prusa_material_model_gcode(
            toolpaths(),project(),printer_ini=PRINTER,tools=[1,2])
        self.assertEqual(result["correct_extrusion_moves"],[32,32])
        self.assertEqual(result["incorrect_extrusion_moves"],[0,0])

    def test_wrong_side_and_unselected_tools_are_rejected(self):
        for raw in (toolpaths(swap=True),toolpaths(leak=True),
                    toolpaths()+b"T4\nG1 X160 Y105 E.05\n"):
            with self.subTest(raw=raw[-32:]),self.assertRaises(WorkerError):
                audit_prusa_material_model_gcode(
                    raw,project(),printer_ini=PRINTER,tools=[1,2])

    def test_real_tower_audit_requires_both_materials_purging(self):
        from core.slicer_prusa_wipe_tower import add_prusa_native_wipe_tower
        source=add_prusa_native_wipe_tower(
            project(),x_mm=55,y_mm=150,rotation_deg=0,
            bed_width=250,bed_depth=210)
        result=audit_prusa_material_model_gcode(
            toolpaths(include_tower=True),source,printer_ini=PRINTER,
            tools=[1,2],tower=[55,150,0,250,210])
        self.assertEqual(result["tower_extrusion_moves"],{0:32,1:32})
        with self.assertRaises(WorkerError):
            audit_prusa_material_model_gcode(
                toolpaths(),source,printer_ini=PRINTER,
                tools=[1,2],tower=[55,150,0,250,210])

    def test_wrong_profile_assignment_is_rejected_before_gcode(self):
        with self.assertRaises(WorkerError):
            audit_prusa_material_model_gcode(
                toolpaths(),project(),printer_ini=ini("0.4"),tools=[1,2])
