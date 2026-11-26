"""Admission uses host/container memory headroom, never filenames or RAM alone."""
from unittest.mock import patch

from django.test import SimpleTestCase

from core import slicer_resource_budget as budget

MiB = 1024 * 1024


class SourceInputBudgetTests(SimpleTestCase):
    @patch.object(budget, "_host_available_bytes", return_value=None)
    @patch.object(budget, "_cgroup_available_bytes", return_value=None)
    def test_unknown_memory_retains_historical_48mib_budget(self, *_):
        self.assertEqual(budget.source_input_budget(upper_cap=128 * MiB),
                         48 * MiB)

    @patch.object(budget, "_host_available_bytes", return_value=16 * 1024 * MiB)
    @patch.object(budget, "_cgroup_available_bytes", return_value=2 * 1024 * MiB)
    def test_container_limit_takes_precedence_over_host_memory(self, *_):
        self.assertEqual(budget.source_input_budget(upper_cap=128 * MiB),
                         128 * MiB)

    @patch.object(budget, "_host_available_bytes", return_value=1024 * MiB)
    @patch.object(budget, "_cgroup_available_bytes", return_value=None)
    def test_host_headroom_limits_increase(self, *_):
        self.assertEqual(budget.source_input_budget(upper_cap=128 * MiB),
                         96 * MiB)

    @patch.object(budget, "_host_available_bytes", return_value=16 * 1024 * MiB)
    @patch.object(budget, "_cgroup_available_bytes", return_value=300 * MiB)
    def test_low_container_memory_pressure_reduces_admission(self, *_):
        self.assertEqual(budget.source_input_budget(upper_cap=128 * MiB),
                         8 * MiB)

    @patch.object(budget, "_host_available_bytes", return_value=16 * 1024 * MiB)
    @patch.object(budget, "_cgroup_available_bytes", return_value=16 * 1024 * MiB)
    def test_upper_cap_still_applies_even_with_abundant_ram(self, *_):
        self.assertEqual(budget.source_input_budget(upper_cap=50 * MiB),
                         50 * MiB)

    @patch.object(budget, "_host_available_bytes", return_value=None)
    @patch.object(budget, "_cgroup_available_bytes", return_value=None)
    def test_injected_small_ceiling_still_applies_to_unknown_memory(self, *_):
        self.assertEqual(budget.source_input_budget(upper_cap=100),
                         100)

    def test_invalid_upper_cap_is_rejected(self):
        for value in (0, -1, True, "128", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                budget.source_input_budget(upper_cap=value)

    @patch.object(budget, "_read_number", side_effect=[1024, 256])
    def test_cgroup_v2_memory_remaining_is_determined_from_usage(self, read):
        self.assertEqual(budget._cgroup_available_bytes(), 768)
        self.assertEqual(read.call_count, 2)

    @patch.object(budget, "_read_number", side_effect=[None, None, 2048, 1000])
    def test_cgroup_v1_fallback_is_supported(self, read):
        self.assertEqual(budget._cgroup_available_bytes(), 1048)
        self.assertEqual(read.call_count, 4)

    @patch.object(budget, "_read_number", side_effect=[None, None, None, None])
    def test_unlimited_cgroup_resorts_to_host_budget(self, read):
        self.assertIsNone(budget._cgroup_available_bytes())
