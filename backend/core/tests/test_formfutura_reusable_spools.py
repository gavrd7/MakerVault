"""Regression tests for source-backed reusable spool hardware references."""
from django.test import TestCase

from core.models import ReusableSpoolCatalogEntry


class FormFuturaMasterSpoolCatalogueTests(TestCase):
    def test_two_distinct_printable_hardware_variants_are_seeded(self):
        entries = list(
            ReusableSpoolCatalogEntry.objects.filter(
                key__in=["formfutura-masterspool-750g", "formfutura-masterspool-2000g"]
            ).order_by("key")
        )
        self.assertEqual(len(entries), 2)
        self.assertNotEqual(entries[0].id, entries[1].id)
        for entry in entries:
            self.assertEqual(entry.manufacturer, "FormFutura")
            self.assertEqual(entry.design_type, "printed")
            self.assertTrue(entry.verified)
            self.assertEqual(entry.provenance["refill_family"], "FormFutura ReFill")
            self.assertTrue(entry.source_url.startswith("https://www.formfutura.com/"))
            self.assertIsNone(entry.nominal_tare_g)
            self.assertIsNone(entry.max_dryer_temp_c)
            self.assertIsNone(entry.capacity_g)
            self.assertIsNone(entry.outer_diameter_mm)
            self.assertIsNone(entry.width_mm)
            self.assertIsNone(entry.hub_diameter_mm)
            self.assertFalse(entry.image)

    def test_refill_size_is_only_metadata_not_spool_tare(self):
        for key, refill_size in (
            ("formfutura-masterspool-750g", "750g"),
            ("formfutura-masterspool-2000g", "2000g"),
        ):
            item = ReusableSpoolCatalogEntry.objects.get(key=key)
            self.assertEqual(item.provenance["compatible_refill_size"], refill_size)
            self.assertIn("nominal_tare_g", item.provenance["unverified_fields"])

    def test_azurefilm_is_one_hardware_design_not_a_bundle_sku(self):
        entry = ReusableSpoolCatalogEntry.objects.get(key="azurefilm-master-spool")
        self.assertEqual(entry.manufacturer, "AzureFilm")
        self.assertEqual(entry.design_type, "manufacturer")
        self.assertEqual(entry.provenance["refill_family"], "AzureFilm Refill")
        self.assertTrue(entry.verified)
        self.assertEqual(str(entry.nominal_tare_g), "196.00")
        self.assertEqual(str(entry.outer_diameter_mm), "200.00")
        self.assertEqual(str(entry.hub_diameter_mm), "55.00")
        self.assertEqual(entry.provenance["manufacturer_reported_temperature_tolerance_c"], 120)
        self.assertTrue(entry.provenance["temperature_tolerance_is_not_dryer_rating"])
        self.assertIsNone(entry.max_dryer_temp_c)
        self.assertEqual(
            ReusableSpoolCatalogEntry.objects.filter(
                key__startswith="azurefilm-master-spool"
            ).count(), 1
        )
