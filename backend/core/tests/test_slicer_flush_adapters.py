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
