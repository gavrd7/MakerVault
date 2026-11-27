"""Security and positive-material evidence for the Prusa-only native G-code gate."""
from unittest import TestCase

from slicer_worker.prusa_gcode_audit import audit_prusa_positive_e
from slicer_worker.runner import WorkerError


class PrusaGcodeAuditTests(TestCase):
    def gcode(self, *, relative=False):
        start = "; PrusaSlicer generated native G-code\n" + ("M83\n" if relative else "M82\n")
        start += "G92 E0\n"
        start += "; setup\n" * 300
        moves = ["G1 Z0.2 F600"]
        for i in range(32):
            value = 0.6 if relative else (i + 1) * 0.6
            moves.append(f"G1 X{i+50} Y50 E{value:.3f} F1200")
        return (start + "\n".join(moves) + "\n").encode()

    def test_genuine_planar_extrusion_in_absolute_and_relative_modes(self):
        for relative in (True, False):
            with self.subTest(relative=relative):
                result = audit_prusa_positive_e(self.gcode(relative=relative))
                self.assertEqual(result["positive_e_moves"], 32)

    def test_extruder_position_survives_mode_switch(self):
        # Relative E+1 repeated 25 times reaches E=25. Switching to M82
        # and commanding E=20 is retraction, not a new positive extrusion.
        prefix = b"; harmless header\n" * 200 + b"M83\nG92 E0\n"
        deposits = b"".join(
            f"G1 X{i+40} Y50 E1\n".encode() for i in range(25)
        )
        tail = b"M82\nG1 X85 Y50 E20\n"
        result = audit_prusa_positive_e(prefix + deposits + tail)
        self.assertEqual(result["positive_e_moves"], 25)

    def test_reset_and_retraction_cannot_fake_positive_material(self):
        data = b"; padding\n" * 300 + b"M82\nG92 E0\n"
        data += b"G1 E10 F2400\nG1 X30 Y40 E10\n" * 25
        with self.assertRaisesRegex(WorkerError, "insufficient"):
            audit_prusa_positive_e(data)

    def test_refuse_binary_malformed_and_empty_gcode(self):
        for data in (
            b"",
            b"; empty\n" * 400,
            self.gcode() + b"\x00",
            self.gcode() + b"\xff",
            self.gcode().replace(b"E0.600", b"E1e999"),
        ):
            with self.subTest(size=len(data)):
                with self.assertRaises(WorkerError):
                    audit_prusa_positive_e(data)

    def test_no_gcode_data_or_script_reaches_error_message(self):
        payload = self.gcode() + b"\0private-preset-marker"
        with self.assertRaises(WorkerError) as ctx:
            audit_prusa_positive_e(payload)
        self.assertNotIn("private-preset-marker", str(ctx.exception))


class PrusaPaintedWallMotionTests(TestCase):
    """Worker must not mistake stationary E, G91 or a crossing path for paint."""

    def source(self, *, stationary=False, crossing=False, relative_xy=False):
        lines = ["M83", "G90", "G92 E0"]
        for tool, y in ((1, 95), (0, 115)):
            lines += [f"T{tool}", ";TYPE:External perimeter",
                      f"G0 X115 Y{y}"]
            if relative_xy:
                lines.append("G91")
            for n in range(25):
                if stationary:
                    lines.append("G1 E0.03")
                elif crossing:
                    if relative_xy:
                        lines += ["G90", f"G0 X110 Y{y}",
                                  f"G1 X120 Y{y} E0.03", "G91"]
                    else:
                        lines += [f"G0 X110 Y{y}", f"G1 X120 Y{y} E0.03"]
                elif relative_xy:
                    lines.append("G1 X0.5 Y0 E0.03")
                else:
                    lines.append(f"G1 X{115+(n+1)*.5:.2f} Y{y} E0.03")
            if relative_xy:
                lines.append("G90")
            lines += [";TYPE:Wipe tower", "G0 X55 Y155"]
            for n in range(12):
                lines.append(f"G1 X{55+(n+1)*.5:.2f} Y155 E0.03")
        return ("\\n".join(lines)+"\\n").encode()

    def checked(self, data):
        from unittest.mock import patch
        from slicer_worker.prusa_colour_gcode_audit import audit_prusa_offline_colour_gcode
        with patch(
            "slicer_worker.prusa_colour_gcode_audit.validate_prusa_material_candidate",
            return_value={"tools": (1, 2)}
        ), patch(
            "slicer_worker.prusa_colour_gcode_audit._wall_regions",
            return_value=((114, 136, 93, 97), (114, 136, 113, 117))
        ):
            return audit_prusa_offline_colour_gcode(
                data, b"verified-project", printer_ini=b"verified-printer",
                tool=1, tower=(55, 150, 0, 250, 210))

    def test_both_native_xy_modes_count_only_deposited_wall_paths(self):
        for relative in (False, True):
            with self.subTest(relative_xy=relative):
                result = self.checked(self.source(relative_xy=relative))
                self.assertEqual(result["painted_wall_moves"][1]["front"], 25)
                self.assertEqual(result["painted_wall_moves"][0]["back"], 25)
                self.assertGreaterEqual(result["tower_extrusion_moves"][0], 10)
                self.assertGreaterEqual(result["tower_extrusion_moves"][1], 10)

    def test_stationary_and_crossing_paths_never_qualify_painted_wall(self):
        for mode in ({"stationary": True}, {"crossing": True}):
            with self.subTest(mode=mode), self.assertRaises(WorkerError):
                self.checked(self.source(**mode))

    def test_stationary_tower_recovery_cannot_qualify_purging(self):
        data = self.source()
        # Keep valid wall extrusion; replace the moving wipe paths with
        # stationary positive-E commands in both tool sections.
        import re
        data = re.sub(rb"G1 X\\d+(?:\\.\\d+)? Y155 E0\\.03",
                      b"G1 E0.03", data)
        with self.assertRaisesRegex(WorkerError, "tower purging"):
            self.checked(data)
