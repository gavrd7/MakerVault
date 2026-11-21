"""Regression checks for combined offline native paint and variable-layer exports."""
import io
import zipfile
from defusedxml import ElementTree as ET
from django.test import SimpleTestCase
from core.slicer_approval import fixture_stl
from core.slicer_plate_3mf import NS, _triangles, build_plate_3mf
from core.slicer_native_support_paint import _fingerprint
from core.slicer_profiles import SlicerProfileError


def _fixture():
    raw = fixture_stl()
    original = list(_triangles(raw))
    minimum = [min(p[i] for tri in original for p in tri) for i in range(3)]
    maximum = [max(p[i] for tri in original for p in tri) for i in range(3)]
    origin = ((minimum[0] + maximum[0])/2,
              (minimum[1] + maximum[1])/2, minimum[2])
    local = [[tuple(p[i] - origin[i] for i in range(3)) for p in tri]
             for tri in original]
    face = local[0]
    centre = [sum(point[i] for point in face)/3 for i in range(3)]
    patch = [[(point[i] + centre[i])/2 for i in range(3)] for point in face]
    return raw, _fingerprint(local), patch


class CombinedPaintNative3MFTests(SimpleTestCase):
    def test_three_overlapping_paints_and_layer_range_are_retained(self):
        raw, signature, patch = _fixture()
        def painted(slot):
            return {"version": 2, "signature": signature,
                    "regions": [{"slot": slot, "patches": [
                        {"face": 0, "polygon": patch}]}]}
        model = {
            "x_mm": 0, "y_mm": 0, "rotation_deg": 0,
            "rotation_xyz_deg": [0, 0], "scale_percent": 100,
            "support_paint": painted(0),
            "seam_paint": painted(1),
            "fuzzy_skin_paint": painted(0),
            "variable_layer_profile": {"version": 1, "bands": [
                {"from_mm": 1, "to_mm": 3, "layer_mm": 0.12}]},
        }
        result = build_plate_3mf([(model, raw)], bed_width=220, bed_depth=220)
        with zipfile.ZipFile(io.BytesIO(result)) as archive:
            xml = ET.fromstring(archive.read("3D/3dmodel.model"))
            ranges = ET.fromstring(archive.read("Metadata/layer_config_ranges.xml"))
        faces = xml.findall(".//{%s}triangle" % NS)
        self.assertGreater(len(faces), len(list(_triangles(raw))))
        self.assertTrue(any(all(face.attrib.get(k) == value for k, value in (
            ("paint_supports", "4"), ("paint_seam", "8"),
            ("paint_fuzzy_skin", "4"))) for face in faces))
        self.assertTrue(any(not any(key.startswith("paint_") for key in f.attrib)
                            for f in faces))
        self.assertEqual(ranges.find("object/range/option").text, "0.120")

    def test_out_of_date_mask_does_not_get_silently_dropped(self):
        raw, signature, patch = _fixture()
        def painted(sig):
            return {"version": 2, "signature": sig,
                    "regions": [{"slot": 0, "patches": [
                        {"face": 0, "polygon": patch}]}]}
        model = {
            "x_mm": 0, "y_mm": 0, "rotation_deg": 0,
            "scale_percent": 100,
            "support_paint": painted(signature),
            "fuzzy_skin_paint": painted("1:bad"),
        }
        with self.assertRaisesRegex(SlicerProfileError, "fingerprint"):
            build_plate_3mf([(model, raw)], bed_width=220, bed_depth=220)

    def test_same_channel_overlapping_patches_are_rejected(self):
        raw, signature, patch = _fixture()
        model = {
            "x_mm": 0, "y_mm": 0, "rotation_deg": 0,
            "scale_percent": 100,
            "support_paint": {"version": 2, "signature": signature,
                "regions": [{"slot": 0, "patches": [
                    {"face": 0, "polygon": patch},
                    {"face": 0, "polygon": patch}]}]},
            "fuzzy_skin_paint": {"version": 2, "signature": signature,
                "regions": [{"slot": 0, "patches": [
                    {"face": 0, "polygon": patch}]}]},
        }
        with self.assertRaisesRegex(SlicerProfileError, "Overlapping"):
            build_plate_3mf([(model, raw)], bed_width=220, bed_depth=220)
