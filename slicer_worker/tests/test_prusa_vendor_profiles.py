"""Offline Prusa 2.9.7 vendor-INI contract, including native parent sections."""
import hashlib
from unittest import TestCase

from slicer_worker.prusa_vendor_profiles import (
    PrusaPresetError, parse_prusa_vendor_bundle, flatten_prusa_vendor_preset,
    validate_flat_prusa_preset
)

# Structure and named parents follow the upstream PrusaResearch.ini format.
BUNDLE = b"""# Prusa Research
[vendor]
name = Prusa Research
config_update_url = https://example.invalid/never-fetched
[print:*common*]
layer_height = 0.2
fill_density = 15%
post_process =
[print:*quality*]
inherits = *common*
perimeters = 3
[print:0.20mm QUALITY @MK4S]
inherits = *quality*
fill_density = 20%
[filament:*common*]
filament_diameter = 1.75
[filament:Generic PLA]
inherits = *common*
temperature = 215
[printer:*common*]
printer_technology = FFF
nozzle_diameter = 0.4
start_gcode = G28\\nM109 S210
[printer:MK4S 0.4 nozzle]
inherits = *common*
bed_shape = 0x0,250x0,250x210,0x210
"""


class PrusaVendorPresetsTests(TestCase):
    def test_multilevel_inheritance_and_per_kind_resolution(self):
        data = flatten_prusa_vendor_preset(
            BUNDLE, kind="print", name="0.20mm QUALITY @MK4S")
        self.assertIn(b"fill_density = 20%", data)
        self.assertIn(b"layer_height = 0.2", data)
        self.assertIn(b"perimeters = 3", data)
        self.assertNotIn(b"inherits", data)
        self.assertNotIn(b"[print", data)
        self.assertNotIn(b"nozzle_diameter", data)

    def test_separate_native_filament_and_printer_files(self):
        filament = flatten_prusa_vendor_preset(
            BUNDLE, kind="filament", name="Generic PLA")
        printer = flatten_prusa_vendor_preset(
            BUNDLE, kind="printer", name="MK4S 0.4 nozzle")
        self.assertIn(b"temperature = 215", filament)
        self.assertIn(b"filament_diameter = 1.75", filament)
        self.assertIn(b"printer_technology = FFF", printer)
        self.assertIn(b"start_gcode = G28", printer)

    def test_sha256_pins_exact_vendor_bytes(self):
        digest = hashlib.sha256(BUNDLE).hexdigest()
        self.assertEqual(
            flatten_prusa_vendor_preset(
                BUNDLE, kind="print", name="*common*",
                expected_sha256=digest),
            b"fill_density = 15%\nlayer_height = 0.2\npost_process = \n")
        with self.assertRaisesRegex(PrusaPresetError, "checksum"):
            flatten_prusa_vendor_preset(
                BUNDLE, kind="print", name="*common*",
                expected_sha256="0"*64)

    def test_refuse_wrong_kind_missing_parent_duplicate_and_cycle(self):
        for kind, name, raw in (
            ("printer", "Generic PLA", BUNDLE),
            ("print", "Missing", BUNDLE),
            ("print", "A", b"[print:A]\ninherits = B\n[print:B]\ninherits = A\n"),
            ("print", "A", b"[print:A]\nlayer_height=0.2\n[print:A]\nfill_density=10%\n"),
            ("print", "A", b"[print:A]\nlayer_height=0.2\nlayer_height=0.1\n"),
        ):
            with self.subTest(kind=kind, name=name):
                with self.assertRaises(PrusaPresetError):
                    flatten_prusa_vendor_preset(raw, kind=kind, name=name)

    def test_reject_nonempty_scripts_and_controls(self):
        for raw in (
            BUNDLE.replace(b"post_process =", b"post_process = /tmp/evil.sh"),
            BUNDLE + b"\x00",
            BUNDLE.replace(b"layer_height = 0.2", b"layer_height = \xff"),
            BUNDLE + b"[print:evil]\ninclude = ../evil.ini\n",
        ):
            with self.subTest(raw=repr(raw[-25:])):
                with self.assertRaises(PrusaPresetError):
                    parse_prusa_vendor_bundle(raw)

    def test_reject_sla_printers_and_keep_literal_percent(self):
        raw = BUNDLE + b"[printer:SLA]\nprinter_technology = SLA\n"
        with self.assertRaisesRegex(PrusaPresetError, "FFF"):
            flatten_prusa_vendor_preset(raw, kind="printer", name="SLA")
        settings = flatten_prusa_vendor_preset(BUNDLE, kind="print", name="*common*")
        self.assertIn(b"15%", settings)

    def test_official_indx_vendor_can_contain_long_but_bounded_literals(self):
        base=(b"[printer:INDX 8T]\n"
              b"nozzle_diameter = 0.4,0.4,0.4,0.4,0.4,0.4,0.4,0.4\n"
              b"bed_shape = 0x0,250x0,250x210,0x210\n")
        safe=base+b"printer_notes = "+b"A"*24000+b"\n"
        result=flatten_prusa_vendor_preset(
            safe,kind="printer",name="INDX 8T")
        self.assertEqual(len(validate_flat_prusa_preset(
            result,kind="printer")["printer_notes"]),24000)
        with self.assertRaisesRegex(PrusaPresetError,"invalid setting"):
            parse_prusa_vendor_bundle(
                base+b"printer_notes = "+b"B"*65537+b"\n")

    def test_source_content_has_no_implicit_network_access(self):
        # The vendor URL is inert metadata, never resolved or returned.
        parsed = parse_prusa_vendor_bundle(BUNDLE)
        self.assertTrue(parsed["vendor"]["config_update_url"].startswith("https:"))
        flat = flatten_prusa_vendor_preset(BUNDLE, kind="printer", name="MK4S 0.4 nozzle")
        self.assertNotIn(b"config_update_url", flat)


    def test_multiple_parents_preserve_later_override_and_shared_ancestors(self):
        bundle = (b"[print:Base]\nlayer_height = 0.2\nfill_density = 10%\n"
                  b"[print:A]\ninherits = Base\nfill_density = 20%\n"
                  b"[print:B]\ninherits = Base\nfill_density = 30%\n"
                  b"[print:Derived]\ninherits = A; B\nperimeters = 3\n")
        flat = flatten_prusa_vendor_preset(bundle, kind="print", name="Derived")
        self.assertIn(b"layer_height = 0.2", flat)
        self.assertIn(b"fill_density = 30%", flat)
        self.assertIn(b"perimeters = 3", flat)
        self.assertNotIn(b"inherits", flat)
        bad = bundle + b"[print:Cycle]\ninherits = Derived; Cycle\n"
        with self.assertRaisesRegex(PrusaPresetError, "cyclic"):
            flatten_prusa_vendor_preset(bad, kind="print", name="Cycle")

    def test_cli_flat_presets_accept_bounded_native_settings(self):
        for kind, name in (
            ("printer", "MK4S 0.4 nozzle"),
            ("filament", "Generic PLA"),
            ("print", "0.20mm QUALITY @MK4S"),
        ):
            flat = flatten_prusa_vendor_preset(BUNDLE, kind=kind, name=name)
            with self.subTest(kind=kind):
                settings = validate_flat_prusa_preset(flat, kind=kind)
                self.assertTrue(settings)

    def test_cli_blocks_unresolved_vendor_sections_and_inheritance(self):
        for raw in (
            b"[printer:MK4S]\nnozzle_diameter = 0.4\n",
            b"nozzle_diameter = 0.4\nbed_shape = 0x0,200x0,200x200,0x200\ninherits = parent\n",
            b"nozzle_diameter = 0.4\nbed_shape = 0x0,200x0,200x200,0x200\n"
            b"binary_gcode = 1\n",
        ):
            with self.subTest(raw=raw[:25]):
                with self.assertRaises(PrusaPresetError):
                    validate_flat_prusa_preset(raw, kind="printer")

    def test_cli_refuses_missing_native_requirements(self):
        for kind, raw in (
            ("printer", b"nozzle_diameter = 0.4\n"),
            ("filament", b"temperature = 215\n"),
            ("print", b"fill_density = 15%\n"),
        ):
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(PrusaPresetError, "required"):
                    validate_flat_prusa_preset(raw, kind=kind)

    def test_cli_rejects_script_sections_and_duplicate_keys(self):
        good = b"nozzle_diameter = 0.4\nbed_shape = 0x0,200x0,200x200,0x200\n"
        for extra in (
            b"post_process = /tmp/run.sh\n",
            b"layer_height = 0.2\nlayer_height = 0.1\n",
            b"nozzle_diameter = 0.6\n",
            b"binary_gcode = 1\n",
            b"\x00",
        ):
            with self.subTest(extra=extra[:20]):
                with self.assertRaises(PrusaPresetError):
                    validate_flat_prusa_preset(good + extra, kind="printer")
