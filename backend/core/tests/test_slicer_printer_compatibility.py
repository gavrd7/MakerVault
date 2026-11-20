"""Native printer-compatibility fixtures are bounded, offline, and tool-agnostic."""
import io
import json
import zipfile
from defusedxml import ElementTree as ET
from django.test import SimpleTestCase

from core.management.commands.diagnose_slicer_printer_profiles import (
    _fixture_items, _safe_native_result, _same_native_pair, _native_nozzle_count,
    _compatible_filament_diameter, _read_creality_project_settings,
    _creality_flush_basis, _creality_control_project,
    _creality_flush_override_control, _validate_creality_override_pair,
    _creality_purge_route_control, _creality_purge_route_audit,
    _validate_creality_purge_route_pair,
    _creality_emitted_setting_audit, _creality_emitted_comparison,
    _creality_prime_volume_control, _creality_control_project_with_extra,
)
from core.slicer_plate_3mf import build_plate_3mf, NS


class PrinterCompatibilityFixtureTests(SimpleTestCase):
    def test_distinct_2_3_4_material_fixtures_on_verified_beds(self):
        for count in (2, 3, 4):
            for width, depth in ((90, 90), (180, 180), (350, 350)):
                with self.subTest(count=count, width=width):
                    items = _fixture_items(count, width, depth)
                    self.assertEqual(len(items), count)
                    self.assertEqual(len(set(item["instance_id"] for item, _ in items)),
                                     count)
                    self.assertEqual(len(set(item["x_mm"] for item, _ in items)), count)
                    project = build_plate_3mf(
                        items, bed_width=width, bed_depth=depth,
                        native_tool_indices=list(range(count)))
                    with zipfile.ZipFile(io.BytesIO(project)) as archive:
                        root = ET.fromstring(archive.read("3D/3dmodel.model"))
                    ns = "{" + NS + "}"
                    objects = root.findall("./" + ns + "resources/" + ns + "object")
                    self.assertEqual(len(objects), count)

    def test_small_bed_or_invalid_tool_count_fails_closed(self):
        for count, width, depth in ((0, 180, 180), (5, 180, 180),
                                    (2, 89, 200), (3, 200, 70)):
            with self.subTest(count=count, width=width, depth=depth):
                with self.assertRaises(ValueError):
                    _fixture_items(count, width, depth)

    def test_offline_native_result_exposes_digest_only(self):
        sample = (b";PRIVATE_MACHINE_GCODE\n"
                  b"G1 X1 Y1 E0.1\n"
                  b"G1 X2 Y2 E0.2\n"
                  b"T0\nM117 CHANGE\n")
        report = _safe_native_result(sample)
        self.assertEqual(len(report["gcode_sha256"]), 64)
        self.assertEqual(len(report["motion_sha256"]), 64)
        self.assertEqual(len(report["machine_command_sha256"]), 64)
        self.assertEqual(report["g1_with_extrusion"], 2)
        self.assertEqual(report["tool0_selects"], 1)
        self.assertEqual(report["tool1_selects"], 0)
        self.assertNotIn("PRIVATE_MACHINE_GCODE", str(report))
        self.assertNotIn("M117 CHANGE", str(report))

    def test_selected_profiles_must_share_owner_engine_and_version(self):
        class Profile:
            owner_id = "user1"
            engine = "orcaslicer"
            engine_version = "2.4.2"
            kind = "filament"
            status = "candidate"
        profile = Profile()
        self.assertTrue(_same_native_pair(
            profile, "user1", "orcaslicer", "2.4.2", "filament"))
        self.assertFalse(_same_native_pair(
            profile, "user2", "orcaslicer", "2.4.2", "filament"))
        self.assertFalse(_same_native_pair(
            profile, "user1", "crealityprint", "2.4.2", "filament"))
        self.assertFalse(_same_native_pair(
            profile, "user1", "orcaslicer", "2.5.0", "filament"))
        self.assertFalse(_same_native_pair(
            profile, "user1", "orcaslicer", "2.4.2", "printer"))
        profile.status = "unverified_invalid"
        self.assertFalse(_same_native_pair(
            profile, "user1", "orcaslicer", "2.4.2", "filament"))

    def test_native_nozzle_count_comes_from_resolved_profile_not_printer_name(self):
        for values, expected in ((["0.4"], 1),
                                 (["0.4", "0.4"], 2),
                                 (["0.25", "0.4", "0.6", "0.8"], 4)):
            with self.subTest(values=values):
                source = json.dumps({
                    "name": "Any Printer", "nozzle_diameter": values,
                }).encode()
                self.assertEqual(_native_nozzle_count(source), expected)
        for values in (None, [], ["nan"], ["0"], ["bad"], ["0.4"] * 17):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    _native_nozzle_count(json.dumps({
                        "name": "Any Printer", "nozzle_diameter": values,
                    }).encode())

    def test_native_multi_material_requires_same_verified_filament_diameter(self):
        def filament(diameter):
            return json.dumps({"type": "filament",
                               "filament_diameter": [diameter]}).encode()
        self.assertEqual(_compatible_filament_diameter(
            [filament("1.75"), filament("1.75"), filament("1.750")]), 1.75)
        for profiles in (
            [filament("1.75"), filament("2.85")],
            [filament("1.75"), filament("nan")],
            [filament("1.75"), json.dumps({"type": "filament"}).encode()],
        ):
            with self.subTest(profiles=profiles):
                with self.assertRaises(ValueError):
                    _compatible_filament_diameter(profiles)

    def test_creality_native_scalar_filament_diameter_is_not_orca_vector(self):
        def scalar(value):
            return json.dumps({"type": "filament",
                               "filament_diameter": value}).encode()
        self.assertEqual(_compatible_filament_diameter(
            [scalar("1.75"), scalar("1.750")], engine="crealityprint"), 1.75)
        self.assertEqual(_compatible_filament_diameter(
            [scalar(1.75)], engine="crealityprint"), 1.75)
        for invalid in (
            [scalar(["1.75"])],  # Orca encoding must not silently cross engines.
            [scalar("nan")],
            [scalar("0")],
            [scalar("bad")],
            [scalar(True)],
            [scalar("1.75"), scalar("2.85")],
            [json.dumps({"type": "filament"}).encode()],
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    _compatible_filament_diameter(invalid, engine="crealityprint")
        # Orca continues to reject Creality's scalar representation.
        with self.assertRaises(ValueError):
            _compatible_filament_diameter([scalar("1.75")], engine="orcaslicer")

    def test_creality_directional_control_rejects_native_script_or_geometry_mutation(self):
        def archive(config, model=b"same fixture"):
            data = io.BytesIO()
            with zipfile.ZipFile(data, "w") as dst:
                dst.writestr("Metadata/project_settings.config",
                             json.dumps(config).encode())
                dst.writestr("3D/3dmodel.model", model)
            return data.getvalue()

        source = {
            "flush_multiplier": "1.3",
            "flush_volumes_matrix": ["0", "624", "220", "661",
                                     "237", "0", "220", "353",
                                     "220", "598", "0", "626",
                                     "378", "493", "358", "0"],
            "change_filament_gcode": "vendor script unchanged",
            "printer_settings_id": "native machine",
        }
        original = archive(source)
        modified = {**source, "flush_volumes_matrix": source["flush_volumes_matrix"].copy(),
                    "flush_volumes_changed": "1"}
        modified["flush_volumes_matrix"][1] = "649.0"
        before, after, changed_keys = _creality_control_project(
            original, archive(modified))
        self.assertEqual(before["flush_volumes_matrix"][4], "237")
        self.assertEqual(after["flush_volumes_matrix"][1], "649.0")
        self.assertEqual(changed_keys, {"flush_volumes_matrix", "flush_volumes_changed"})
        self.assertEqual(_creality_flush_basis(before), (624.0, 1.3))
        for mutated, model in (
            ({**modified, "change_filament_gcode": "tampered"}, b"same fixture"),
            (modified, b"DIFFERENT geometry"),
            ({**modified, "printer_settings_id": "wrong machine"}, b"same fixture"),
        ):
            with self.subTest(changed=list(mutated), model=model):
                with self.assertRaises(ValueError):
                    _creality_control_project(original, archive(mutated, model))

    def test_creality_multiplier_control_does_not_mutate_native_matrix(self):
        def archive(config):
            data = io.BytesIO()
            with zipfile.ZipFile(data, "w") as dst:
                dst.writestr("Metadata/project_settings.config",
                             json.dumps(config).encode())
                dst.writestr("3D/3dmodel.model", b"identical geometry")
            return data.getvalue()

        source = {"flush_multiplier": "1.3",
                  "flush_volumes_matrix": ["0", "624", *["140"] * 14],
                  "change_filament_gcode": "native"}
        control = {**source, "flush_multiplier": "1.0"}
        before, after, keys = _creality_control_project(
            archive(source), archive(control))
        self.assertEqual(keys, {"flush_multiplier"})
        self.assertEqual(before["flush_volumes_matrix"],
                         after["flush_volumes_matrix"])
        self.assertEqual(_creality_flush_basis(after), (624.0, 1.0))

    def test_explicit_multiplier_controls_when_native_default_is_absent(self):
        def archive(config):
            data = io.BytesIO()
            with zipfile.ZipFile(data, "w") as z:
                z.writestr("Metadata/project_settings.config", json.dumps(config))
                z.writestr("3D/3dmodel.model", b"identical")
            return data.getvalue()

        original = {
            "flush_volumes_matrix": ["0", "140", *["140"] * 14],
            "change_filament_gcode": "original native vendor macro",
        }
        self.assertEqual(_creality_flush_basis(original), (140.0, None))
        for multiplier in (1.0, 2.0):
            with self.subTest(multiplier=multiplier):
                explicit = {**original, "flush_multiplier": str(multiplier)}
                before, after, changes = _creality_control_project(
                    archive(original), archive(explicit))
                self.assertEqual(changes, {"flush_multiplier"})
                self.assertEqual(before["flush_volumes_matrix"],
                                 after["flush_volumes_matrix"])
                self.assertEqual(before["change_filament_gcode"],
                                 after["change_filament_gcode"])
                self.assertEqual(_creality_flush_basis(after),
                                 (140.0, multiplier))

    def test_creality_override_marker_control_only_changes_process_declarations(self):
        def archive(config, model=b"same geometry"):
            destination = io.BytesIO()
            with zipfile.ZipFile(destination, "w") as z:
                z.writestr("Metadata/project_settings.config", json.dumps(config))
                z.writestr("3D/3dmodel.model", model)
                for name in ("Metadata/model_settings.config",
                             "Metadata/creality.config",
                             "[Content_Types].xml", "_rels/.rels"):
                    z.writestr(name, b"unchanged")
            return destination.getvalue()

        config = {
            "filament_settings_id": ["A", "B", "A", "B"],
            "different_settings_to_system": [
                "enable_support;support_type", "", "", "", "", ""],
            "flush_multiplier": "2.0",
            "flush_volumes_matrix": ["0", "140"] + ["140"] * 14,
            "flush_volumes_changed": "1",
            "change_filament_gcode": "preserve vendor macro",
        }
        raw = archive(config)
        marked = _creality_flush_override_control(raw)
        self.assertTrue(_validate_creality_override_pair(raw, marked))
        original = _read_creality_project_settings(raw)
        result = _read_creality_project_settings(marked)
        self.assertEqual(result["flush_multiplier"], "2.0")
        self.assertEqual(result["flush_volumes_matrix"], original["flush_volumes_matrix"])
        self.assertEqual(result["change_filament_gcode"], "preserve vendor macro")
        self.assertEqual(result["different_settings_to_system"][1:],
                         original["different_settings_to_system"][1:])
        names = result["different_settings_to_system"][0].split(";")
        self.assertEqual(names[:2], ["enable_support", "support_type"])
        self.assertEqual(names[2:], [
            "flush_multiplier", "flush_volumes_matrix", "flush_volumes_changed"])
        self.assertEqual(marked, _creality_flush_override_control(marked))

    def test_creality_override_marker_fails_closed_on_invalid_vector(self):
        config = {
            "filament_settings_id": ["A", "B", "A", "B"],
            "different_settings_to_system": ["", "", ""],
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr("Metadata/project_settings.config", json.dumps(config))
            for name in ("3D/3dmodel.model", "Metadata/model_settings.config",
                         "Metadata/creality.config", "[Content_Types].xml", "_rels/.rels"):
                z.writestr(name, b"unchanged")
        with self.assertRaises(ValueError):
            _creality_flush_override_control(buffer.getvalue())

    def test_invalid_creality_native_flush_basis_fails_closed(self):
        valid = {"flush_multiplier": "1.3",
                 "flush_volumes_matrix": ["0", "624"] + ["140"] * 14}
        for altered in (
            {**valid, "flush_multiplier": ["1.3"]},
            {**valid, "flush_multiplier": "nan"},
            {**valid, "flush_volumes_matrix": ["0", "624"]},
            {**valid, "flush_volumes_matrix": ["0", "inf"] + ["140"] * 14},
            {**valid, "flush_volumes_matrix": ["0", "-1"] + ["140"] * 14},
        ):
            with self.subTest(altered=altered):
                with self.assertRaises(ValueError):
                    _creality_flush_basis(altered)
        self.assertEqual(_creality_flush_basis({
            "flush_volumes_matrix": valid["flush_volumes_matrix"]}),
            (624.0, None))

    def test_purge_route_controls_preserve_native_geometry_macros_and_flush_values(self):
        def archive(config):
            destination = io.BytesIO()
            with zipfile.ZipFile(destination, "w") as z:
                z.writestr("Metadata/project_settings.config", json.dumps(config))
                for name in ("3D/3dmodel.model", "Metadata/model_settings.config",
                             "Metadata/creality.config", "[Content_Types].xml", "_rels/.rels"):
                    z.writestr(name, b"unchanged native bytes")
            return destination.getvalue()

        source = {
            "purge_in_prime_tower": "0",
            "enable_prime_tower": "1",
            "prime_volume": "45",
            "flush_multiplier": "2.0",
            "flush_volumes_matrix": ["0", "140"] + ["140"] * 14,
            "change_filament_gcode": "secret native vendor macro",
            "filament_settings_id": ["A", "B", "C", "D"],
        }
        original = archive(source)
        for enabled, expected in ((False, "0"), (True, "1")):
            with self.subTest(enabled=enabled):
                candidate = _creality_purge_route_control(original, enabled)
                with zipfile.ZipFile(io.BytesIO(original)) as before, zipfile.ZipFile(
                        io.BytesIO(candidate)) as after:
                    self.assertEqual(before.namelist(), after.namelist())
                    for name in before.namelist():
                        if name != "Metadata/project_settings.config":
                            self.assertEqual(before.read(name), after.read(name))
                changed = _read_creality_project_settings(candidate)
                self.assertEqual(changed["purge_in_prime_tower"], expected)
                for key in ("change_filament_gcode", "flush_multiplier",
                            "flush_volumes_matrix", "prime_volume", "enable_prime_tower"):
                    self.assertEqual(changed[key], source[key])
                audit = _creality_purge_route_audit(changed)
                self.assertEqual(audit["purge_in_prime_tower"],
                                 "enabled" if enabled else "disabled")
                self.assertEqual(audit["flush_multiplier"], 2.0)
                self.assertEqual(audit["prime_volume_mm3"], 45.0)
                self.assertNotIn("secret native vendor macro", str(audit))
                self.assertEqual(candidate, _creality_purge_route_control(candidate, enabled))

    def test_route_isolation_compares_common_multiplier_parent_not_native_baseline(self):
        def archive(config, geometry=b"same object"):
            out = io.BytesIO()
            with zipfile.ZipFile(out, "w") as z:
                z.writestr("Metadata/project_settings.config", json.dumps(config))
                for name in ("3D/3dmodel.model", "Metadata/model_settings.config",
                             "Metadata/creality.config", "[Content_Types].xml", "_rels/.rels"):
                    z.writestr(name, geometry)
            return out.getvalue()

        native = {"flush_volumes_matrix": ["0", "140"] + ["140"] * 14,
                  "change_filament_gcode": "native immutable tool-change macro",
                  "purge_in_prime_tower": "0"}
        baseline = archive(native)
        parent = archive({**native, "flush_multiplier": "2.0"})
        for route in (False, True):
            candidate = _creality_purge_route_control(parent, route)
            self.assertTrue(_validate_creality_purge_route_pair(
                baseline, parent, candidate, route))
        tampered = archive({**native, "flush_multiplier": "2.0",
                            "purge_in_prime_tower": "1",
                            "prime_volume": "999"})
        with self.assertRaises(ValueError):
            _validate_creality_purge_route_pair(baseline, parent, tampered, True)
        with self.assertRaises(ValueError):
            _validate_creality_purge_route_pair(
                baseline, parent, archive({**native, "flush_multiplier": "1.0",
                                           "purge_in_prime_tower": "1"}), True)

    def test_prime_volume_positive_control_preserves_all_other_archive_members(self):
        original = {
            "prime_volume": "45",
            "purge_in_prime_tower": "0",
            "flush_multiplier": "2.0",
            "flush_volumes_matrix": ["0", "140"] + ["140"] * 14,
            "change_filament_gcode": "preserve vendor macro",
        }
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            z.writestr("Metadata/project_settings.config", json.dumps(original))
            for name in ("3D/3dmodel.model", "Metadata/model_settings.config",
                         "Metadata/creality.config", "[Content_Types].xml", "_rels/.rels"):
                z.writestr(name, b"untouched geometry and native script")
        raw = out.getvalue()
        changed = _creality_prime_volume_control(raw)
        self.assertEqual(_read_creality_project_settings(changed)["prime_volume"], "180")
        before, after, changed_keys = _creality_control_project_with_extra(
            raw, changed, {"prime_volume"})
        self.assertEqual(changed_keys, {"prime_volume"})
        self.assertEqual(before["change_filament_gcode"], after["change_filament_gcode"])
        self.assertEqual(_creality_prime_volume_control(raw), changed)
        with self.assertRaises(ValueError):
            _creality_prime_volume_control(raw, 50)
        with self.assertRaises(ValueError):
            _creality_prime_volume_control(raw, True)

    def test_emitted_gcode_audit_reports_only_safe_native_comment_evidence(self):
        baseline = (b"; flush_multiplier = 1.0\n"
                    b"; prime_volume = 45\n"
                    b"; purge_in_prime_tower = 0\n"
                    b"; flush_volumes_matrix = 0,140,140,0\n"
                    b"; change_filament_gcode = SECRET_MACRO\n"
                    b"G1 X1 Y1 E1\n")
        changed = baseline.replace(b"flush_multiplier = 1.0", b"flush_multiplier = 2.0")
        before = _creality_emitted_setting_audit(baseline)
        comparison = _creality_emitted_comparison(baseline, changed)
        self.assertEqual(before["settings"]["flush_multiplier"], 1.0)
        self.assertEqual(before["settings"]["purge_in_prime_tower"], "disabled")
        self.assertEqual(before["settings"]["flush_volumes_matrix"], "present")
        self.assertEqual(comparison["changed_emitted_keys"], ["flush_multiplier"])
        self.assertEqual(comparison["candidate"]["settings"]["flush_multiplier"], 2.0)
        self.assertNotIn("SECRET_MACRO", str(comparison))
        self.assertNotIn("0,140,140,0", str(before))

    def test_emitted_gcode_audit_handles_absence_conflicts_and_invalid_input(self):
        report = _creality_emitted_setting_audit(
            b"; flush_multiplier = 1.0\n; flush_multiplier = 2.0\n"
            b"; prime_volume = nan\n; prime_tower_width = 0xBAD\n"
            b"; purge_in_prime_tower = suspicious\n"
            b"; a_secret = 1234\n")
        self.assertEqual(report["settings"], {})
        self.assertEqual(report["conflicting_keys"], ["flush_multiplier"])
        self.assertIn("prime_volume", report["recognised_keys_absent"])
        self.assertNotIn("suspicious", str(report))
        self.assertNotIn("0xBAD", str(report))
        for value in (None, b"", "not bytes"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _creality_emitted_setting_audit(value)

    def test_purge_route_audit_rejects_unrecognised_values_without_leaking(self):
        audit = _creality_purge_route_audit({
            "purge_in_prime_tower": ["invalid"],
            "multicolor_method": "not a flag",
            "prime_volume": "NaN",
            "flush_multiplier": {"invalid": 123},
            "change_filament_gcode": "private details",
        })
        self.assertEqual(audit["purge_in_prime_tower"], "unrecognised")
        self.assertEqual(audit["multicolor_method"], "unrecognised")
        self.assertIsNone(audit["prime_volume_mm3"])
        self.assertIsNone(audit["flush_multiplier"])
        self.assertNotIn("private details", str(audit))
        with self.assertRaises(ValueError):
            _creality_purge_route_audit([])
        with self.assertRaises(ValueError):
            _creality_purge_route_control(b"not a zip", True)
        with self.assertRaises(ValueError):
            _creality_purge_route_control(b"not a zip", "1")
