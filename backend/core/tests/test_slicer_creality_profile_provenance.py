"""Read-only native Creality printer/profile provenance; never expose private scripts."""
import hashlib
import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from core.management.commands.diagnose_creality_paint_features import (
    _creality_purge_profile_merge_audit,
)
from core.slicer_native_resolution import audit_creality_profile_origins
from core.slicer_profiles import SlicerProfileError


class _MemoryStorage:
    def __init__(self, files):
        self.files = files

    def open(self, name, mode):
        return io.BytesIO(self.files[name])


def _profile(identifier, name, blob, storage):
    return SimpleNamespace(
        pk=identifier, name=name, engine="crealityprint", engine_version="7.3.1",
        kind="machine", owner_id=50, source_scope="approved-profile-pack",
        content_sha256=hashlib.sha256(blob).hexdigest(),
        file_asset=SimpleNamespace(owner_id=50, file=SimpleNamespace(
            name=name, storage=storage)),
    )


class NativeCrealityProvenanceTests(SimpleTestCase):
    def test_native_process_precedence_and_redacted_macro_capabilities(self):
        machine = {
            "type": "machine",
            "change_filament_gcode":
                "G1 E{flush_length_1}\n; SECRET_MACHINE_MACRO",
            "nozzle_volume": ["183"],
            "purge_in_prime_tower": "0",
        }
        process = {
            "type": "process",
            "change_filament_gcode": "T[next_extruder]; SECRET_PROCESS_SCRIPT",
            "purge_in_prime_tower": "1",
        }
        audit = _creality_purge_profile_merge_audit(
            json.dumps(machine).encode(), json.dumps(process).encode())
        macro = audit["fields"]["change_filament_gcode"]
        self.assertEqual(macro["source"], "process_overrides_machine")
        self.assertTrue(macro["values_differ"])
        self.assertTrue(macro["machine_capability"]["uses_flush_length_segments"])
        self.assertFalse(macro["effective_capability"]["uses_flush_length_segments"])
        self.assertEqual(audit["fields"]["nozzle_volume"]["source"], "machine")
        self.assertEqual(audit["fields"]["purge_in_prime_tower"]["source"],
                         "process_overrides_machine")
        self.assertNotIn("SECRET_MACHINE_MACRO", str(audit))
        self.assertNotIn("SECRET_PROCESS_SCRIPT", str(audit))

    def test_inherited_machine_macro_origin_and_selected_override(self):
        parent_raw = json.dumps({
            "type": "machine", "name": "Parent",
            "change_filament_gcode": "G1 E{flush_length_1};PRIVATE_PARENT_SCRIPT",
            "nozzle_volume": "183",
        }).encode()
        child_raw = json.dumps({
            "type": "machine", "name": "Child",
            "inherits": "Parent", "nozzle_volume": "150",
        }).encode()
        storage = _MemoryStorage({"child.json": child_raw, "parent.json": parent_raw})
        child = _profile(1, "child.json", child_raw, storage)
        parent = _profile(2, "parent.json", parent_raw, storage)
        obj = MagicMock()
        obj.select_related.return_value.filter.return_value = [parent]
        with patch("core.slicer_native_resolution.SlicerProfile.objects", obj):
            report = audit_creality_profile_origins(child)
        macro = report["fields"]["change_filament_gcode"]
        self.assertEqual(macro["origin"], "inherited_parent")
        self.assertEqual(macro["parent_depth"], 1)
        self.assertEqual(report["fields"]["nozzle_volume"]["origin"],
                         "selected_preset")
        self.assertEqual(report["inheritance_depth"], 1)
        self.assertEqual(len(macro["script_sha256"]), 64)
        self.assertNotIn("PRIVATE_PARENT_SCRIPT", str(report))
        self.assertNotIn("Parent", str(report))

    def test_tampered_selected_profile_fails_closed(self):
        raw = b'{"type":"machine","change_filament_gcode":"M117 PRIVATE"}'
        storage = _MemoryStorage({"model.json": raw})
        profile = _profile(1, "model.json", raw, storage)
        profile.content_sha256 = "0" * 64
        with self.assertRaises(SlicerProfileError):
            audit_creality_profile_origins(profile)

    def test_missing_macros_cannot_be_reported_as_consumed(self):
        raw = b'{"type":"machine","nozzle_volume":"183"}'
        storage = _MemoryStorage({"model.json": raw})
        profile = _profile(1, "model.json", raw, storage)
        report = audit_creality_profile_origins(profile)
        self.assertEqual(report["fields"]["change_filament_gcode"]["origin"],
                         "absent")
        self.assertEqual(report["inheritance_depth"], 0)
        merged = _creality_purge_profile_merge_audit(raw, b'{"type":"process"}')
        self.assertEqual(merged["fields"]["change_filament_gcode"]["source"],
                         "native_default_or_missing")
        self.assertFalse(merged["fields"]["change_filament_gcode"]["defined"])
