import json
from django.test import SimpleTestCase

from core.slicer_profile_edit import customise_native_json
from core.slicer_profiles import SlicerProfileError


class NativeSlicerProfileEditorTests(SimpleTestCase):
    def test_customised_orca_process_preserves_unrelated_native_fields(self):
        original = json.dumps({
            "name": "Original process", "layer_height": "0.20",
            "wall_loops": "2", "sparse_infill_pattern": "gyroid",
            "sparse_infill_density": "15%",
        }).encode()
        copy = customise_native_json(original, "process", "My process", {
            "layer_height": 0.16, "wall_loops": 3, "sparse_infill_density": 25,
        })
        edited = json.loads(copy)
        self.assertEqual(edited["name"], "My process")
        self.assertEqual(edited["layer_height"], "0.16")
        self.assertEqual(edited["wall_loops"], "3")
        self.assertEqual(edited["sparse_infill_density"], "25%")
        self.assertEqual(edited["sparse_infill_pattern"], "gyroid")
        self.assertEqual(json.loads(original)["layer_height"], "0.20")

    def test_creality_native_filament_list_shape_preserved(self):
        original = json.dumps({
            "name": "Creality PETG", "nozzle_temperature": ["245"],
            "hot_plate_temp": ["80"],
        }).encode()
        edited = json.loads(customise_native_json(original, "filament", "My PETG", {
            "nozzle_temperature": 250,
        }))
        self.assertEqual(edited["nozzle_temperature"], ["250"])
        self.assertEqual(edited["hot_plate_temp"], ["80"])


    def test_custom_profile_editor_handles_native_filament_basics(self):
        source = json.dumps({
            "name": "PLA", "filament_max_volumetric_speed": ["18"],
            "nozzle_temperature_initial_layer": ["220"],
            "filament_diameter": ["1.75"],
        }).encode()
        edited = json.loads(customise_native_json(source, "filament", "PLA faster", {
            "filament_max_volumetric_speed": 20,
            "nozzle_temperature_initial_layer": 215,
        }))
        self.assertEqual(edited["filament_max_volumetric_speed"], ["20"])
        self.assertEqual(edited["nozzle_temperature_initial_layer"], ["215"])
        self.assertEqual(edited["filament_diameter"], ["1.75"])

    def test_single_value_profile_editor_rejects_multi_extruder_overwrite(self):
        source = json.dumps({
            "name": "Dual extruder machine",
            "retraction_speed": ["30", "45"],
            "nozzle_diameter": ["0.4", "0.6"],
        }).encode()
        with self.assertRaisesRegex(SlicerProfileError, "multiple native values"):
            customise_native_json(source, "printer", "Unsafe edit", {
                "retraction_speed": 50,
            })

    def test_k2_long_retraction_must_be_explicitly_adjusted_on_a_copy(self):
        original = json.dumps({
            "name": "Official Creality K2 0.4 nozzle",
            "retraction_distances_when_cut": "30",
            "nozzle_diameter": ["0.4"],
        }).encode()
        candidate = json.loads(customise_native_json(
            original, "printer", "K2 CLI compatibility candidate",
            {"retraction_distances_when_cut": 18},
        ))
        self.assertEqual(candidate["retraction_distances_when_cut"], "18")
        self.assertEqual(candidate["nozzle_diameter"], ["0.4"])
        self.assertEqual(json.loads(original)["retraction_distances_when_cut"], "30")
        with self.assertRaises(SlicerProfileError):
            customise_native_json(
                original, "printer", "Invalid K2 value",
                {"retraction_distances_when_cut": 30},
            )

    def test_custom_k2_copy_is_flattened_and_keeps_inherited_bed(self):
        from io import BytesIO
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch
        import hashlib

        def record(pk, name, data):
            raw = json.dumps(data).encode()
            storage = MagicMock()
            storage.open.side_effect = lambda _name, _mode: BytesIO(raw)
            file = SimpleNamespace(name=f"private/{pk}.json", storage=storage)
            return SimpleNamespace(
                pk=pk, name=name, owner_id=7, engine="orcaslicer",
                engine_version="2.4.2", kind="printer",
                file_asset=SimpleNamespace(file=file, owner_id=7),
                content_sha256=hashlib.sha256(raw).hexdigest(),
            )

        parent = record("parent", "fdm_creality_common", {
            "name": "fdm_creality_common",
            "printable_height": "260",
            "bed_exclude_area": ["0x0"],
        })
        child = record("child", "Creality K2 0.4 nozzle", {
            "name": "Creality K2 0.4 nozzle",
            "inherits": "fdm_creality_common",
            "printable_area": ["0x0", "260x0", "260x260", "0x260"],
            "retraction_distances_when_cut": "30",
        })
        chain = MagicMock()
        chain.first.return_value = parent
        with patch("core.slicer_native_resolution.SlicerProfile.objects.select_related") as source:
            source.return_value.filter.return_value = chain
            from core.slicer_native_resolution import resolved_native_profile
            merged = resolved_native_profile(child)
        candidate = json.loads(customise_native_json(
            merged, "printer", "K2 custom standalone", {
                "retraction_distances_when_cut": 18,
            }
        ))
        self.assertNotIn("inherits", candidate)
        self.assertEqual(candidate["printable_area"], ["0x0", "260x0", "260x260", "0x260"])
        self.assertEqual(candidate["printable_height"], "260")
        self.assertEqual(candidate["bed_exclude_area"], ["0x0"])
        self.assertEqual(candidate["retraction_distances_when_cut"], "18")

    def test_dependency_profiles_are_identified_for_hidden_selectors(self):
        from io import BytesIO
        from types import SimpleNamespace
        import hashlib
        from core.slicer_api import _native_parent_ids

        def row(pk, name, parent=None):
            payload = {"name": name}
            if parent:
                payload["inherits"] = parent
            raw = json.dumps(payload).encode()
            return SimpleNamespace(
                pk=pk, name=name, kind="printer", engine="orcaslicer",
                engine_version="2.4.2", owner_id=7,
                content_sha256=hashlib.sha256(raw).hexdigest(),
                file_asset=SimpleNamespace(file=SimpleNamespace(
                    open=lambda mode: BytesIO(raw)
                )),
            )
        parent = row("base", "fdm_creality_common")
        k2 = row("k2", "Creality K2 0.4 nozzle", "fdm_creality_common")
        standalone = row("custom", "K2 self-contained copy")
        self.assertEqual(_native_parent_ids([parent, k2, standalone]), {"base"})

    def test_unsafe_keys_numeric_ranges_and_postprocessors_are_rejected(self):
        original = b'{"name":"Original","layer_height":"0.2"}'
        for edits in (
            {"post_process": 1}, {"layer_height": 100},
            {"layer_height": float("nan")}, {"wall_loops": 1.5},
        ):
            with self.subTest(edits=edits), self.assertRaises(SlicerProfileError):
                customise_native_json(original, "process", "Custom", edits)
        with self.assertRaises(SlicerProfileError):
            customise_native_json(b'{"post_process":"evil"}', "process", "Custom",
                                  {"layer_height": 0.2})
