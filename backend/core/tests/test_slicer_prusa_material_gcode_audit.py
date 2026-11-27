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

    def test_native_first_layer_skirt_brim_does_not_impersonate_neighbour_model(self):
        native=toolpaths().replace(
            b"T0\nG0 X90 Y105\n",
            b"T0\nG0 Z0.2\n;TYPE:Skirt/Brim\n"
            b"G0 X160 Y105\nG1 X160.1 Y105 E0.1\n"
            b";TYPE:External perimeter\nG0 X90 Y105\n")
        result=audit_prusa_material_model_gcode(
            native,project(),printer_ini=PRINTER,tools=[1,2])
        self.assertEqual(result["correct_extrusion_moves"],[32,32])
        self.assertEqual(result["incorrect_extrusion_moves"],[0,0])
        self.assertEqual(result["native_first_layer_adhesion_moves"],{0:1,1:0})
        for forged in (
            native.replace(b"G0 Z0.2",b"G0 Z2.5"),
            native.replace(b";TYPE:Skirt/Brim",b";TYPE:External perimeter").replace(
                b"G1 X160.1 Y105 E0.1",
                b"".join(f"G1 X{160+(i+1)*.1:.2f} Y105 E0.1\n".encode()
                         for i in range(8)).rstrip()),
            native.replace(b";TYPE:Skirt/Brim",b";TYPE:Skirt/Brim\nT9"),
        ):
            with self.subTest(raw=forged[:140]),self.assertRaises(WorkerError):
                audit_prusa_material_model_gcode(
                    forged,project(),printer_ini=PRINTER,tools=[1,2])

    def test_native_process_requires_real_first_layer_adhesion_when_enabled(self):
        base=toolpaths()
        printer=PRINTER
        requested=b"skirts = 2\nbrim_width = 3\n"
        with self.assertRaisesRegex(WorkerError,"no verified first-layer"):
            audit_prusa_material_model_gcode(
                base,project(),printer_ini=printer,tools=[1,2],
                process_ini=requested)
        # Ten independent moving positive-E first-layer adhesion strokes,
        # deliberately in the other model's XY footprint.
        skirt=(b"G0 Z0.2\n;TYPE:Skirt/Brim\n"
               b"G0 X160 Y105\n"+
               b"".join(f"G1 X{160+(n+1)*.1:.2f} Y105 E0.03\n".encode()
                        for n in range(12))+
               b";TYPE:External perimeter\nG0 X90 Y105\n")
        native=base.replace(b"G0 X90 Y105\n",skirt,1)
        accepted=audit_prusa_material_model_gcode(
            native,project(),printer_ini=printer,tools=[1,2],
            process_ini=requested)
        self.assertGreaterEqual(accepted["native_first_layer_adhesion_moves"][0],10)
        self.assertEqual(accepted["incorrect_extrusion_moves"],[0,0])
        for invalid in (
            b"skirts = 21\n",b"brim_width = 51\n",
            b"skirts = nan\n",b"skirts = 2.5\n",
        ):
            with self.subTest(invalid=invalid),self.assertRaises(WorkerError):
                audit_prusa_material_model_gcode(
                    native,project(),printer_ini=printer,tools=[1,2],
                    process_ini=invalid)

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


class PrusaOfficialIndxCleanerTests(TestCase):
    """Only verified firmware-cleaner motion may be excluded from model XY."""

    def native(self, *, include_flush=True, swap_cleaner=False, leak=False):
        lines=["G90","M83","T0","G0 X90 Y105"]
        lines += [f"G1 X{90+.06*(i+1):.3f} Y105 E.03" for i in range(32)]
        lines += ["T1"]
        if swap_cleaner:
            lines += [";FLUSH_START"]
        else:
            lines += ["G12 S90", "G91", ";FLUSH_START"]
        if include_flush:
            lines += ["G1 X-0.20 E0", "G1 X0.4 E1.0",
                      "G1 Y-1.2 E1.0", "G1 X-0.4 E1.0",
                      "G1 Y1.2 E1.0", "G1 X0.20 E.2"]
        if not swap_cleaner:
            lines += [";FLUSH_END","G90","G12 S91"]
        if leak:
            lines += ["G0 X90 Y105","G1 X90.5 Y105 E.03"]
        lines += ["G90","G0 X160 Y105"]
        lines += [f"G1 X{160+.06*(i+1):.3f} Y105 E.03" for i in range(32)]
        return ("\n".join(lines)+"\n").encode()

    def qualified(self, data):
        from unittest.mock import patch
        with patch(
            "slicer_worker.prusa_material_gcode_audit._trusted_indx_cleaner_profile",
            return_value=True
        ):
            return audit_prusa_material_model_gcode(
                data,project(),printer_ini=PRINTER,tools=[1,2])

    def test_verified_cleaner_excludes_only_bounded_toolchange_flush(self):
        result=self.qualified(self.native())
        self.assertEqual(result["correct_extrusion_moves"],[32,32])
        self.assertEqual(result["incorrect_extrusion_moves"],[0,0])
        self.assertEqual(result["qualified_cleaner_flushes"],1)

    def test_first_native_flush_can_precede_absolute_xy_without_inventing_position(self):
        raw=self.native()
        prefix=(b"T0\nG12 S90\nG91\n;FLUSH_START\n"
                b"G1 X-0.2 E0\nG1 X0.4 E1\nG1 Y-1.2 E1\n"
                b"G1 X-0.4 E1\nG1 Y1.2 E1\nG1 X0.2 E.2\n"
                b";FLUSH_END\nG90\nG12 S91\nG0 X90 Y105")
        self.assertIn(b"T0\nG0 X90 Y105",raw)
        checked=self.qualified(raw.replace(b"T0\nG0 X90 Y105",prefix))
        self.assertEqual(checked["qualified_cleaner_flushes"],2)
        self.assertEqual(checked["incorrect_extrusion_moves"],[0,0])

    def test_marker_without_exact_profile_never_excludes_material(self):
        with self.assertRaisesRegex(WorkerError, "Unqualified"):
            audit_prusa_material_model_gcode(
                self.native(),project(),printer_ini=PRINTER,tools=[1,2])

    def test_broken_cleaner_missing_flush_and_real_leak_all_fail(self):
        variants=(
            self.native(include_flush=False),
            self.native(swap_cleaner=True),
            self.native(leak=True),
            self.native().replace(b"G12 S91", b"G12 S90"),
            self.native().replace(b"G1 X0.4 E1.0", b"G1 X40 E1.0"),
        )
        for data in variants:
            with self.subTest(tail=data[-50:]),self.assertRaises(WorkerError):
                self.qualified(data)

    def test_official_cleaner_profile_is_hash_pinned_not_merely_marker_text(self):
        from slicer_worker.prusa_material_gcode_audit import (
            _trusted_indx_cleaner_profile, _OFFICIAL_INDX_8T_TOOLCHANGE_SHA256)
        self.assertEqual(len(_OFFICIAL_INDX_8T_TOOLCHANGE_SHA256),64)
        forged=(b"bed_shape = 0x0,250x0,250x210,0x210\n"
                b"nozzle_diameter = 0.4,0.4,0.4,0.4,0.4,0.4,0.4,0.4\n"
                b"toolchange_gcode = ;FLUSH_START\\nG12 S90\\n;FLUSH_END\\nG12 S91\n")
        self.assertFalse(_trusted_indx_cleaner_profile(
            forged,list(range(1,9)),None))
