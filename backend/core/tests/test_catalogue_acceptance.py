"""Offline release gates for the real shared starter catalogues.

Unlike fixture-only tests, these use the unmodified starter definitions and a
fresh Django test database. No external vendor services are contacted.
"""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from core.catalogue_seed import BOARD_DEFINITIONS, COMPONENT_DEFINITIONS
from core.models import BoardModel, ComponentModel


class FreshCatalogueAcceptanceTests(TestCase):
    def test_real_seed_is_idempotent_and_preserves_manual_values(self):
        output = StringIO()
        call_command("seed_catalogue", stdout=output)
        self.assertEqual(BoardModel.objects.count(), len(BOARD_DEFINITIONS))
        self.assertEqual(ComponentModel.objects.count(), len(COMPONENT_DEFINITIONS))
        first_board = BoardModel.objects.select_related("manufacturer").first()
        first_component = ComponentModel.objects.first()
        original_board_pk = first_board.pk
        original_component_pk = first_component.pk

        first_board.description = "Custom user board description"
        first_board.specifications = {
            **(first_board.specifications or {}),
            "custom_manual_field": "retain this",
        }
        first_board.save(update_fields=["description", "specifications", "updated_at"])
        first_component.description = "Custom user component description"
        first_component.specifications = {
            **(first_component.specifications or {}),
            "custom_manual_field": "retain component value",
        }
        first_component.save(update_fields=["description", "specifications", "updated_at"])

        # Simulates a second startup with the same database and seed definitions.
        call_command("seed_catalogue", stdout=StringIO())
        self.assertEqual(BoardModel.objects.count(), len(BOARD_DEFINITIONS))
        self.assertEqual(ComponentModel.objects.count(), len(COMPONENT_DEFINITIONS))
        first_board.refresh_from_db()
        first_component.refresh_from_db()
        self.assertEqual(first_board.pk, original_board_pk)
        self.assertEqual(first_component.pk, original_component_pk)
        self.assertEqual(first_board.description, "Custom user board description")
        self.assertEqual(first_component.description, "Custom user component description")
        self.assertEqual(first_board.specifications["custom_manual_field"], "retain this")
        self.assertEqual(first_component.specifications["custom_manual_field"], "retain component value")

    def test_coverage_report_uses_fresh_actual_catalogue_records(self):
        call_command("seed_catalogue", stdout=StringIO())
        from core.catalogue_coverage import catalogue_coverage_summary
        summary = catalogue_coverage_summary()
        self.assertGreaterEqual(summary["records"], len(BOARD_DEFINITIONS) + len(COMPONENT_DEFINITIONS))
        by_label = {entry["label"]: entry for entry in summary["catalogues"]}
        self.assertEqual(by_label["Board catalogue"]["total"], len(BOARD_DEFINITIONS))
        self.assertEqual(by_label["Components"]["total"], len(COMPONENT_DEFINITIONS))
        for entry in summary["catalogues"]:
            for metric in entry["metrics"]:
                self.assertGreaterEqual(metric["complete"], 0)
                self.assertGreaterEqual(metric["missing"], 0)
                self.assertGreaterEqual(metric["percent"], 0)
                self.assertLessEqual(metric["percent"], 100)
