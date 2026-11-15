import io
import zipfile
from unittest import TestCase

from slicer_worker.material_gcode_audit import (
    expected_native_tools, verify_multi_material_output, verify_two_object_tool_regions,
    summarize_k2_fixture_changeovers,
    verify_k2_fixture_purge_tower_evidence,
)
from slicer_worker.runner import WorkerError


class MaterialOutputVerificationTests(TestCase):
    def test_tools_are_read_from_native_3mf_assignments(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr("Metadata/model_settings.config", """<config>
              <object id="1"><metadata key="extruder" value="1"/></object>
              <object id="2"><metadata key="extruder" value="4"/></object>
              </config>""")
        self.assertEqual(expected_native_tools(archive.getvalue()), {0, 3})

    def test_two_native_tools_must_both_deposit_extrusion(self):
        self.assertTrue(verify_multi_material_output(
            b"M83\nT0\nG1 X10 E0.4\nT3\nG1 X20 E1.2\n", {0, 3}))

    def test_single_filament_or_comment_only_selection_fails(self):
        for raw in (
            b"M83\nT0\nG1 X10 E1\n; T1\n",
            b"M83\nT0\nG1 X10 E1\nT1\nG1 E1\n",
            b"M83\nT0\nG1 X10 E1\nT1\nG1 X20 E-2\n",
        ):
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(WorkerError, "lacks required"):
                    verify_multi_material_output(raw, {0, 1})


    def test_real_fixture_requires_correct_tool_in_each_model_region(self):
        left = "T0\n" + "".join("G1 X75 Y110 E0.2\n" for _ in range(25))
        right = "T1\n" + "".join("G1 X145 Y110 E0.2\n" for _ in range(25))
        content = ("M83\n" + left + right).encode()
        evidence = verify_two_object_tool_regions(content)
        self.assertEqual(evidence, {"left_tool_deposits": 25, "right_tool_deposits": 25})
        with self.assertRaisesRegex(WorkerError, "expected model/tool"):
            verify_two_object_tool_regions(("M83\n" +
                left.replace("T0", "T1") + right.replace("T1", "T0")).encode())
        # Purge-only material extrusion outside both model bounds is insufficient.
        with self.assertRaises(WorkerError):
            verify_two_object_tool_regions(
                b"M83\nT0\nG1 X10 Y10 E1\nT1\nG1 X20 Y20 E1\n")

    def test_absolute_e_and_resets_are_not_interpreted_as_filament_changes(self):
        raw = (b"M82\nT0\nG92 E0\nG1 X10 E0.3\n"
               b"T1\nG92 E0\nG1 X20 E0.5\n")
        self.assertTrue(verify_multi_material_output(raw, {0, 1}))

    def test_changeover_summary_counts_extrusion_outside_model_regions(self):
        raw = (b"G90\nM83\nT0\n"
               b"G1 X75 Y110 E0.2\n"
               b"; FEATURE: Prime tower\nG1 X40 Y40 E0.3\n"
               b"T1\nG1 E3\n"
               b"G1 X145 Y110 E0.2\n"
               b"; FEATURE: Prime tower\nG1 X41 Y40 E0.4\n"
               b"T0\nG1 X40 Y40 E0.5\n")
        evidence = summarize_k2_fixture_changeovers(raw)
        self.assertEqual(evidence["selected_tools"], [0, 1])
        self.assertEqual(evidence["tool_switches"], 2)
        self.assertEqual(evidence["outside_model_deposition_moves"], {"0": 2, "1": 1})
        self.assertEqual(evidence["stationary_extrusion_moves"], {"1": 1})
        self.assertEqual(evidence["outside_deposition_features"]["prime tower"], 3)

    def test_changeover_auditor_rejects_unsupported_relative_xy_and_binary(self):
        with self.assertRaisesRegex(WorkerError, "Relative XY"):
            summarize_k2_fixture_changeovers(b"M83\nG91\nT0\nG1 X3 E1\n")
        with self.assertRaisesRegex(WorkerError, "UTF-8"):
            summarize_k2_fixture_changeovers(b"T0\n\xff")

    def test_k2_prime_tower_gate_needs_both_tools_and_actual_outside_deposition(self):
        valid = ("G90\\nM83\\nT0\\n; FEATURE: Prime tower\\n" +
                 "".join("G1 X40 Y40 E1\\n" for _ in range(25)) +
                 "T1\\n; FEATURE: Prime tower\\n" +
                 "".join("G1 X41 Y40 E1\\n" for _ in range(25)) +
                 "T0\\n").replace(chr(92) + "n", chr(10)).encode()
        evidence = verify_k2_fixture_purge_tower_evidence(valid)
        self.assertTrue(evidence["k2_prime_tower_evidence_verified"])
        for malformed in (
            valid.replace(b"FEATURE: Prime tower", b"FEATURE: Outer wall"),
            valid.replace(b"G1 X41 Y40 E1", b"G1 X145 Y110 E1"),
            valid.replace(b"T1", b"T0"),
        ):
            with self.subTest(raw=malformed[:60]):
                with self.assertRaisesRegex(WorkerError, "prime-tower"):
                    verify_k2_fixture_purge_tower_evidence(malformed)

