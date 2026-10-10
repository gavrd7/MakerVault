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
