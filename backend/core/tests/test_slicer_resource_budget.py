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


class EngineNeutralCapacityTests(SimpleTestCase):
    @patch.object(budget, "_host_available_bytes", return_value=8 * 1024**3)
    @patch.object(budget, "_cgroup_available_bytes", return_value=4 * 1024**3)
    def test_shared_model_and_output_budgets_follow_cgroup_memory(self, *_):
        memory = 4 * 1024**3
        reserve = 256 * MiB
        self.assertEqual(budget.input_model_budget(), (memory - reserve) // 8)
        self.assertEqual(budget.gcode_transport_budget(), (memory - reserve) // 6)
        self.assertEqual(budget.project_archive_budget(), (memory - reserve) // 8)
        self.assertEqual(budget.xml_geometry_budget(), (memory - reserve) // 12)
        self.assertEqual(budget.plate_triangle_budget(), (memory - reserve) // 1200)

    @patch.object(budget, "_host_available_bytes", return_value=16 * 1024**3)
    @patch.object(budget, "_cgroup_available_bytes", return_value=512 * MiB)
    def test_low_cgroup_headroom_rejects_large_jobs(self, *_):
        self.assertEqual(budget.input_model_budget(), 32 * MiB)
        self.assertEqual(budget.gcode_transport_budget(), (256 * MiB) // 6)
        self.assertEqual(budget.plate_triangle_budget(), (256 * MiB) // 1200)

    @patch.object(budget, "_host_available_bytes", return_value=None)
    @patch.object(budget, "_cgroup_available_bytes", return_value=None)
    def test_unknown_telemetry_does_not_claim_unlimited_slicing(self, *_):
        self.assertEqual(budget.input_model_budget(), 32 * MiB)
        self.assertEqual(budget.gcode_transport_budget(), 64 * MiB)
        self.assertIsNone(budget.resource_snapshot()["available_bytes"])


class PreparationWorkerTests(SimpleTestCase):
    @patch.object(budget, "_cpu_quota", return_value=2.5)
    @patch.object(budget.os, "sched_getaffinity", return_value=set(range(16)))
    def test_affinity_and_fractional_quota(self, *_):
        self.assertEqual(budget.effective_cpu_count(), 2)

    @patch.object(budget, "_cpu_quota", return_value=None)
    @patch.object(budget.os, "sched_getaffinity", return_value={0})
    def test_single_core(self, *_):
        self.assertEqual(budget.effective_cpu_count(), 1)

    @patch.object(budget, "resource_snapshot",
                  return_value={"available_bytes": 64 * 1024 * MiB})
    def test_scales_with_hardware_and_workload(self, _):
        for cpus, expected in ((1, 1), (2, 1), (4, 3), (16, 15), (32, 31)):
            with self.subTest(cpus=cpus), patch.object(
                    budget, "effective_cpu_count", return_value=cpus):
                self.assertEqual(budget.preparation_worker_count(
                    independent_tasks=100, bytes_per_worker=128 * MiB), expected)
        with patch.object(budget, "effective_cpu_count", return_value=32):
            self.assertEqual(budget.preparation_worker_count(
                independent_tasks=2, bytes_per_worker=128 * MiB), 2)
            self.assertEqual(budget.preparation_worker_count(
                independent_tasks=100, bytes_per_worker=128 * MiB,
                max_workers=4), 4)

    @patch.object(budget, "effective_cpu_count", return_value=32)
    def test_memory_pressure_and_unknown_telemetry(self, _):
        for memory in (None, 300 * MiB):
            with self.subTest(memory=memory), patch.object(
                    budget, "resource_snapshot",
                    return_value={"available_bytes": memory}):
                self.assertEqual(budget.preparation_worker_count(
                    independent_tasks=20, bytes_per_worker=128 * MiB), 1)

    def test_invalid_worker_parameters(self):
        for cap in (0, -1, True, "4"):
            with self.subTest(cap=cap), self.assertRaises(ValueError):
                budget.preparation_worker_count(
                    independent_tasks=4, bytes_per_worker=MiB, max_workers=cap)
