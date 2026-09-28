from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from core.models import ComponentModel, Manufacturer


class GenericComponentCatalogueTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="component-admin",
            email="components@example.com",
            password="test-password",
        )
        self.client.force_login(self.user)

    def test_component_model_has_no_manufacturer_field(self):
        field_names = {field.name for field in ComponentModel._meta.get_fields()}
        self.assertNotIn("manufacturer", field_names)

    def test_component_create_ignores_legacy_manufacturer_payload(self):
        response = self.client.post(
            "/api/components/",
            data={
                "manufacturer": "Legacy Component Brand",
                "category": "LEDs & Lighting",
                "name": "5mm amber LED",
                "part_number": "",
                "description": "Generic LED",
                "specifications": {
                    "type": "led",
                    "colour": "amber",
                    "package": "5 mm through-hole",
                },
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()["component"]
        self.assertNotIn("manufacturer", payload)
        self.assertEqual(payload["name"], "5mm amber LED")
        self.assertEqual(payload["category"], "LEDs & Lighting")
        self.assertFalse(
            Manufacturer.objects.filter(name="Legacy Component Brand").exists()
        )

    def test_starter_catalogue_tolerates_existing_duplicate_component_identity(self):
        ComponentModel.objects.create(name="220 ohm resistor", part_number="")
        ComponentModel.objects.create(name="220 ohm resistor", part_number="")

        call_command("seed_catalogue")

        self.assertEqual(
            ComponentModel.objects.filter(
                name="220 ohm resistor",
                part_number="",
            ).count(),
            2,
        )

    def test_starter_catalogue_does_not_create_component_brand_manufacturers(self):
        call_command("seed_catalogue")
        self.assertTrue(ComponentModel.objects.filter(name__icontains="BME280").exists())
        self.assertFalse(Manufacturer.objects.filter(name="Bosch").exists())
        self.assertFalse(Manufacturer.objects.filter(name="Texas Instruments").exists())
