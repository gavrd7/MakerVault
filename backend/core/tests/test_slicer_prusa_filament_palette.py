from unittest import TestCase
from unittest.mock import patch
from types import SimpleNamespace

from core.slicer_prusa_filament_palette import (
    compile_prusa_filament_palette, resolve_owned_prusa_filament_palette,
)
from core.slicer_profiles import SlicerProfileError
from core.tests.test_slicer_prusa_machine_topology import ini


def filament(temp=205, first=210, diameter="1.75", extra=""):
    return (f"filament_diameter = {diameter}\n"
            f"temperature = {temp}\nfirst_layer_temperature = {first}\n"
            + extra).encode()


class PrusaFilamentPaletteTests(TestCase):
    def test_order_and_immutable_inputs(self):
        a, b = filament(), filament(220, 225)
        for changer in ("0", "1"):
            result = compile_prusa_filament_palette(ini("0.4,0.4", changer), [a,b])
            self.assertIn(b"temperature = 205,220\n", result)
            self.assertIn(b"first_layer_temperature = 210,225\n", result)
            self.assertIn(b"filament_diameter = 1.75\n", result)
        self.assertEqual(a, filament())
        self.assertEqual(b, filament(220,225))

    def test_five_slots_and_sparse_selection(self):
        result = compile_prusa_filament_palette(
            ini("0.4,0.4,0.4,0.4,0.4", "1"),
            [filament(205), filament(220), filament(215), filament(200), filament(230)],
        )
        self.assertIn(b"temperature = 205,220,215,200,230\n", result)

    def test_reject_ambiguous_and_unsupported_settings(self):
        printer = ini("0.4,0.4", "1")
        for profiles in ([filament()], [filament(), filament(351)],
                         [filament(), filament("205,220")],
                         [filament(), filament(diameter="2.85")],
                         [filament(extra="fan_speed = 30\n"), filament(extra="fan_speed = 80\n")],
                         [filament(extra="post_process = script\n"), filament()],
                         [filament(diameter="NaN"), filament(diameter="NaN")]):
            with self.subTest(profiles=profiles), self.assertRaises(SlicerProfileError):
                compile_prusa_filament_palette(printer, profiles)

    @patch("core.slicer_prusa_filament_palette.resolved_prusa_profile")
    def test_owner_checked_before_read(self, resolve):
        printer = SimpleNamespace(owner_id=7, kind="printer")
        owned = SimpleNamespace(owner_id=7, kind="filament")
        foreign = SimpleNamespace(owner_id=8, kind="filament")
        with self.assertRaises(SlicerProfileError):
            resolve_owned_prusa_filament_palette(printer, [owned, foreign], owner_id=7)
        resolve.assert_not_called()
        resolve.side_effect = [ini("0.4,0.4","1"), filament(), filament(220)]
        result = resolve_owned_prusa_filament_palette(printer, [owned,owned], owner_id=7)
        self.assertIn(b"temperature = 205,220\n", result)
