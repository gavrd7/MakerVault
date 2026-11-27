"""Native Prusa 2.9.7 ranges must preserve requested layer limits and actual Z data."""
from unittest import TestCase

from core.slicer_prusa_layer_ranges import prusa_layer_config_ranges, audit_prusa_variable_layers


class PrusaNativeLayerRangeTests(TestCase):
    def test_multiple_object_ids_and_exact_native_range_xml(self):
        rows = [
            ({"variable_layer_profile": {"version": 1, "bands": [
                {"from_mm": 4, "to_mm": 16, "layer_mm": .12}]}}, b""),
            ({}, b""),
            ({"variable_layer_profile": {"version": 1, "bands": [
                {"from_mm": 6, "to_mm": 12, "layer_mm": .16}]}}, b""),
        ]
        xml = prusa_layer_config_ranges(rows).decode("utf-8")
        self.assertIn('<object id="1">', xml)
        self.assertIn('<object id="3">', xml)
        self.assertNotIn('<object id="2">', xml)
        self.assertIn('opt_key="layer_height">0.120', xml)
        self.assertIn('opt_key="layer_height">0.160', xml)
        self.assertEqual(prusa_layer_config_ranges([({}, b"")]), None)

    def test_reject_unverified_tilt_scale_elevation_and_bad_ranges(self):
        value = {"version": 1, "bands": [
            {"from_mm": 4, "to_mm": 16, "layer_mm": .12}]}
        for row in (
            {"variable_layer_profile": value, "rotation_xyz_deg": [15, 0]},
            {"variable_layer_profile": value, "scale_xyz_percent": [100, 100, 110]},
            {"variable_layer_profile": value, "z_mm": 3},
            {"variable_layer_profile": {"version": 1, "bands": [
                {"from_mm": 4, "to_mm": 16, "layer_mm": .9}]}},
        ):
            with self.subTest(row=row), self.assertRaises(ValueError):
                prusa_layer_config_ranges([(row, b"")])

    def test_audit_measures_real_layer_change_markers_not_z_hops(self):
        zs = [.2, .4, .6, .8, 1., 1.12, 1.24, 1.36, 1.48, 1.6]
        data = "; generated\n" + "".join(
            ";LAYER_CHANGE\n;Z:%.3f\nG1 X0 Y0 E1\n" % z for z in zs)
        self.assertEqual(audit_prusa_variable_layers(data, [
            {"from_mm": 1, "to_mm": 1.7, "layer_mm": .12}
        ])["verified_bands"][0]["verified_layers"], 3)
        with self.assertRaisesRegex(ValueError, "requested layer height"):
            audit_prusa_variable_layers(data, [
                {"from_mm": 1, "to_mm": 1.7, "layer_mm": .3}
            ])
