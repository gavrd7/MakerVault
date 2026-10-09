from django.contrib.auth import get_user_model
from django.test import TestCase

from core.catalogue_seed import COMPONENT_DEFINITIONS
from core.models import ComponentCategory, ComponentModel


class ComponentCatalogueManufacturerRemovalTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="component-admin",
            email="components@example.com",
            password="test-password",
        )
        self.client.force_login(self.user)

    def test_component_model_no_longer_has_manufacturer_field(self):
        field_names = {field.name for field in ComponentModel._meta.get_fields()}
        self.assertNotIn("manufacturer", field_names)

    def test_starter_component_dataset_has_no_manufacturer_metadata(self):
        self.assertTrue(COMPONENT_DEFINITIONS)
        self.assertTrue(all("manufacturer" not in row for row in COMPONENT_DEFINITIONS))

    def test_component_api_creates_and_serialises_without_manufacturer(self):
        response = self.client.post(
            "/api/components/",
            data={
                "manufacturer": "Ignored legacy value",
                "category": "Passives",
                "name": "47k ohm resistor",
                "part_number": "",
                "description": "Generic passive component",
                "specifications": {
                    "type": "resistor",
                    "value": "47 kΩ",
                    "power": "0.25 W",
                },
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        component = response.json()["component"]
        self.assertNotIn("manufacturer", component)
        self.assertEqual(component["name"], "47k ohm resistor")
        self.assertEqual(component["category"], "Passives")

        stored = ComponentModel.objects.get(pk=component["id"])
        self.assertEqual(stored.category.name, "Passives")

        listing = self.client.get("/api/components/?q=47k")
        self.assertEqual(listing.status_code, 200, listing.content)
        self.assertEqual(len(listing.json()["rows"]), 1)
        self.assertNotIn("manufacturer", listing.json()["rows"][0])

    def test_category_search_remains_available_without_manufacturer_search(self):
        category = ComponentCategory.objects.create(name="LEDs & Lighting", slug="leds-lighting-test")
        ComponentModel.objects.create(
            category=category,
            name="5mm amber LED",
            part_number="",
            specifications={"type": "led", "colour": "amber"},
        )

        response = self.client.get("/api/components/?q=lighting")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual([row["name"] for row in response.json()["rows"]], ["5mm amber LED"])

    def test_component_coverage_distinguishes_generic_and_sourced_parts(self):
        from core.catalogue_coverage import _component_coverage

        category = ComponentCategory.objects.create(name="Test components", slug="test-components")
        ComponentModel.objects.create(
            category=category, name="10k resistor", part_number="",
        )
        ComponentModel.objects.create(
            category=category, name="Identifiable IC", part_number="LM358",
        )
        result = _component_coverage()
        self.assertEqual(result["diagnostics"]["generic_without_part_number"], 1)
        self.assertEqual(result["diagnostics"]["identifiable_without_authoritative_source"], 1)
