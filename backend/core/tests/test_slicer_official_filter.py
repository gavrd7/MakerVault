"""Catalogue model scoping narrows discovery; it never approves profiles."""
from django.test import SimpleTestCase
from core.slicer_official_filter import narrow_catalogue, profile_matches_printer


class OfficialModelScopeTests(SimpleTestCase):
    def test_printer_variants_are_not_mixed(self):
        records = [(name, "machine/" + name + ".json") for name in (
            "Creality K1 0.4 nozzle",
            "Creality K1 Max 0.4 nozzle",
            "Creality K2 0.4 nozzle",
        )]
        self.assertEqual([name for name, _ in narrow_catalogue(records, "printer", "K1")],
                         ["Creality K1 0.4 nozzle"])
        self.assertEqual([name for name, _ in narrow_catalogue(records, "printer", "K1 Max")],
                         ["Creality K1 Max 0.4 nozzle"])

    def test_machine_qualified_presets_and_generic_candidates(self):
        self.assertTrue(profile_matches_printer("Generic PLA", "filament", "Creality K1"))
        self.assertTrue(profile_matches_printer("Generic PLA @Creality K1", "filament", "Creality K1"))
        self.assertFalse(profile_matches_printer("Generic PLA @Creality K2", "filament", "Creality K1"))
        self.assertFalse(profile_matches_printer("0.20mm Standard @Creality K2", "process", "Creality K1"))
        self.assertTrue(profile_matches_printer(
            "0.20mm Standard @Creality K1 (0.4 nozzle)", "process", "Creality K1"))
        self.assertFalse(profile_matches_printer(
            "0.20mm Standard @Creality K1 Max_CFS-C 0.4 nozzle", "process", "Creality K1"))
        self.assertFalse(profile_matches_printer(
            "0.20mm Standard @Creality K1 SE 0.4 nozzle", "process", "Creality K1"))
        self.assertTrue(profile_matches_printer("0.20mm Standard", "process", "Creality K1"))
        self.assertFalse(profile_matches_printer("Creality K2 Hyper PLA", "filament", "Creality K1"))
        self.assertTrue(profile_matches_printer("Generic PLA", "filament", ""))
