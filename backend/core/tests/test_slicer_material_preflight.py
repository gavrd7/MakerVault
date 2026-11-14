"""Offline preflight proves routing and 3MF tool assignment are one artifact."""
import io
import json
import zipfile
from types import SimpleNamespace

from defusedxml import ElementTree as ET
from django.test import SimpleTestCase

from core.slicer_approval import fixture_stl
from core.slicer_material_preflight import prepare_offline_material_plate
from core.slicer_material_routing import MaterialRoutingError


class OfflineMaterialPreflightTests(SimpleTestCase):
    def setUp(self):
        mesh = fixture_stl()
        self.items = [
            ({"instance_id": "left", "asset_id": "left-mesh",
              "x_mm": -35, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100,
              "material_slot": {"printer_id": "printer-k2", "slot_id": "cfs-4", "slot_index": 3}}, mesh),
            ({"instance_id": "right", "asset_id": "right-mesh",
              "x_mm": 35, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100,
              "material_slot": {"printer_id": "printer-k2", "slot_id": "cfs-1", "slot_index": 0}}, mesh),
        ]
        self.profiles = [
            SimpleNamespace(owner_id="owner", engine="orcaslicer",
                            engine_version="2.4.2", kind="filament", status="verified",
                            name="filament-0"),
            SimpleNamespace(owner_id="owner", engine="orcaslicer",
                            engine_version="2.4.2", kind="filament", status="verified",
                            name="filament-1"),
        ]
        self.options = {
            "bed_width": 260, "bed_depth": 260,
            "printer_id": "printer-k2", "owner_id": "owner",
            "engine": "orcaslicer", "engine_version": "2.4.2",
            "topology": "single_nozzle_changer",
            "tool_bindings": {"cfs-4": 1, "cfs-1": 0},
            "native_filament_profiles": self.profiles,
            "resolver": lambda p: json.dumps({
                "name": p.name, "filament_diameter": ["1.75"],
            }).encode(),
        }

    def test_3mf_object_extruders_match_verified_route_order(self):
        output = prepare_offline_material_plate(self.items, **self.options)
        self.assertEqual(output["native_tool_indices"], (1, 0))
        self.assertEqual([r.slot_id for r in output["routes"]], ["cfs-4", "cfs-1"])
        with zipfile.ZipFile(io.BytesIO(output["model_3mf"])) as pkg:
            manifest = ET.fromstring(pkg.read("Metadata/model_settings.config"))
            config = [
                [node.attrib["value"] for node in group.findall("metadata")
                 if node.attrib["key"] == "extruder"][0]
                for group in manifest.findall("object")
            ]
        self.assertEqual(config, ["2", "1"])
        self.assertEqual(len(output["filament_profiles"]), 2)

    def test_independent_head_topology_produces_same_neutral_mesh_assignments(self):
        output = prepare_offline_material_plate(
            self.items, **{**self.options, "topology": "independent_toolheads"})
        self.assertEqual(output["native_tool_indices"], (1, 0))
        self.assertEqual(output["topology"], "independent_toolheads")

    def test_different_printer_and_overlapping_geometry_fail_closed(self):
        foreign = [(dict(self.items[0][0]), self.items[0][1]), self.items[1]]
        foreign[0][0]["material_slot"] = {
            **foreign[0][0]["material_slot"], "printer_id": "another-printer"}
        with self.assertRaises(MaterialRoutingError):
            prepare_offline_material_plate(foreign, **self.options)
        overlapping = [(dict(self.items[0][0]), self.items[0][1]), self.items[1]]
        overlapping[0][0]["x_mm"] = 35
        with self.assertRaises(ValueError):
            prepare_offline_material_plate(overlapping, **self.options)

    def test_offline_preflight_applies_directional_flush_and_preserves_native_tower(self):
        process = json.dumps({
            "flush_volumes_matrix": [0, 160, 220, 0],
            "flush_multiplier": ["0.7"],
            "enable_prime_tower": "1",
            "prime_tower_width": "40",
        }).encode()
        flush = {"multiplier": 1.1, "prime_tower": "native", "transitions": [
            {"from_slot_id": "cfs-4", "to_slot_id": "cfs-1", "volume_mm3": 345},
        ]}
        output = prepare_offline_material_plate(
            self.items, **self.options, native_process_profile=process,
            flush_settings=flush)
        profile = json.loads(output["native_process_profile"])
        self.assertEqual(profile["flush_volumes_matrix"], ["0", "160", "345", "0"])
        self.assertEqual(profile["flush_multiplier"], ["1.1"])
        self.assertEqual(profile["enable_prime_tower"], "1")
        self.assertEqual(profile["prime_tower_width"], "40")

