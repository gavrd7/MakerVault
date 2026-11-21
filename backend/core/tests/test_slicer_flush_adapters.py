"""Common flush request and separate slicer adapters: multi-printer contract tests."""
import json
from types import SimpleNamespace

from django.test import SimpleTestCase

from core.slicer_flush_adapters import (
    apply_creality_native_flush, apply_orca_native_flush,
    audit_native_flush_profile,
    map_verified_flush_transitions, require_flush_capability,
    resolve_flush_capability,
)
from core.slicer_material_routing import MaterialRoutingError
from core.slicer_profiles import SlicerProfileError


class FlushAdapterCapabilityTests(SimpleTestCase):
    def test_same_slicer_supports_verified_single_nozzle_changers_independent_of_brand(self):
        for engine, multiplier in (("orca", "per_nozzle_vector"),
                                   ("crealityprint", "scalar")):
            for model in ("generic-mmu-1", "unknown-brand-cfs-2"):
                with self.subTest(engine=engine, model=model):
                    # Printer names intentionally do not enter capability resolution.
                    found = resolve_flush_capability(
                        engine, "single_nozzle_changer", nozzle_count=1,
                        material_count=2)
                    self.assertTrue(found.supported)
                    self.assertEqual(found.multiplier_encoding, multiplier)
                    self.assertEqual(found.matrix_layout, "directional_row_major")
                    self.assertEqual(found.purge_validation, "native_unverified")

    def test_multihead_and_nonchanger_printers_are_not_assumed_to_flush(self):
        for topology, nozzles, materials in (
            ("independent_toolheads", 2, 2),
            ("toolchanger", 4, 4),
            ("idex", 2, 2),
            ("single_material", 1, 1),
            ("manual_filament_change", 1, 2),
            ("unknown", 1, 2),
            ("single_nozzle_changer", 2, 2),
        ):
            for engine in ("orcaslicer", "crealityprint"):
                with self.subTest(engine=engine, topology=topology):
                    cap = resolve_flush_capability(
                        engine, topology, nozzle_count=nozzles,
                        material_count=materials)
                    self.assertFalse(cap.supported)
                    with self.assertRaises(MaterialRoutingError):
                        require_flush_capability(
                            engine, topology, nozzle_count=nozzles,
                            material_count=materials)

    def test_capability_is_only_encoding_not_firmware_or_physical_purge(self):
        for engine in ("orcaslicer", "crealityprint"):
            supported = resolve_flush_capability(
                engine, "single_nozzle_changer",
                nozzle_count=1, material_count=2)
            self.assertTrue(supported.supported)
            self.assertTrue(supported.supported_for_encoding_only)
            self.assertEqual(supported.purge_validation, "native_unverified")
            self.assertEqual(supported.reason, "")
            for topology, nozzles, materials in (
                ("independent_toolheads", 2, 2),
                ("toolchanger", 4, 4),
                ("idex", 2, 2),
                ("manual_filament_change", 1, 2),
                ("single_material", 1, 1),
                ("unknown", 1, 2),
            ):
                with self.subTest(engine=engine, topology=topology):
                    unsupported = resolve_flush_capability(
                        engine, topology,
                        nozzle_count=nozzles, material_count=materials)
                    self.assertFalse(unsupported.supported_for_encoding_only)
                    self.assertFalse(unsupported.supported)
                    self.assertTrue(unsupported.reason)
                    self.assertEqual(unsupported.purge_validation, "native_unverified")

    def test_orca_variable_material_palettes_preserve_direction_and_defaults(self):
        for tool_count in (2, 3, 4, 8, 16):
            with self.subTest(materials=tool_count):
                # Distinctive values ensure row/column transposition and
                # accidental replacement of unselected pairs are detected.
                matrix = [
                    "0" if a == b else str(100 + a * 17 + b)
                    for a in range(tool_count) for b in range(tool_count)
                ]
                native = json.dumps({
                    "flush_volumes_matrix": matrix,
                    "flush_multiplier": ["0.75"],
                    "enable_prime_tower": "1",
                    "change_filament_gcode": "NATIVE_TOOLCHANGE_UNCHANGED",
                }).encode()
                # The physical bay order deliberately differs from native
                # T0..Tn assignment. A direction reversal must not transpose.
                bindings = [
                    SimpleNamespace(slot_id="bay-%d" % n,
                                    tool_index=tool_count - n - 1)
                    for n in range(tool_count)
                ]
                source = bindings[0]
                dest = bindings[1]
                value = 350 + tool_count
                settings = {
                    "multiplier": None, "prime_tower": "native",
                    "transitions": [{
                        "from_slot_id": source.slot_id,
                        "to_slot_id": dest.slot_id,
                        "volume_mm3": value,
                    }],
                }
                output = json.loads(apply_orca_native_flush(
                    native, settings, routes=bindings, tool_count=tool_count,
                    topology="single_nozzle_changer"))
                index = source.tool_index * tool_count + dest.tool_index
                reverse_index = dest.tool_index * tool_count + source.tool_index
                self.assertEqual(output["flush_volumes_matrix"][index], str(value))
                self.assertEqual(output["flush_volumes_matrix"][reverse_index],
                                 matrix[reverse_index])
                self.assertEqual(output["flush_multiplier"], ["0.75"])
                self.assertEqual(output["change_filament_gcode"],
                                 "NATIVE_TOOLCHANGE_UNCHANGED")
                self.assertEqual(len(output["flush_volumes_matrix"]),
                                 tool_count * tool_count)
                for a in range(tool_count):
                    for b in range(tool_count):
                        at = a * tool_count + b
                        if at != index:
                            self.assertEqual(output["flush_volumes_matrix"][at],
                                             matrix[at])

    def test_native_matrix_absent_requires_all_directional_pairs(self):
        for count in (3, 4):
            with self.subTest(materials=count):
                routes = [SimpleNamespace(slot_id="slot-%d" % n, tool_index=n)
                          for n in range(count)]
                all_pairs = [
                    {"from_slot_id": "slot-%d" % a,
                     "to_slot_id": "slot-%d" % b,
                     "volume_mm3": 200 + a * 10 + b}
                    for a in range(count) for b in range(count) if a != b
                ]
                source = b'{"flush_multiplier":["1"],"native_custom":"preserved"}'
                request = {"multiplier": None, "prime_tower": "native",
                           "transitions": all_pairs[:-1]}
                with self.assertRaisesRegex(
                        MaterialRoutingError, "Missing native flush volumes"):
                    apply_orca_native_flush(
                        source, request, routes=routes,
                        tool_count=count, topology="single_nozzle_changer")
                request["transitions"] = all_pairs
                final = json.loads(apply_orca_native_flush(
                    source, request, routes=routes,
                    tool_count=count, topology="single_nozzle_changer"))
                self.assertEqual(final["native_custom"], "preserved")
                self.assertEqual(len(final["flush_volumes_matrix"]), count * count)
                self.assertEqual(final["flush_volumes_matrix"][1], "201")

    def test_orca_four_material_changer_does_not_require_four_nozzles(self):
        cap = require_flush_capability(
            "orcaslicer", "single_nozzle_changer",
            nozzle_count=1, material_count=4)
        self.assertEqual(cap.material_count, 4)
        self.assertEqual(cap.nozzle_count, 1)
        self.assertEqual(cap.max_calculated_volume_mm3, 20000)

    def test_creality_unverified_large_palette_remains_unavailable(self):
        cap = resolve_flush_capability(
            "crealityprint", "single_nozzle_changer",
            nozzle_count=1, material_count=4)
        self.assertFalse(cap.supported)
        # The approved project builder currently routes only TWO assigned
        # logical materials into the native four-entry palette.
        self.assertTrue(resolve_flush_capability(
            "crealityprint", "single_nozzle_changer",
            nozzle_count=1, material_count=2).supported)

    def test_unknown_engine_topology_and_counts_fail_closed(self):
        for engine, topology, n, m in (
            ("not-yet-installed", "single_nozzle_changer", 1, 2),
            ("orcaslicer", "not_verified", 1, 2),
            ("orcaslicer", "single_nozzle_changer", True, 2),
            ("orcaslicer", "single_nozzle_changer", 1, 0),
            ("crealityprint", "single_nozzle_changer", 1, 17),
        ):
            with self.subTest(engine=engine, topology=topology):
                with self.assertRaises(MaterialRoutingError):
                    resolve_flush_capability(
                        engine, topology, nozzle_count=n, material_count=m)

    def test_directional_tool_mapping_rejects_conflicts_and_collisions(self):
        settings = [
            {"from_slot_id": "blue", "to_slot_id": "black", "volume_mm3": 310},
            {"from_slot_id": "black", "to_slot_id": "blue", "volume_mm3": 180},
        ]
        routes = [SimpleNamespace(slot_id="blue", tool_index=1),
                  SimpleNamespace(slot_id="black", tool_index=0)]
        self.assertEqual(map_verified_flush_transitions(settings, routes, 2),
                         [(1, 0, 310), (0, 1, 180)])
        self.assertEqual(map_verified_flush_transitions(
            settings, {"blue": 1, "black": 0}, 2),
            [(1, 0, 310), (0, 1, 180)])
        for invalid in (
            [*routes, SimpleNamespace(slot_id="blue", tool_index=0)],
            [SimpleNamespace(slot_id="blue", tool_index=1),
             SimpleNamespace(slot_id="black", tool_index=1)],
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(MaterialRoutingError):
                    map_verified_flush_transitions(settings, invalid, 2)
        duplicate = [settings[0], {"from_slot_id": "blue-alias",
                                   "to_slot_id": "black", "volume_mm3": 320}]
        with self.assertRaises(MaterialRoutingError):
            map_verified_flush_transitions(duplicate,
                {"blue": 1, "blue-alias": 1, "black": 0}, 2)

    def test_orca_native_adapter_preserves_unmodified_machine_settings(self):
        original = json.dumps({
            "flush_volumes_matrix": ["0", "200", "300", "0"],
            "flush_multiplier": ["0.8"],
            "enable_prime_tower": "1",
            "change_filament_gcode": "native-only",
        }).encode()
        settings = {"prime_tower": "native", "multiplier": 1.2,
                    "transitions": [{"from_slot_id": "red",
                                     "to_slot_id": "white", "volume_mm3": 350}]}
        result = json.loads(apply_orca_native_flush(
            original, settings,
            routes=[SimpleNamespace(slot_id="red", tool_index=1),
                    SimpleNamespace(slot_id="white", tool_index=0)],
            tool_count=2, topology="single_nozzle_changer"))
        self.assertEqual(result["flush_volumes_matrix"],
                         ["0", "200", "350", "0"])
        self.assertEqual(result["flush_multiplier"], ["1.2"])
        self.assertEqual(result["change_filament_gcode"], "native-only")

    def test_creality_native_adapter_serializes_scalar_multiplier(self):
        original = {"filament_settings_id": ["A", "B", "A", "B"],
                    "flush_volumes_matrix": ["0"] * 16,
                    "change_filament_gcode": "native-only",
                    "enable_prime_tower": "1"}
        request = {"prime_tower": "native", "multiplier": 1.1,
                   "transitions": [
                       {"from_slot_id": "blue", "to_slot_id": "black",
                        "volume_mm3": 305}]}
        apply_creality_native_flush(
            original, request, {"blue": 1, "black": 0})
        self.assertEqual(original["flush_multiplier"], "1.1")
        self.assertEqual(original["flush_volumes_matrix"][4], "305.0")
        self.assertEqual(original["flush_volumes_changed"], "1")
        self.assertEqual(original["change_filament_gcode"], "native-only")
        self.assertEqual(original["enable_prime_tower"], "1")
        with self.assertRaises(SlicerProfileError):
            apply_creality_native_flush(original, request, {"blue": 0, "black": 0})

    def test_shared_request_maps_same_transition_into_distinct_native_engines(self):
        # Printer names deliberately omitted: source/destination mapping is
        # a verified routing relationship, not a specific K2/AMS model.
        common = {
            "multiplier": 1.15, "prime_tower": "native",
            "transitions": [
                {"from_slot_id": "left-feeder", "to_slot_id": "right-feeder",
                 "volume_mm3": 365},
                {"from_slot_id": "right-feeder", "to_slot_id": "left-feeder",
                 "volume_mm3": 205},
            ],
        }
        bindings = {"left-feeder": 1, "right-feeder": 0}
        orca = json.loads(apply_orca_native_flush(
            json.dumps({"flush_volumes_matrix": ["0", "150", "150", "0"],
                        "change_filament_gcode": "ORCA_VERIFIED_MACRO"}).encode(),
            common, routes=[
                SimpleNamespace(slot_id=slot, tool_index=index)
                for slot, index in bindings.items()],
            tool_count=2, topology="single_nozzle_changer"))
        creality = {
            "flush_volumes_matrix": ["0"] * 16,
            "change_filament_gcode": "CREALITY_VERIFIED_MACRO",
        }
        apply_creality_native_flush(creality, common, bindings)
        self.assertEqual(orca["flush_volumes_matrix"][2], "365")
        self.assertEqual(orca["flush_volumes_matrix"][1], "205")
        self.assertEqual(creality["flush_volumes_matrix"][4], "365.0")
        self.assertEqual(creality["flush_volumes_matrix"][1], "205.0")
        self.assertEqual(orca["flush_multiplier"], ["1.15"])
        self.assertEqual(creality["flush_multiplier"], "1.15")
        self.assertEqual(orca["change_filament_gcode"], "ORCA_VERIFIED_MACRO")
        self.assertEqual(creality["change_filament_gcode"], "CREALITY_VERIFIED_MACRO")

    def test_desktop_native_multipliers_and_matrices_are_not_normalised(self):
        # Reference values transcribed from the user's desktop Orca and
        # Creality Print flushing dialogs for the same four colour swatches.
        # They are observations, NOT a new cross-engine calculation formula.
        orca_matrix = [
            "0", "480", "170", "509",
            "212", "0", "199", "301",
            "170", "460", "0", "482",
            "291", "380", "276", "0",
        ]
        creality_matrix = [
            "0", "624", "220", "661",
            "237", "0", "220", "353",
            "220", "598", "0", "626",
            "378", "493", "358", "0",
        ]
        self.assertAlmostEqual(float(creality_matrix[1]), float(orca_matrix[1]) * 1.3)
        # Some native entries do NOT follow a universal 1.3x rule.
        self.assertNotEqual(int(creality_matrix[4]),
                            int(float(orca_matrix[4]) * 1.3))
        orca_native = json.dumps({
            "flush_multiplier": ["1"],
            "flush_volumes_matrix": orca_matrix,
            "change_filament_gcode": "ORCA_VENDOR_MACRO",
        }).encode()
        # No user override must preserve byte-for-byte native settings.
        self.assertEqual(apply_orca_native_flush(
            orca_native, None, routes=[], tool_count=4,
            topology="single_nozzle_changer"), orca_native)
        creality_native = {
            "flush_multiplier": "1.3",
            "flush_volumes_matrix": creality_matrix.copy(),
            "change_filament_gcode": "CREALITY_VENDOR_MACRO",
        }
        original = dict(creality_native)
        apply_creality_native_flush(creality_native, None,
                                    {"slot-1": 0, "slot-2": 1})
        self.assertEqual(creality_native, original)

    def test_creality_native_selected_direction_not_scaled_by_native_multiplier(self):
        # Creality native matrices are four-by-four even though the current
        # verified printer route binds precisely two logical materials.
        matrix = [
            "0", "624", "220", "661",
            "237", "0", "220", "353",
            "220", "598", "0", "626",
            "378", "493", "358", "0",
        ]
        native = {
            "flush_multiplier": "1.3",
            "flush_volumes_matrix": matrix.copy(),
            "change_filament_gcode": "CREALITY_VENDOR_MACRO",
        }
        settings = {
            "multiplier": None, "prime_tower": "native",
            "transitions": [{
                "from_slot_id": "a", "to_slot_id": "b",
                "volume_mm3": 480,
            }],
        }
        apply_creality_native_flush(native, settings, {"a": 0, "b": 1})
        self.assertEqual(native["flush_volumes_matrix"][1], "480.0")
        self.assertEqual(native["flush_volumes_matrix"][4], "237")
        self.assertEqual(native["flush_volumes_matrix"][3], "661")
        self.assertEqual(native["flush_multiplier"], "1.3")
        self.assertEqual(native["flush_volumes_changed"], "1")
        self.assertEqual(native["change_filament_gcode"], "CREALITY_VENDOR_MACRO")
        # Explicit multiplier changes only the native scalar; no second
        # arithmetic pass is applied to directional user volumes.
        native_again = {
            "flush_multiplier": "1.3",
            "flush_volumes_matrix": matrix.copy(),
            "change_filament_gcode": "CREALITY_VENDOR_MACRO",
        }
        apply_creality_native_flush(native_again,
            {**settings, "multiplier": 1.0}, {"a": 0, "b": 1})
        self.assertEqual(native_again["flush_multiplier"], "1.0")
        self.assertEqual(native_again["flush_volumes_matrix"][1], "480.0")
        self.assertEqual(native_again["flush_volumes_matrix"][4], "237")

    def test_orca_desktop_selected_direction_not_scaled_by_native_multiplier(self):
        native = json.dumps({
            "flush_multiplier": ["1"],
            "flush_volumes_matrix": ["0", "480", "212", "0"],
            "change_filament_gcode": "ORCA_VENDOR_MACRO",
        }).encode()
        routes = [SimpleNamespace(slot_id="a", tool_index=0),
                  SimpleNamespace(slot_id="b", tool_index=1)]
        settings = {
            "multiplier": None, "prime_tower": "native",
            "transitions": [{
                "from_slot_id": "a", "to_slot_id": "b",
                "volume_mm3": 624,
            }],
        }
        result = json.loads(apply_orca_native_flush(
            native, settings, routes=routes, tool_count=2,
            topology="single_nozzle_changer"))
        self.assertEqual(result["flush_volumes_matrix"], ["0", "624", "212", "0"])
        self.assertEqual(result["flush_multiplier"], ["1"])
        self.assertEqual(result["change_filament_gcode"], "ORCA_VENDOR_MACRO")

    def test_no_override_does_not_alter_source_or_invent_purge(self):
        self.assertEqual(apply_orca_native_flush(
            b"native", None, routes=[], tool_count=2,
            topology="single_nozzle_changer"), b"native")
        project = {"flush_volumes_matrix": ["0"] * 16}
        apply_creality_native_flush(project, None, {"A": 0, "B": 1})
        self.assertEqual(project, {"flush_volumes_matrix": ["0"] * 16})

    def test_redacted_native_profile_capability_audit_never_reveals_gcode(self):
        info = audit_native_flush_profile({
            "change_filament_gcode":
                "{if multicolor_method} M8200 P S[next_extruder] "
                "G1 E{flush_length_1} ; SECRET_SUPPLIER_MACRO {endif}",
            "nozzle_volume": ["183", "99999999", "bad"],
            "purge_in_prime_tower": "0",
            "printer_settings_id": "PRIVATE_PRINTER",
        })
        self.assertTrue(info["uses_flush_length_segments"])
        self.assertTrue(info["has_multicolor_conditional"])
        self.assertTrue(info["mentions_vendor_material_handoff"])
        self.assertEqual(info["nozzle_volumes_mm3"], [183.0])
        self.assertNotIn("SECRET_SUPPLIER_MACRO", str(info))
        self.assertNotIn("PRIVATE_PRINTER", str(info))
        self.assertEqual(info["verification"],
                         "template_only_not_emitted_or_physical_proof")
