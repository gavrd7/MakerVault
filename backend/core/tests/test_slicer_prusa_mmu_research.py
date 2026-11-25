"""Native Prusa 2.9.7 MMU painting requires exact XML prefix and state.

These are research-only fixtures, not worker admission or printer approval.
"""
import io
from unittest import TestCase
import zipfile

from scripts.prusa_generate_mmu_paint import fixture, append_native_colour
from core.slicer_prusa_3mf import build_prusa_native_3mf


class PrusaResearchMmuFacetDialectTests(TestCase):
    def test_prusa_native_mmu_prefix_binds_second_logical_tool(self):
        _cube, painted, tags = fixture()
        row = {"asset_id": "verified", "x_mm": 0, "y_mm": 0, "z_mm": 0,
               "rotation_deg": 0, "scale_percent": 100}
        source = build_prusa_native_3mf([(row, painted)], bed_width=250, bed_depth=210)
        archive = append_native_colour(source, tags)
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            xml = z.read("3D/3dmodel.model")
        self.assertIn(b'xmlns:slic3rpe="http://schemas.slic3r.org/3mf/2017/06"', xml)
        self.assertIn(b'slic3rpe:mmu_segmentation="8"', xml)
        self.assertIn(b'name="slic3rpe:MmPaintingVersion"', xml)
        self.assertNotIn(b'ns1:mmu_segmentation', xml)
        self.assertNotIn(b'slic3rpe:mmu_segmentation="4"', xml)
