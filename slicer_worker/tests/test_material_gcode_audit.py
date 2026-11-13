import io
import zipfile
from unittest import TestCase

from slicer_worker.material_gcode_audit import (
    expected_native_tools, verify_multi_material_output,
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

    def test_absolute_e_and_resets_are_not_interpreted_as_filament_changes(self):
        raw = (b"M82\nT0\nG92 E0\nG1 X10 E0.3\n"
               b"T1\nG92 E0\nG1 X20 E0.5\n")
        self.assertTrue(verify_multi_material_output(raw, {0, 1}))
