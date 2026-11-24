"""Catalogue model scoping narrows discovery; it never approves profiles."""
from django.test import SimpleTestCase
from core.slicer_official_filter import narrow_catalogue, profile_matches_printer, models_from_machines, fuzzy_name_match, slot_filament_catalogue


class OfficialPresetDecimalSearchTests(SimpleTestCase):
    def test_decimal_layer_height_matches_unit_suffixed_bambu_presets(self):
        preset = "0.20mm Standard @BBL X1C"
        for query in ("0.20", "0.20mm", "0.20 mm", "Standard 0.20"):
            with self.subTest(query=query):
                self.assertTrue(fuzzy_name_match(preset, query))
        self.assertFalse(fuzzy_name_match(preset, "0.12"))

    def test_exact_model_tokens_remain_distinct(self):
        self.assertFalse(fuzzy_name_match("0.20mm Standard @K10", "K1"))
        self.assertTrue(fuzzy_name_match("0.20mm Standard @K1", "K1"))


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

    def test_models_are_deduplicated_from_machine_nozzle_variants(self):
        entries = [(name, "machine/" + name + ".json") for name in (
            "Creality K1 (0.4 nozzle)", "Creality K1 (0.6 nozzle)",
            "Creality K1 Max (0.4 nozzle)", "Creality K2 (0.4 nozzle)",
        )]
        self.assertEqual(models_from_machines(entries),
                         ["Creality K1", "Creality K1 Max", "Creality K2"])

    def test_fuzzy_search_matches_tokens_anywhere_without_k1_k10_confusion(self):
        self.assertTrue(fuzzy_name_match("0.20mm Standard @Creality K1 (0.4 nozzle)", "K1 standard"))
        self.assertTrue(fuzzy_name_match("Generic PLA @Creality K1", "K1 PLA"))
        self.assertFalse(fuzzy_name_match("Generic PLA @Creality K10", "K1 PLA"))


class SlotProfileDiscoveryTests(SimpleTestCase):
    def test_k2_discovery_excludes_internal_base_and_wrong_printer(self):
        rows = [(name, "filament/Creality/" + name + ".json") for name in (
            "CR-ABS @base", "CR-ABS @Creality K1", "CR-ABS @Creality K2 Plus",
            "CR-ABS @Creality K2", "Generic ABS @System",
        )]
        found = slot_filament_catalogue(rows, "Creality K2 Combo", product="CR-ABS",
                                       material="ABS", manufacturer="Creality",
                                       catalogue_vendor="Creality")
        self.assertEqual([name for name, _ in found],
                         ["CR-ABS @Creality K2", "Generic ABS @System"])

    def test_material_library_excludes_competitor_brand_without_identified_spool(self):
        rows = [
            ("BETA PLA Basic @System", "filament/BETA/beta.json"),
            ("Bambu PLA Basic @System", "filament/Bambu/bambu.json"),
            ("Creality PLA Basic @System", "filament/Creality/creality.json"),
            ("Generic PLA @System", "filament/Generic/generic.json"),
            ("Generic PLA Basic @base", "filament/base/base.json"),
        ]
        found = slot_filament_catalogue(rows, "Creality K2", product="PLA Basic",
                                       material="PLA", catalogue_vendor="OrcaFilamentLibrary")
        self.assertEqual([name for name, _ in found],
                         ["Creality PLA Basic @System", "Generic PLA @System"])

    def test_known_library_spool_brand_unlocks_its_own_manufacturer(self):
        rows = [
            ("Sunlu PLA Silk @System", "filament/Sunlu/sunlu.json"),
            ("Bambu PLA Silk @System", "filament/Bambu/bambu.json"),
        ]
        found = slot_filament_catalogue(rows, "Creality K2", product="PLA Silk",
                                       material="PLA", manufacturer="Sunlu",
                                       catalogue_vendor="OrcaFilamentLibrary")
        self.assertEqual([name for name, _ in found], ["Sunlu PLA Silk @System"])
