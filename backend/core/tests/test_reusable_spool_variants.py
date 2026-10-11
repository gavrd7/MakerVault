"""Regression checks for the distinct second generation and recycled variants."""
from decimal import Decimal
from django.test import TestCase
from core.models import ReusableSpoolCatalogEntry


class ReusableSpoolVariantsTests(TestCase):
    def test_esun_second_generation_is_distinct_from_original(self):
        first = ReusableSpoolCatalogEntry.objects.get(key="esun-espool-plus")
        second = ReusableSpoolCatalogEntry.objects.get(key="esun-espool-plus-2")
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(second.provenance["revision"], "2.0")
        self.assertIsNone(second.nominal_tare_g)
        self.assertIsNone(second.max_dryer_temp_c)

    def test_recycling_material_variants_keep_dryer_limit_unknown(self):
        entries = [
            ReusableSpoolCatalogEntry.objects.get(key="recycling-fabrik-multispool-" + slug)
            for slug in ("rpla", "rpetg")
        ]
        self.assertNotEqual(entries[0].pk, entries[1].pk)
        self.assertEqual([e.material for e in entries], ["rPLA", "rPETG"])
        for entry in entries:
            self.assertEqual(entry.nominal_tare_g, Decimal("150.00"))
            self.assertTrue(entry.provenance["approximate_tare_g"])
            self.assertTrue(entry.provenance["avoid_dryer"])
            self.assertEqual(entry.provenance["reseller_exposure_limit_c"], 60)
            self.assertIsNone(entry.max_dryer_temp_c)
            self.assertFalse(entry.image)
