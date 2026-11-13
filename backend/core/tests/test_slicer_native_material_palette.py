"""Ordered native palette preflight; never queue a printer job."""
import json
from types import SimpleNamespace

from django.test import SimpleTestCase

from core.slicer_material_routing import MaterialRoutingError
from core.slicer_native_material_palette import resolve_native_material_palette


class NativeMaterialPaletteTests(SimpleTestCase):
    def setUp(self):
        self.objects = [
            {"instance_id": "model-a", "material_slot": {
                "printer_id": "printer-1", "slot_id": "cfs-4", "slot_index": 3}},
            {"instance_id": "model-b", "material_slot": {
                "printer_id": "printer-1", "slot_id": "cfs-1", "slot_index": 0}},
        ]
        self.profiles = [
            SimpleNamespace(owner_id="user-1", engine="orcaslicer",
                            engine_version="2.4.2", kind="filament",
                            status="verified", name="PLA A"),
            SimpleNamespace(owner_id="user-1", engine="orcaslicer",
                            engine_version="2.4.2", kind="filament",
                            status="verified", name="PLA B"),
        ]
        self.payload = {
            "printer_id": "printer-1", "owner_id": "user-1",
            "engine": "orcaslicer", "engine_version": "2.4.2",
            "topology": "single_nozzle_changer",
            "tool_bindings": {"cfs-4": 1, "cfs-1": 0},
            "native_filament_profiles": self.profiles,
        }

    def resolve(self, profile):
        return json.dumps({
            "name": profile.name,
            "filament_diameter": ["1.75"],
        }).encode()

    def test_changer_preserves_explicit_palette_and_object_tool_order(self):
        data = resolve_native_material_palette(
            self.objects, **self.payload, resolver=self.resolve)
        self.assertEqual(data["native_tool_indices"], (1, 0))
        self.assertEqual([json.loads(b)["name"] for b in data["filament_profiles"]],
                         ["PLA A", "PLA B"])
        self.assertEqual(data["topology"], "single_nozzle_changer")
        self.assertEqual(len(data["routes"]), 2)

    def test_independent_heads_use_the_same_native_palette(self):
        data = resolve_native_material_palette(
            self.objects, **{**self.payload, "topology": "independent_toolheads"},
            resolver=self.resolve)
        self.assertEqual(data["native_tool_indices"], (1, 0))

    def test_rejects_unverified_foreign_or_wrong_engine_profiles(self):
        cases = [
            {"status": "candidate"},
            {"owner_id": "someone-else"},
            {"engine": "crealityprint"},
            {"engine_version": "2.4.1"},
            {"kind": "process"},
        ]
        for mutation in cases:
            with self.subTest(mutation=mutation):
                changed = [SimpleNamespace(**vars(self.profiles[0])),
                           SimpleNamespace(**{**vars(self.profiles[1]), **mutation})]
                with self.assertRaises(MaterialRoutingError):
                    resolve_native_material_palette(
                        self.objects, **{**self.payload, "native_filament_profiles": changed},
                        resolver=self.resolve)

    def test_rejects_missing_tool_profile_and_nonmatching_diameter(self):
        for bindings in ({"cfs-4": 3, "cfs-1": 0}, {"cfs-4": 0, "cfs-1": 0}):
            with self.subTest(bindings=bindings):
                with self.assertRaises(MaterialRoutingError):
                    resolve_native_material_palette(
                        self.objects, **{**self.payload, "tool_bindings": bindings},
                        resolver=self.resolve)
        def mismatched(profile):
            diameter = "2.85" if profile.name == "PLA B" else "1.75"
            return json.dumps({"filament_diameter": [diameter]}).encode()
        with self.assertRaisesRegex(MaterialRoutingError, "Mixed filament diameters"):
            resolve_native_material_palette(
                self.objects, **self.payload, resolver=mismatched)

    def test_rejects_invalid_native_filament_blob(self):
        for blob in (b"{}", b'{"filament_diameter":[false]}',
                     b'{"filament_diameter":["NaN"]}', b"[]", b"not json"):
            with self.subTest(blob=blob):
                with self.assertRaises(MaterialRoutingError):
                    resolve_native_material_palette(
                        self.objects, **self.payload, resolver=lambda profile: blob)
