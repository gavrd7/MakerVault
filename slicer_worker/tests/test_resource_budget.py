import unittest
from unittest.mock import patch
from slicer_worker import resource_budget


class SharedWorkerResourceBudgetTests(unittest.TestCase):
    @patch.object(resource_budget, "memory_headroom", return_value=2*1024**3)
    def test_memory_budget_is_operation_defined_not_engine_defined(self, _headroom):
        self.assertEqual(
            resource_budget.operation_memory_budget(
                reserve_bytes=256*1024**2, expansion_factor=4),
            (2*1024**3 - 256*1024**2) // 4)

    @patch.object(resource_budget, "memory_headroom", return_value=None)
    def test_unmeasured_resources_fail_closed(self, _headroom):
        self.assertIsNone(resource_budget.operation_memory_budget(
            reserve_bytes=0, expansion_factor=1))

    @patch.object(resource_budget, "scratch_disk_headroom", return_value=4*1024**3)
    @patch.object(resource_budget, "memory_headroom", return_value=2*1024**3)
    def test_admission_requires_both_disk_and_ram(self, *_):
        self.assertTrue(resource_budget.admit_working_set(
            memory_bytes=512*1024**2, scratch_bytes=1024**3))
        self.assertFalse(resource_budget.admit_working_set(
            memory_bytes=2*1024**3, scratch_bytes=1024**3))
        self.assertFalse(resource_budget.admit_working_set(
            memory_bytes=512*1024**2, scratch_bytes=4*1024**3))

    def test_invalid_operation_cost_is_rejected(self):
        with self.assertRaises(ValueError):
            resource_budget.operation_memory_budget(
                reserve_bytes=-1, expansion_factor=8)
        with self.assertRaises(ValueError):
            resource_budget.admit_working_set(
                memory_bytes=-1)
