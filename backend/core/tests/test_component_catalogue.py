from unittest.mock import patch

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


class VerifiedComponentReferenceTests(TestCase):
    def test_exact_part_number_enriched_without_changing_existing_metadata(self):
        from core.component_reference_enrichment import enrich_component_reference_links
        item = ComponentModel.objects.create(
            name="LM358 dual operational amplifier", part_number="LM358",
            specifications={"type": "op-amp"},
        )
        result = enrich_component_reference_links()
        item.refresh_from_db()
        self.assertEqual(result["enriched"], 1)
        self.assertEqual(item.specifications["reference_url"], "https://www.ti.com/product/LM358")
        self.assertEqual(item.specifications["type"], "op-amp")
        self.assertEqual(enrich_component_reference_links()["enriched"], 0)

    def test_generic_and_existing_references_are_never_modified(self):
        from core.component_reference_enrichment import enrich_component_reference_links
        generic = ComponentModel.objects.create(name="Generic resistor", specifications={})
        manual = ComponentModel.objects.create(
            name="LM393 comparator", part_number="LM393",
            specifications={"reference_url": "https://example.com/manual"},
        )
        enrich_component_reference_links()
        generic.refresh_from_db()
        manual.refresh_from_db()
        self.assertNotIn("reference_url", generic.specifications)
        self.assertEqual(manual.specifications["reference_url"], "https://example.com/manual")


    def test_expanded_family_references_cover_multiple_manufacturers(self):
        from core.component_reference_enrichment import (
            VERIFIED_FAMILY_REFERENCES,
            enrich_component_reference_links,
        )
        expected = {
            "INA219": "https://www.ti.com/product/INA219",
            "MCP23017": "https://www.microchip.com/en-us/product/mcp23017",
            "VL53L0X": "https://www.st.com/en/imaging-and-photonics-solutions/vl53l0x.html",
        }
        self.assertGreaterEqual(len(VERIFIED_FAMILY_REFERENCES), 9)
        self.assertTrue(all(VERIFIED_FAMILY_REFERENCES[k] == v for k, v in expected.items()))
        for part in expected:
            ComponentModel.objects.create(
                name=f"{part} generic module", part_number=part,
                specifications={"existing_note": "Preserve me"},
            )
        result = enrich_component_reference_links()
        self.assertEqual(result["enriched"], 3)
        for part, link in expected.items():
            item = ComponentModel.objects.get(part_number=part)
            self.assertEqual(item.specifications["reference_url"], link)
            self.assertEqual(item.specifications["existing_note"], "Preserve me")
            self.assertEqual(
                item.specifications["reference_match_type"], "exact-part-number-family"
            )

    def test_batched_reference_sweep_visits_remaining_records(self):
        from core.component_reference_enrichment import enrich_component_reference_links
        import uuid
        for index in range(103):
            ComponentModel.objects.create(
                id=uuid.UUID(int=index + 1),
                name=f"Fixture {index}",
                part_number="LM358" if index == 102 else "",
            )
        first = enrich_component_reference_links(limit=80)
        second = enrich_component_reference_links(limit=80, cursor=first["next_cursor"])
        self.assertEqual((first["status"], first["processed"]), ("limit-reached", 80))
        self.assertEqual((second["status"], second["processed"]), ("complete", 23))
        self.assertEqual(first["enriched"] + second["enriched"], 1)


    def test_verified_technical_fields_are_fill_only_and_sourced(self):
        from core.component_reference_enrichment import enrich_component_reference_links
        component = ComponentModel.objects.create(
            name="MCP23017 I/O expander", part_number="MCP23017",
            specifications={"interface": "User custom", "note": "Keep me"},
        )
        result = enrich_component_reference_links()
        component.refresh_from_db()
        self.assertEqual(result["enriched"], 1)
        self.assertEqual(component.specifications["interface"], "User custom")
        self.assertEqual(component.specifications["gpio_count"], 16)
        self.assertEqual(component.specifications["technical_field_sources"]["gpio_count"],
                         "https://www.microchip.com/en-us/product/mcp23017")
        self.assertEqual(component.specifications["note"], "Keep me")
        self.assertEqual(enrich_component_reference_links()["enriched"], 0)

    def test_family_chip_specs_do_not_transfer_to_breakout_modules(self):
        from core.component_reference_enrichment import enrich_component_reference_links
        component = ComponentModel.objects.create(
            name="VL53L0X breakout module", part_number="VL53L0X",
            specifications={"type": "sensor"},
        )
        enrich_component_reference_links()
        component.refresh_from_db()
        self.assertNotIn("maximum_range_m", component.specifications)
        self.assertNotIn("interface", component.specifications)

    def test_verified_sensor_range_from_manufacturer_is_recorded(self):
        from core.component_reference_enrichment import enrich_component_reference_links
        component = ComponentModel.objects.create(
            name="VL53L0X ranging sensor IC", part_number="VL53L0X",
            specifications={},
        )
        enrich_component_reference_links()
        component.refresh_from_db()
        self.assertEqual(component.specifications["maximum_range_m"], 2)
        self.assertEqual(component.specifications["interface"], "I2C")


class ComponentSweepRetryTests(TestCase):
    @patch("core.tasks.backup_in_progress", return_value=False)
    @patch("core.tasks.enrich_component_reference_links", side_effect=RuntimeError("temporary failure"))
    @patch("core.tasks.enrich_component_references_task.apply_async")
    def test_transient_failure_retries_same_cursor_with_backoff(self, enqueue, enrich, backup):
        from core.tasks import enrich_component_references_task
        first = enrich_component_references_task(limit=80, cursor="sample-cursor", retry_attempt=0)
        self.assertEqual(first["status"], "retry-scheduled")
        self.assertEqual(enqueue.call_args.kwargs["countdown"], 60)
        self.assertEqual(enqueue.call_args.kwargs["kwargs"]["cursor"], "sample-cursor")
        second = enrich_component_references_task(limit=80, cursor="sample-cursor", retry_attempt=1)
        self.assertEqual(second["status"], "retry-scheduled")
        self.assertEqual(enqueue.call_args.kwargs["countdown"], 120)
        self.assertEqual(enqueue.call_count, 2)

    @patch("core.tasks.backup_in_progress", return_value=False)
    @patch("core.tasks.enrich_component_reference_links", side_effect=RuntimeError("provider down"))
    @patch("core.tasks.enrich_component_references_task.apply_async")
    def test_retries_stop_after_two_attempts(self, enqueue, enrich, backup):
        from core.tasks import enrich_component_references_task
        result = enrich_component_references_task(limit=80, retry_attempt=2)
        self.assertEqual(result["status"], "error")
        enqueue.assert_not_called()

    @patch("core.tasks.backup_in_progress", return_value=False)
    @patch("core.tasks.enrich_component_reference_links", return_value={
        "status": "limit-reached", "processed": 80, "next_cursor": "next-cursor",
    })
    @patch("core.tasks.enrich_component_references_task.apply_async")
    def test_successful_batch_resets_retry_budget(self, enqueue, enrich, backup):
        from core.tasks import enrich_component_references_task
        enrich_component_references_task(limit=80, retry_attempt=2)
        self.assertEqual(enqueue.call_args.kwargs["kwargs"]["retry_attempt"], 0)
        self.assertEqual(enqueue.call_args.kwargs["kwargs"]["cursor"], "next-cursor")
