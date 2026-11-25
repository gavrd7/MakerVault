from unittest import TestCase

from core.slicer_prusa_purge import compile_prusa_purge_matrix
from core.slicer_profiles import SlicerProfileError
from core.tests.test_slicer_prusa_machine_topology import ini


class PrusaPurgeMatrixTests(TestCase):
    def test_directional_order_and_immutable_process(self):
        original = b"layer_height = 0.2\nwipe_tower = 0\nwipe_into_infill = 1\n"
        result = compile_prusa_purge_matrix(
            ini("0.4,0.4", "1"), original, [[0,120],[240,0]])
        self.assertIn(b"wiping_volumes_matrix = 0,120,240,0\n", result)
        self.assertIn(b"wipe_tower = 1\n", result)
        self.assertIn(b"wipe_into_infill = 0\n", result)
        self.assertIn(b"wipe_into_objects = 0\n", result)
        self.assertIn(b"wipe_tower = 0\n", original)

    def test_mmu_count_is_logical_not_physical(self):
        printer = ini("0.4,0.4,0.4,0.4,0.4", "1")
        matrix = [[0 if i == j else 50 + i*10+j for j in range(5)] for i in range(5)]
        result = compile_prusa_purge_matrix(printer, b"layer_height = 0.2\n", matrix)
        line = next(x for x in result.splitlines() if x.startswith(b"wiping_volumes_matrix"))
        self.assertEqual(len(line.split(b"=",1)[1].split(b",")),25)

    def test_invalid_matrix_is_rejected(self):
        printer = ini("0.4,0.4","0")
        for matrix in ([[0,1]], [[0,1],[1]], [[1,50],[50,0]],
                       [[0,0],[50,0]], [[0,True],[50,0]], [[0,float("inf")],[50,0]],
                       [[0,1001],[50,0]], [[0,-1],[50,0]]):
            with self.subTest(matrix=matrix), self.assertRaises(SlicerProfileError):
                compile_prusa_purge_matrix(printer,b"layer_height = 0.2\n",matrix)
