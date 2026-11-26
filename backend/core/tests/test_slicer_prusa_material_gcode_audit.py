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


def toolpaths(*,swap=False,leak=False,include_tower=False,stationary=0):
    commands=["M83","G90","T0","G0 X90 Y105"]
    commands.extend(["G1 X%.3f Y105 E0.03" % (90+(i+1)*.06)
                     for i in range(32)])
    if include_tower:
        commands.append("G0 X65 Y155")
        commands.extend(["G1 X%.3f Y155 E0.03" % (65+(i+1)*.06)
                         for i in range(32)])
    if leak:
        commands.append("G0 X160 Y105")
        commands.extend(["G1 X%.3f Y105 E0.03" % (160+(i+1)*.06)
                         for i in range(8)])
    commands.append("T1" if not swap else "T0")
    # INDX native toolchange scripts may prime the next head at the
    # previous head's location: E-only movements are not deposition.
    commands.extend(["G1 E0.03"]*stationary)
    commands.append("G0 X160 Y105")
    commands.extend(["G1 X%.3f Y105 E0.03" % (160+(i+1)*.06)
                     for i in range(32)])
    if include_tower:
        commands.append("G0 X65 Y155")
        commands.extend(["G1 X%.3f Y155 E0.03" % (65+(i+1)*.06)
                         for i in range(32)])
    return ("\n".join(commands)+"\n").encode()

class PrusaNativeToolpathAuditTests(TestCase):
    def test_material_tools_follow_native_mesh_footprints(self):
        result=audit_prusa_material_model_gcode(
            toolpaths(),project(),printer_ini=PRINTER,tools=[1,2])
        self.assertEqual(result["correct_extrusion_moves"],[32,32])
        self.assertEqual(result["incorrect_extrusion_moves"],[0,0])

    def test_indx_toolchange_e_only_recovery_never_counts_as_wrong_model(self):
        result=audit_prusa_material_model_gcode(
            toolpaths(stationary=79),project(),
            printer_ini=PRINTER,tools=[1,2])
        self.assertEqual(result["correct_extrusion_moves"],[32,32])
        self.assertEqual(result["incorrect_extrusion_moves"],[0,0])

    def test_relative_xy_and_e_require_actual_deposited_segments(self):
        rows=["M83","G90","T0","G0 X90 Y105","G91"]
        rows.extend(["G1 X.06 Y0 E0.03"]*32)
        rows.extend(["G90","T1","G0 X160 Y105","G91"])
        rows.extend(["G1 X.06 Y0 E0.03"]*32)
        result=audit_prusa_material_model_gcode(
            ("\n".join(rows)+"\n").encode(),project(),
            printer_ini=PRINTER,tools=[1,2])
        self.assertEqual(result["correct_extrusion_moves"],[32,32])

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

    def test_stationary_purge_at_tower_counts_but_not_at_model(self):
        from core.slicer_prusa_wipe_tower import add_prusa_native_wipe_tower
        source=add_prusa_native_wipe_tower(
            project(),x_mm=55,y_mm=150,rotation_deg=0,
            bed_width=250,bed_depth=210)
        lines=["M83","G90"]
        for tool,center in ((0,90),(1,160)):
            lines.extend(["T%d" % tool,"G0 X%.3f Y105" % center])
            lines.extend(["G1 X%.3f Y105 E0.03" % (center+.06*(i+1))
                          for i in range(32)])
            lines.extend(["G0 X65 Y155"]+["G1 E0.03"]*32)
        actual=("\n".join(lines)+"\n").encode()
        result=audit_prusa_material_model_gcode(
            actual,source,printer_ini=PRINTER,
            tools=[1,2],tower=[55,150,0,250,210])
        self.assertEqual(result["correct_extrusion_moves"],[32,32])
        self.assertEqual(result["incorrect_extrusion_moves"],[0,0])
        self.assertEqual(result["tower_extrusion_moves"],{0:32,1:32})

    def test_wrong_profile_assignment_is_rejected_before_gcode(self):
        with self.assertRaises(WorkerError):
            audit_prusa_material_model_gcode(
                toolpaths(),project(),printer_ini=ini("0.4"),tools=[1,2])
