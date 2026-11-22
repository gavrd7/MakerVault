"""Offline-only Bambu vendor profile lineage fixture contract."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.prepare_bambu_native_fixtures import (
    PROFILE_NAMES, find_vendor_bundle, prepare, resolve,
)


class BambuNativeFixturesTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.appdir = self.root / "appdir"
        self.bundle = self.appdir / "usr/share/bambu-studio/resources/profiles/BBL"
        self.bundle.mkdir(parents=True)
        (self.bundle / "cli_config.json").write_text("{}")
        for kind in PROFILE_NAMES:
            (self.bundle / kind).mkdir()
        self.write("machine", "base_machine", {
            "machine_start_gcode": "G28",
            "nozzle_diameter": ["0.4"],
        })
        self.write("machine", "start_gcode", {
            "machine_start_gcode": "G28\nM104 S200",
        })
        self.write("machine", PROFILE_NAMES["machine"], {
            "inherits": "base_machine",
            "include": ["start_gcode"],
            "nozzle_diameter": ["0.4"],
        })
        self.write("process", PROFILE_NAMES["process"], {"layer_height": "0.2"})
        self.write("filament", PROFILE_NAMES["filament"], {"filament_type": ["PLA"]})

    def write(self, kind, name, extras):
        path = self.bundle / kind / (name + ".json")
        path.write_text(json.dumps({"type": kind, "name": name, **extras}))

    def test_genuine_profile_lineage_is_flattened_without_unsafe_guessing(self):
        self.assertEqual(find_vendor_bundle(self.appdir), self.bundle)
        hashes = prepare(self.appdir, self.root / "output")
        self.assertEqual(set(hashes), {"machine", "process", "filament"})
        machine = json.loads((self.root / "output/printer.json").read_text())
        self.assertEqual(machine["machine_start_gcode"], "G28\nM104 S200")
        self.assertEqual(machine["nozzle_diameter"], ["0.4"])
        self.assertNotIn("inherits", machine)
        self.assertNotIn("include", machine)
        self.assertTrue((self.root / "output/process.json").is_file())
        self.assertTrue((self.root / "output/filament.json").is_file())

    def test_vendor_gcode_include_without_type_is_allowed_only_as_include(self):
        # Real BBL machine_start_gcode includes have name/instantiation but
        # deliberately omit the preset type field.
        fragment = self.bundle / "machine/start_gcode.json"
        fragment.write_text(json.dumps({
            "name": "start_gcode", "instantiation": "false",
            "machine_start_gcode": "G28\\nM104 S200",
        }))
        selected = resolve(self.bundle, "machine", PROFILE_NAMES["machine"])
        self.assertIn("M104", selected["machine_start_gcode"])
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            resolve(self.bundle, "machine", "start_gcode")

    def test_unknown_parent_fails_closed_and_writes_no_partial_fixture(self):
        self.write("machine", PROFILE_NAMES["machine"], {"inherits": "missing"})
        with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
            prepare(self.appdir, self.root / "output")
        self.assertFalse((self.root / "output").exists())

    def test_cycle_is_refused(self):
        self.write("machine", "base_machine", {"inherits": PROFILE_NAMES["machine"]})
        with self.assertRaisesRegex(ValueError, "cycle"):
            resolve(self.bundle, "machine", PROFILE_NAMES["machine"])

    def test_existing_fixture_dir_never_overwritten(self):
        output = self.root / "output"
        output.mkdir()
        (output / "important.txt").write_text("keep")
        with self.assertRaisesRegex(ValueError, "overwrite"):
            prepare(self.appdir, output)
        self.assertEqual((output / "important.txt").read_text(), "keep")

    def test_bad_reference_and_wrong_kind_fail_closed(self):
        self.write("machine", PROFILE_NAMES["machine"], {"inherits": "../bad"})
        with self.assertRaisesRegex(ValueError, "Invalid native"):
            resolve(self.bundle, "machine", PROFILE_NAMES["machine"])
        self.write("machine", PROFILE_NAMES["machine"], {"type": "filament"})
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            resolve(self.bundle, "machine", PROFILE_NAMES["machine"])
