import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.catalogue_enrichment import _slug_candidates, _tokens


class DummyManufacturer:
    name = "Seeed Studio"


class DummyBoard:
    name = "XIAO ESP32C6"
    manufacturer = DummyManufacturer()


class CatalogueEnrichmentTests(unittest.TestCase):
    def test_slug_candidates_include_plain_board_name(self):
        self.assertIn("xiao-esp32c6", _slug_candidates(DummyBoard()))

    def test_token_matching_ignores_generic_words(self):
        self.assertEqual(_tokens("Generic ESP32-S3 Super Mini board"), {"esp32", "s3", "super"})
        self.assertTrue({"esp32", "c6"}.issubset(_tokens("Seeed Studio XIAO ESP32C6")))


class BoardBatchProgressTests(unittest.TestCase):
    def test_bounded_runs_visit_all_boards_and_wrap_without_duplicates(self):
        from core.catalogue_enrichment import run_board_catalogue_enrichment

        class FakeCache:
            def __init__(self):
                self.store = {}

            def add(self, key, value, timeout=None):
                if key in self.store:
                    return False
                self.store[key] = value
                return True

            def get(self, key):
                return self.store.get(key)

            def set(self, key, value, timeout=None):
                self.store[key] = value

            def delete(self, key):
                self.store.pop(key, None)

        class FakeQuerySet:
            def __init__(self, items):
                self.items = items

            def order_by(self, *args):
                return self

            def filter(self, **kwargs):
                return FakeQuerySet([b for b in self.items if b.id > int(kwargs["id__gt"])])

            def exists(self):
                return bool(self.items)

            def __getitem__(self, item):
                return self.items[item]

            def iterator(self):
                return iter(self.items)

        seen = []
        boards = [SimpleNamespace(id=i, name=f"Board {i}") for i in range(1, 104)]
        queryset = FakeQuerySet(boards)
        memory_cache = FakeCache()
        with (
            patch("core.catalogue_enrichment.cache", memory_cache),
            patch("core.models.BoardModel.objects") as objects,
            patch("core.catalogue_enrichment._is_esp_family", return_value=False),
            patch("core.catalogue_enrichment.enrich_board_from_profile", side_effect=lambda board: seen.append(board.id) or False),
            patch("core.catalogue_enrichment.update_board_enrichment_state", return_value=False),
        ):
            objects.select_related.return_value = queryset
            first = run_board_catalogue_enrichment(limit=80)
            second = run_board_catalogue_enrichment(limit=80)
            third = run_board_catalogue_enrichment(limit=80)

        self.assertEqual((first["status"], first["processed"]), ("limit-reached", 80))
        self.assertEqual((second["status"], second["processed"]), ("complete", 23))
        self.assertEqual((third["status"], third["processed"]), ("limit-reached", 80))
        self.assertEqual(seen[:103], list(range(1, 104)))
        self.assertEqual(seen[103:], list(range(1, 81)))


class BoardContinuationTaskTests(unittest.TestCase):
    def test_limit_reached_queues_next_batch_without_force_retry(self):
        from core.tasks import enrich_board_catalogue_task

        with (
            patch("core.tasks.backup_in_progress", return_value=False),
            patch("core.tasks.run_board_catalogue_enrichment",
                  return_value={"status": "limit-reached", "processed": 80}) as run,
            patch.object(enrich_board_catalogue_task, "apply_async") as queue,
        ):
            result = enrich_board_catalogue_task(limit=80, force_retry=True)

        self.assertEqual(result["status"], "limit-reached")
        run.assert_called_once_with(limit=80, force_retry=True)
        queue.assert_called_once_with(
            kwargs={"limit": 80, "force_retry": False}, countdown=5,
        )

    def test_complete_and_empty_batches_do_not_requeue(self):
        from core.tasks import enrich_board_catalogue_task

        for result in (
            {"status": "complete", "processed": 23},
            {"status": "already-running", "processed": 0},
            {"status": "limit-reached", "processed": 0},
        ):
            with (
                self.subTest(result=result),
                patch("core.tasks.backup_in_progress", return_value=False),
                patch("core.tasks.run_board_catalogue_enrichment", return_value=result),
                patch.object(enrich_board_catalogue_task, "apply_async") as queue,
            ):
                self.assertEqual(enrich_board_catalogue_task(limit=80), result)
                queue.assert_not_called()

    def test_backup_in_progress_does_not_run_or_requeue(self):
        from core.tasks import enrich_board_catalogue_task

        with (
            patch("core.tasks.backup_in_progress", return_value=True),
            patch("core.tasks.run_board_catalogue_enrichment") as run,
            patch.object(enrich_board_catalogue_task, "apply_async") as queue,
        ):
            result = enrich_board_catalogue_task(limit=80)

        self.assertEqual(result["status"], "backup-in-progress")
        run.assert_not_called()
        queue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
