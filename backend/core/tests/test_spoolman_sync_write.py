"""Regression tests for read-before-write Spoolman sync decisions."""
from django.test import SimpleTestCase

from core.printing_sync import _spoolman_remote_matches_export


class SpoolmanExportDiffTests(SimpleTestCase):
    def setUp(self):
        self.remote = {
            "id": 15,
            "archived": False,
            "location": "Shelf A",
            "remaining_weight": 750.0,
            "comment": "PETG",
        }
        self.payload = {
            "archived": False,
            "location": "Shelf A",
            "remaining_weight": 750.00,
            "comment": "PETG",
        }

    def test_unchanged_export_is_skipped(self):
        self.assertTrue(_spoolman_remote_matches_export(self.remote, self.payload))

    def test_actual_changes_require_export(self):
        for field, replacement in (
            ("archived", True),
            ("location", "Shelf B"),
            ("remaining_weight", 700.00),
            ("comment", "New note"),
        ):
            with self.subTest(field=field):
                updated = dict(self.payload)
                updated[field] = replacement
                self.assertFalse(_spoolman_remote_matches_export(self.remote, updated))

    def test_missing_remote_or_missing_required_field_is_never_assumed_equal(self):
        self.assertFalse(_spoolman_remote_matches_export(None, self.payload))
        for field in ("archived", "location", "remaining_weight", "comment"):
            with self.subTest(field=field):
                remote = dict(self.remote)
                del remote[field]
                self.assertFalse(_spoolman_remote_matches_export(remote, self.payload))

    def test_optional_comment_is_not_exported_if_blank(self):
        payload = dict(self.payload)
        del payload["comment"]
        self.assertTrue(_spoolman_remote_matches_export(self.remote, payload))

    def test_remote_weight_rounding_does_not_force_new_write(self):
        remote = dict(self.remote)
        remote["remaining_weight"] = 750.001
        self.assertTrue(_spoolman_remote_matches_export(remote, self.payload))
