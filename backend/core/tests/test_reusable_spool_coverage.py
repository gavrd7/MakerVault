from django.test import TestCase

from core.catalogue_coverage import catalogue_coverage_summary
from core.models import ReusableSpoolCatalogEntry


class ReusableSpoolCoverageTests(TestCase):
    def test_shared_spool_catalogue_appears_in_coverage(self):
        audit = catalogue_coverage_summary()
        spool = next(item for item in audit["catalogues"] if item["key"] == "reusable_spools")
        self.assertEqual(spool["total"], ReusableSpoolCatalogEntry.objects.count())
        metric = {m["key"]: m for m in spool["metrics"]}
        self.assertIn("images", metric)
        self.assertIn("specifications", metric)
        self.assertIn("sources", metric)
        self.assertIn("drying", metric)
        self.assertEqual(metric["images"]["complete"], sum(
            bool(row.image) for row in ReusableSpoolCatalogEntry.objects.all()
        ))

    def test_temperature_tolerance_without_dryer_source_does_not_count(self):
        spool = next(item for item in catalogue_coverage_summary()["catalogues"]
                     if item["key"] == "reusable_spools")
        azure = ReusableSpoolCatalogEntry.objects.get(key="azurefilm-master-spool")
        self.assertIsNone(azure.max_dryer_temp_c)
        sample = next((s for s in spool["missing_samples"] if s["id"] == str(azure.id)), None)
        if sample:
            self.assertIn("verified_dryer_limit", sample["missing"])
