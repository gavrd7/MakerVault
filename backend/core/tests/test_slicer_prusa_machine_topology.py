"""Native Prusa topology is explicit; no MMU-to-XL conflation or printer writes."""
from unittest import TestCase
from core.slicer_prusa_machine_topology import (
    prusa_machine_topology, validate_prusa_model_tool_order,
)


def ini(nozzles, changer="0", **more):
    lines = ["printer_technology = FFF",
             "bed_shape = 0x0,250x0,250x210,0x210",
             "nozzle_diameter = " + nozzles,
             "binary_gcode = 0",
             "single_extruder_multi_material = " + changer]
    lines.extend("%s = %s" % (k, v) for k, v in more.items())
    return ("\n".join(lines)+"\n").encode()


class PrusaMachineTopologyTests(TestCase):
    def test_single_tool_mmu_and_independent_heads_are_distinct(self):
        single = prusa_machine_topology(ini("0.4"))
        self.assertEqual(single["kind"], "single_tool")
        self.assertEqual(single["physical_nozzle_count"], 1)
        mmu = prusa_machine_topology(ini(",".join(["0.4"]*5), "1"))
        self.assertEqual(mmu["kind"], "single_nozzle_changer")
        self.assertEqual(mmu["logical_tool_count"], 5)
        self.assertEqual(mmu["physical_nozzle_count"], 1)
        for n in (2, 5):
            with self.subTest(nozzles=n):
                xl = prusa_machine_topology(ini(",".join(["0.4"]*n)))
                self.assertEqual(xl["kind"], "independent_tools")
                self.assertEqual(xl["physical_nozzle_count"], n)

    def test_indx_six_to_eight_native_tools_have_explicit_assignments(self):
        for count in (6,7,8):
            with self.subTest(count=count):
                candidate=ini(",".join(["0.4"]*count))
                topology=prusa_machine_topology(candidate)
                self.assertEqual(topology["kind"],"indx")
                self.assertEqual(topology["physical_nozzle_count"],count)
                self.assertEqual(topology["logical_tool_count"],count)
                self.assertFalse(topology["requires_new_toolchanger_qualification"])
                result=validate_prusa_model_tool_order(candidate,[1,count])
                self.assertEqual(result["selected_tools"],(1,count))
        # The 8-tool generic parser is not authorisation for an MMU with
        # eight virtual materials or for a Prusa 2.9.7 INDX worker job.
        with self.assertRaises(ValueError):
            prusa_machine_topology(ini(",".join(["0.4"]*8),"1"))

    def test_explicit_native_tool_assignment_rejects_out_of_range(self):
        raw = ini("0.4,0.4,0.4,0.4,0.4", "1")
        result = validate_prusa_model_tool_order(raw, [1, 2])
        self.assertEqual(result["selected_tools"], (1, 2))
        self.assertEqual(result["physical_nozzle_count"], 1)
        for selected in ([1,1], [1,6], [0,1], [True,2], [1,2.0], [], [1,2]*100+[1]):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                validate_prusa_model_tool_order(raw, selected)

    def test_unsafe_or_unknown_native_topologies_rejected(self):
        for raw in (
            ini("0.4", "1"),
            ini("0.4,0.4", "unknown"),
            ini("0.4,NaN"),
            ini(",".join(["0.4"]*9)),
            ini(",".join(["0.4"]*8),"1"),
            ini("0.4,0.4", "0", binary_gcode="1"),
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                prusa_machine_topology(raw)
