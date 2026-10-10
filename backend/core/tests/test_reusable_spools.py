from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from core.models import ReusableSpoolDesign, ReusableSpool, Spool


class ReusableSpoolModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user(username="reel-owner", password="example-test-password")
        cls.other = get_user_model().objects.create_user(username="reel-other", password="example-test-password")

    def test_multiple_instances_share_design_with_distinct_measured_weights(self):
        design = ReusableSpoolDesign.objects.create(
            owner=self.owner, name="Printed refill spool", nominal_tare_g=Decimal("175.00")
        )
        first = ReusableSpool(owner=self.owner, design=design, code="RS-1")
        first.full_clean()
        first.save()
        second = ReusableSpool(owner=self.owner, design=design, code="RS-2", measured_tare_g=Decimal("182.15"))
        second.full_clean()
        second.save()
        self.assertEqual(first.effective_tare_g, Decimal("175.00"))
        self.assertEqual(second.effective_tare_g, Decimal("182.15"))

    def test_other_users_design_cannot_be_attached(self):
        design = ReusableSpoolDesign.objects.create(owner=self.other, name="Another user's reel")
        reel = ReusableSpool(owner=self.owner, design=design, code="RS-3")
        with self.assertRaises(ValidationError):
            reel.full_clean()

    def test_unverified_drying_temperature_is_rejected(self):
        design = ReusableSpoolDesign(owner=self.owner, name="Printed reel", max_dryer_temp_c=65)
        with self.assertRaises(ValidationError):
            design.full_clean()

    def test_negative_tare_is_rejected(self):
        design = ReusableSpoolDesign.objects.create(owner=self.owner, name="Empty spool")
        reel = ReusableSpool(owner=self.owner, design=design, code="RS-4", measured_tare_g=-1)
        with self.assertRaises(ValidationError):
            reel.full_clean()


class ReusableSpoolApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_superuser(
            username="reel-admin-owner", email="owner@example.test", password="example-test-password",
        )
        cls.other = get_user_model().objects.create_superuser(
            username="reel-admin-other", email="other@example.test", password="example-test-password",
        )

    def setUp(self):
        self.client.force_login(self.owner)

    def _post(self, path, data):
        import json
        return self.client.post(path, data=json.dumps(data), content_type="application/json")

    def _patch(self, path, data):
        import json
        return self.client.patch(path, data=json.dumps(data), content_type="application/json")

    def test_create_design_and_reel_with_tare_override(self):
        design_response = self._post("/api/printing/reusable-spool-designs/", {
            "name": "Manufacturer refill spool", "design_type": "manufacturer", "nominal_tare_g": "176.50",
        })
        self.assertEqual(design_response.status_code, 201, design_response.content)
        design_id = design_response.json()["item"]["id"]
        reel_response = self._post("/api/printing/reusable-spools/", {
            "code": "REEL-100", "design_id": design_id, "measured_tare_g": "180.25", "color_name": "Orange",
        })
        self.assertEqual(reel_response.status_code, 201, reel_response.content)
        self.assertEqual(reel_response.json()["item"]["effective_tare_g"], "180.25")
        get_response = self.client.get("/api/printing/reusable-spools/")
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(len(get_response.json()["rows"]), 1)

    def test_reject_other_users_design_and_hide_other_users_records(self):
        foreign_design = ReusableSpoolDesign.objects.create(owner=self.other, name="Private")
        response = self._post("/api/printing/reusable-spools/", {
            "code": "REEL-101", "design_id": str(foreign_design.id),
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/api/printing/reusable-spool-designs/").json()["rows"], [])
        self.assertEqual(
            self._patch("/api/printing/reusable-spool-designs/" + str(foreign_design.id) + "/", {"name": "Hacked"}).status_code,
            404,
        )

    def test_same_filament_stock_cannot_be_assigned_twice(self):
        from core.models import FilamentProduct
        filament = FilamentProduct.objects.create(name="PLA", material="PLA")
        stock = Spool.objects.create(owner=self.owner, spool_id="SP-101", filament=filament)
        design = ReusableSpoolDesign.objects.create(owner=self.owner, name="Reusable reel")
        first = self._post("/api/printing/reusable-spools/", {
            "code": "R-1", "design_id": str(design.id), "filament_spool_id": str(stock.id),
        })
        self.assertEqual(first.status_code, 201, first.content)
        second = self._post("/api/printing/reusable-spools/", {
            "code": "R-2", "design_id": str(design.id), "filament_spool_id": str(stock.id),
        })
        self.assertEqual(second.status_code, 400)
        self.assertEqual(ReusableSpool.objects.filter(owner=self.owner).count(), 1)

    def test_reel_can_unlink_stock_without_deleting_it(self):
        from core.models import FilamentProduct
        filament = FilamentProduct.objects.create(name="PLA", material="PLA")
        stock = Spool.objects.create(owner=self.owner, spool_id="SP-102", filament=filament)
        design = ReusableSpoolDesign.objects.create(owner=self.owner, name="Reusable reel")
        reel = ReusableSpool.objects.create(owner=self.owner, code="R-3", design=design, filament_spool=stock)
        response = self._patch("/api/printing/reusable-spools/" + str(reel.id) + "/", {"filament_spool_id": ""})
        self.assertEqual(response.status_code, 200, response.content)
        reel.refresh_from_db()
        self.assertIsNone(reel.filament_spool_id)
        self.assertTrue(Spool.objects.filter(pk=stock.pk).exists())
