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
