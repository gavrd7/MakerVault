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

    def test_official_indx_extended_literals_preserve_owner_digest_and_limits(self):
        from core.slicer_prusa_native_resolution import (
            parse_prusa_profile, MAX_NATIVE_VALUE)
        value = "{next_extruder}" + " " * 20000 + "G1 E0"
        native = PRINTER + ("toolchange_gcode = " + value + "\n").encode()
        self.assertEqual(
            parse_prusa_profile(resolved_native_profile(profile(native)), "printer")[
                "toolchange_gcode"], value)
        for bad in (
            PRINTER + ("toolchange_gcode = " + "x"*(MAX_NATIVE_VALUE+1) + "\n").encode(),
            PRINTER + ("post_process = " + "x"*20000 + "\n").encode(),
            PRINTER + ("include = " + "x"*20000 + "\n").encode(),
        ):
            with self.subTest(kind=bad.split(b" = ")[-2][-20:]):
                with self.assertRaises(SlicerProfileError):
                    resolved_native_profile(profile(bad))
        # The trust check is performed on the exact bytes even for long values.
        altered = profile(native)
        altered.content_sha256 = "0"*64
        with self.assertRaisesRegex(SlicerProfileError, "changed"):
            resolved_native_profile(altered)

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

    def test_extended_prusa_global_speeds_preserve_native_keys(self):
        from core.slicer_prusa_process_settings import (
            apply_prusa_process_overrides, prusa_process_schema, FIELDS)
        raw = (b"layer_height = 0.2\n"
               b"external_perimeter_speed = 30\nperimeter_speed = 40\n"
               b"infill_speed = 70\ntravel_speed = 130\n"
               b"top_solid_infill_speed = 35\n")
        edits = {"outer_wall_speed": 22, "inner_wall_speed": 38,
                 "sparse_infill_speed": 60, "travel_speed": 150,
                 "top_surface_speed": 25}
        fields = prusa_process_schema(raw)
        self.assertTrue(set(edits).issubset(fields))
        from core.slicer_prusa_native_resolution import parse_prusa_profile
        native = parse_prusa_profile(
            apply_prusa_process_overrides(raw, edits), "process")
        for key, value in edits.items():
            self.assertEqual(float(native[FIELDS[key][0]]), value)
        for unsafe in (
            {"outer_wall_speed": False}, {"inner_wall_speed": "G28"},
            {"travel_speed": float("inf")}, {"sparse_infill_speed": 900}):
            with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                apply_prusa_process_overrides(raw, unsafe)

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
        for field, value, expected in (
            ("colour_paint", {"regions": [{"colour": "#ff0000"}]}, "not yet verified"),
            ("seam_paint", {"regions": [{"state": "enforce"}]}, "fingerprinted native regions"),
        ):
            with self.subTest(field=field):
                job = SimpleNamespace(engine="prusaslicer", engine_version="2.9.7",
                                      settings={"plate_objects": [{**base, field: value}]},
                                      owner=None, printer_profile_id="verified")
                with self.assertRaisesRegex(SlicerExecutionError, expected):
                    _validate_plate_execution(job)

    def test_native_support_enforcer_blocker_and_fuzzy_admit_separately(self):
        from core.slicer_execution import _validate_plate_execution, SlicerExecutionError
        def paint(slot=0):
            return {"version": 2, "signature": "12:deadbeef",
                    "regions": [{"slot": slot, "patches": [{
                        "face": 0, "polygon": [[0,0,0],[1,0,0],[0,1,0]]}]}]}
        base = {"asset_id": "owned-cube", "x_mm": 0, "y_mm": 0,
                "z_mm": 0, "rotation_deg": 0, "scale_percent": 100}
        for field, value in (
            ("support_paint", paint(0)),
            ("support_paint", paint(1)),
            ("fuzzy_skin_paint", paint(0)),
        ):
            with self.subTest(field=field,value=value):
                job = SimpleNamespace(engine="prusaslicer", engine_version="2.9.7",
                                      settings={"plate_objects": [{**base, field: value}]},
                                      owner=None, printer_profile_id="verified")
                self.assertTrue(_validate_plate_execution(job))
        for extras in (
            {"support_paint": paint(0), "fuzzy_skin_paint": paint(0)},
            {"support_paint": paint(0), "process_overrides": {"wall_loops": 4}},
            {"fuzzy_skin_paint": paint(0), "variable_layer_profile":
                {"version": 1, "bands": [{"from_mm": 3, "to_mm": 10, "layer_mm": .12}]}},
        ):
            with self.subTest(extras=extras):
                job = SimpleNamespace(engine="prusaslicer", engine_version="2.9.7",
                                      settings={"plate_objects": [{**base, **extras}]},
                                      owner=None, printer_profile_id="verified")
                with self.assertRaises(SlicerExecutionError):
                    _validate_plate_execution(job)

    def test_prusa_two_model_fuzzy_is_independently_admitted_but_support_is_not(self):
        from core.slicer_execution import _validate_plate_execution, SlicerExecutionError
        paint = {"version": 2, "signature": "12:deadbeef",
                 "regions": [{"slot": 0, "patches": [{
                     "face": 0, "polygon": [[0, 0, 0], [1, 0, 0], [0, 1, 0]]
                 }]}]}
        left = {"asset_id": "owned-left", "x_mm": -35, "y_mm": 0, "z_mm": 0,
                "rotation_deg": 0, "scale_percent": 100,
                "fuzzy_skin_paint": paint}
        right = {"asset_id": "owned-right", "x_mm": 35, "y_mm": 0, "z_mm": 0,
                 "rotation_deg": 0, "scale_percent": 100}
        job = SimpleNamespace(engine="prusaslicer", engine_version="2.9.7",
                              settings={"plate_objects": [left, right]},
                              owner=None, printer_profile_id="verified")
        self.assertTrue(_validate_plate_execution(job))
        for edited in (
            [{**left, "support_paint": paint}, right],
            [{**left, "fuzzy_skin_paint": paint},
             {**right, "fuzzy_skin_paint": paint}],
            [left, {**right, "scale_percent": 150}],
        ):
            with self.subTest(edited=edited):
                job.settings["plate_objects"] = edited
                with self.assertRaises(SlicerExecutionError):
                    _validate_plate_execution(job)

    def test_prusa_two_object_variable_layers_admitted_with_independent_audit(self):
        from core.slicer_execution import _validate_plate_execution, SlicerExecutionError
        band = {"version": 1, "bands": [
            {"from_mm": 5, "to_mm": 15, "layer_mm": .12}]}
        base = {"asset_id": "owned-cube", "z_mm": 0,
                "rotation_deg": 0, "rotation_xyz_deg": [0, 0],
                "scale_percent": 100, "scale_xyz_percent": [100, 100, 100]}
        left = {**base, "x_mm": -35, "y_mm": 0,
                "variable_layer_profile": band}
        right = {**base, "x_mm": 35, "y_mm": 0}
        job = SimpleNamespace(engine="prusaslicer", engine_version="2.9.7",
                              settings={"plate_objects": [left, right]},
                              owner=None, printer_profile_id="verified")
        self.assertTrue(_validate_plate_execution(job))
        for invalid in (
            [{**left, "scale_percent": 150},right],
            [left,{**right, "rotation_xyz_deg": [90, 0]}],
            [left,right,{**right, "x_mm": 90}],
        ):
            with self.subTest(invalid=invalid):
                job.settings["plate_objects"] = invalid
                with self.assertRaises(SlicerExecutionError):
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
