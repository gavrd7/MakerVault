"""Prusa candidate INI resolution requires intact private owner-scoped bytes."""
import hashlib
from io import BytesIO
from types import SimpleNamespace
from unittest import TestCase

from core.slicer_native_resolution import resolved_native_profile
from core.slicer_profiles import SlicerProfileError


def profile(raw: bytes, *, kind="printer", owner="maker", asset_owner="maker"):
    storage = SimpleNamespace(open=lambda name, mode: BytesIO(raw))
    asset = SimpleNamespace(
        owner_id=asset_owner,
        file=SimpleNamespace(name="private/prusa.ini", storage=storage),
    )
    return SimpleNamespace(
        engine="prusaslicer", kind=kind, file_asset=asset, owner_id=owner,
        content_sha256=hashlib.sha256(raw).hexdigest(),
    )


PRINTER = (b"printer_technology = FFF\nbed_shape = 0x0,250x0,250x210,0x210\n"
           b"nozzle_diameter = 0.4\npost_process = \n")


class PrusaPrivateNativeProfileTests(TestCase):
    def test_exact_private_printer_file_can_be_resolved(self):
        self.assertEqual(resolved_native_profile(profile(PRINTER)), PRINTER)

    def test_filament_and_print_settings_admitted_independently(self):
        for kind, value in (
            ("filament", b"filament_diameter = 1.75\n"),
            ("process", b"layer_height = 0.2\n"),
        ):
            with self.subTest(kind=kind):
                self.assertEqual(resolved_native_profile(profile(value, kind=kind)), value)

    def test_owner_mismatch_refused(self):
        with self.assertRaisesRegex(SlicerProfileError, "owned"):
            resolved_native_profile(profile(PRINTER, asset_owner="another-owner"))

    def test_changed_file_hash_refused(self):
        p = profile(PRINTER)
        p.content_sha256 = "0" * 64
        with self.assertRaisesRegex(SlicerProfileError, "changed"):
            resolved_native_profile(p)

    def test_unresolved_vendor_sections_and_script_directives_refused(self):
        bad = (
            b"[printer:MK4S]\n" + PRINTER,
            PRINTER + b"inherits = *common*\n",
            PRINTER + b"post_process = UNTRUSTED_COMMAND\n",
            PRINTER + b"binary_gcode = 1\n",
            b"printer_technology = SLA\nbed_shape = 0x0,200x0\nnozzle_diameter = 0.4\n",
            PRINTER + b"\x00",
            b"bed_shape = 0x0,200x0\n",
        )
        for raw in bad:
            with self.subTest(raw=raw[:30]):
                with self.assertRaises(SlicerProfileError):
                    resolved_native_profile(profile(raw))


class PrusaSingleMaterialAdmissionTests(TestCase):
    """Never silently ignore workbench controls unsupported by native Prusa."""

    def test_global_process_changes_require_owned_native_profile(self):
        from core.slicer_execution import _validate_plate_execution, SlicerExecutionError
        job = SimpleNamespace(engine="prusaslicer", engine_version="2.9.7",
                              settings={"process_overrides": {"wall_loops": 5}}, owner=None,
                              process_profile_id=None)
        with self.assertRaisesRegex(SlicerExecutionError, "native Prusa process profile"):
            _validate_plate_execution(job)

    def test_backend_native_process_mapping_and_schema(self):
        from core.slicer_prusa_process_settings import apply_prusa_process_overrides, prusa_process_schema
        from core.slicer_prusa_native_resolution import parse_prusa_profile
        raw = (b"layer_height = 0.2\nperimeters = 2\ntop_solid_layers = 4\n"
               b"bottom_solid_layers = 3\nfill_density = 15%\nbrim_width = 0\nskirts = 1\n")
        values = {"layer_height": .25, "wall_loops": 3, "top_shell_layers": 5,
                  "bottom_shell_layers": 4, "sparse_infill_density": 30,
                  "brim_width": 3, "skirt_loops": 2}
        self.assertEqual(set(prusa_process_schema(raw)), set(values))
        self.assertEqual(parse_prusa_profile(apply_prusa_process_overrides(raw, values), "process"),
                         {"layer_height": "0.25", "perimeters": "3",
                          "top_solid_layers": "5", "bottom_solid_layers": "4",
                          "fill_density": "30%", "brim_width": "3", "skirts": "2"})
        self.assertEqual(apply_prusa_process_overrides(raw, {}), raw)
        for invalid in ({"post_process": "bad"}, {"wall_loops": 2.5},
                        {"layer_height": float("nan")}, {"brim_width": True}):
            with self.assertRaises(ValueError):
                apply_prusa_process_overrides(raw, invalid)

    def test_unverified_native_multimaterial_fails_before_worker_dispatch(self):
        from core.slicer_execution import _validate_plate_execution, SlicerExecutionError
        job = SimpleNamespace(engine="prusaslicer", engine_version="2.9.7",
                              settings={"multi_material_test": True}, owner=None)
        with self.assertRaisesRegex(SlicerExecutionError, "multi-material"):
            _validate_plate_execution(job)

    def test_unmodified_visual_stl_with_native_printer_profile_is_slicable(self):
        from core.slicer_execution import _validate_plate_execution
        cube = {
            "asset_id": "original-cube",
            "x_mm": 0, "y_mm": 0, "z_mm": 0,
            "rotation_deg": 0, "scale_percent": 100,
            "rotation_xyz_deg": [0, 0],
            "scale_xyz_percent": [100, 100, 100],
        }
        job = SimpleNamespace(
            engine="prusaslicer", engine_version="2.9.7",
            settings={"plate_objects": [cube]}, owner=None,
            printer_profile_id="official-prusa-printer",
            printer_id=None, filament_profile_id=None,
        )
        self.assertTrue(_validate_plate_execution(job))

    def test_unmodified_visual_stl_without_printer_profile_stays_blocked(self):
        from core.slicer_execution import _validate_plate_execution, SlicerExecutionError
        job = SimpleNamespace(
            engine="prusaslicer", engine_version="2.9.7",
            settings={"plate_objects": [{
                "x_mm": 0, "y_mm": 0, "z_mm": 0,
                "rotation_deg": 0, "scale_percent": 100,
                "rotation_xyz_deg": [0, 0],
                "scale_xyz_percent": [100, 100, 100],
            }]}, owner=None,
            printer_profile_id=None, printer_id=None, filament_profile_id=None,
        )
        with self.assertRaisesRegex(SlicerExecutionError, "native printer profile"):
            _validate_plate_execution(job)

    def test_transformed_prusa_plate_is_admitted_for_baked_stl(self):
        from core.slicer_execution import _validate_plate_execution
        job = SimpleNamespace(engine="prusaslicer", engine_version="2.9.7",
                              settings={"plate_objects": [{
                                  "x_mm": 10, "y_mm": 0, "z_mm": 0,
                                  "rotation_deg": 90, "scale_percent": 100,
                                  "rotation_xyz_deg": [0, 0],
                                  "scale_xyz_percent": [100, 100, 100],
                              }]}, owner=None, printer_profile_id="verified")
        self.assertTrue(_validate_plate_execution(job))

    def test_prusa_paint_stays_blocked(self):
        from core.slicer_execution import _validate_plate_execution, SlicerExecutionError
        base = {"x_mm": 10, "y_mm": 0, "z_mm": 0,
                "rotation_deg": 0, "scale_percent": 100}
        for field, value in (
            ("colour_paint", {"regions": [{"colour": "#ff0000"}]}),
            ("support_paint", {"regions": [{"state": "enforce"}]}),
            ("seam_paint", {"regions": [{"state": "enforce"}]}),
        ):
            with self.subTest(field=field):
                job = SimpleNamespace(engine="prusaslicer", engine_version="2.9.7",
                                      settings={"plate_objects": [{**base, field: value}]},
                                      owner=None, printer_profile_id="verified")
                with self.assertRaisesRegex(SlicerExecutionError, "not yet verified"):
                    _validate_plate_execution(job)

    def test_prusa_valid_object_overrides_admitted_without_modifiers(self):
        from core.slicer_execution import _validate_plate_execution
        job = SimpleNamespace(engine="prusaslicer", engine_version="2.9.7",
                              settings={"plate_objects": [{
                                  "asset_id": "owned", "x_mm": 0, "y_mm": 0, "z_mm": 0,
                                  "rotation_deg": 0, "scale_percent": 100,
                                  "process_overrides": {"wall_loops": 4,
                                                        "sparse_infill_density": 35},
                              }]}, owner=None, printer_profile_id="verified")
        self.assertTrue(_validate_plate_execution(job))

    def test_prusa_valid_negative_and_modifier_admitted_but_multimodel_guarded(self):
        import uuid
        from core.slicer_execution import _validate_plate_execution, SlicerExecutionError
        volume = {
            "id": str(uuid.uuid4()), "shape": "box", "kind": "negative",
            "width_mm": 10, "depth_mm": 10, "height_mm": 15,
            "x_mm": 0, "y_mm": 0, "z_mm": 8, "settings": {},
            "coordinate_space": "world", "rotation_xyz_deg": [0, 0, 0],
            "scale_xyz_percent": [100, 100, 100],
        }
        base = {"asset_id": "owned", "x_mm": 0, "y_mm": 0, "z_mm": 0,
                "rotation_deg": 0, "scale_percent": 100}
        job = SimpleNamespace(engine="prusaslicer", engine_version="2.9.7",
                              settings={"plate_objects": [{**base, "modifier_volumes": [volume]}]},
                              owner=None, printer_profile_id="verified")
        self.assertTrue(_validate_plate_execution(job))
        job.settings["plate_objects"].append(dict(base))
        # Native 2.9.7 G-code now demonstrates per-object modifier and
        # subtraction effects on two independent printable resources.
        self.assertTrue(_validate_plate_execution(job))
        job.settings["plate_objects"] = [{**base, "modifier_volumes": [
            {**volume, "coordinate_space": "bad"}]}]
        with self.assertRaises(SlicerExecutionError):
            _validate_plate_execution(job)
