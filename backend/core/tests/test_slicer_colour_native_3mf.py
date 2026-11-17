"""Native Orca surface-colour 3MF conversion, offline only."""
import io
import zipfile
from types import SimpleNamespace
from defusedxml import ElementTree as ET
from django.test import SimpleTestCase

from core.slicer_approval import fixture_stl

PRINTER_ID = "11111111-1111-4111-8111-111111111111"
from core.slicer_native_support_paint import _fingerprint
from core.slicer_plate_3mf import NS, _triangles, build_plate_3mf
from core.slicer_native_material_palette import native_colour_tool_maps
from core.slicer_material_routing import MaterialRoutingError
from core.slicer_profiles import SlicerProfileError


def fixture_paint():
    raw = fixture_stl()
    original = list(_triangles(raw))
    lower = [min(point[axis] for tri in original for point in tri) for axis in range(3)]
    upper = [max(point[axis] for tri in original for point in tri) for axis in range(3)]
    origin = ((lower[0] + upper[0]) / 2, (lower[1] + upper[1]) / 2, lower[2])
    local = [[tuple(point[axis] - origin[axis] for axis in range(3))
              for point in tri] for tri in original]
    face = local[0]
    centre = [sum(point[axis] for point in face) / 3 for axis in range(3)]
    patch = [[(point[axis] + centre[axis]) / 2 for axis in range(3)]
             for point in face]
    swatches = [
        {"color": "#111111", "label": "Black", "printer_id": PRINTER_ID,
         "slot_id": "bay-1", "slot_index": 0},
        {"color": "#eeeeee", "label": "White", "printer_id": "printer",
         "slot_id": "bay-2", "slot_index": 1},
        {"color": "#123456", "label": "Blue", "printer_id": "printer",
         "slot_id": "bay-3", "slot_index": 2},
    ]
    painting = {"version": 2, "signature": _fingerprint(local),
                "palette": swatches, "regions": [{"slot": 2, "patches": [
                    {"face": 0, "polygon": patch}]}]}
    return raw, painting


class NativeColourRegionTests(SimpleTestCase):
    def test_region_preserves_unpainted_cells_and_exact_orca_tool_code(self):
        raw, painting = fixture_paint()
        item = {"x_mm": 0, "y_mm": 0, "rotation_deg": 0,
                "scale_percent": 100, "colour_paint": painting}
        maps = native_colour_tool_maps([item], printer_id=PRINTER_ID,
                                       tool_bindings={"bay-3": 2})
        self.assertEqual(maps, ({2: 2},))
        result = build_plate_3mf([(item, raw)], bed_width=220, bed_depth=220,
                                 native_tool_indices=[0], native_colour_tools=maps)
        with zipfile.ZipFile(io.BytesIO(result)) as archive:
            model = ET.fromstring(archive.read("3D/3dmodel.model"))
        faces = model.findall(".//{%s}triangle" % NS)
        self.assertGreater(len(faces), len(list(_triangles(raw))))
        self.assertTrue(any(face.attrib.get("paint_color") == "0C" for face in faces))
        self.assertTrue(any("paint_color" not in face.attrib for face in faces))

    def test_fails_closed_when_painted_swatch_has_no_tool(self):
        _raw, painting = fixture_paint()
        with self.assertRaisesRegex(MaterialRoutingError, "no verified native"):
            native_colour_tool_maps([{"colour_paint": painting}], printer_id="printer",
                                    tool_bindings={"bay-1": 0, "bay-2": 1})

    def test_fails_closed_on_wrong_printer(self):
        _raw, painting = fixture_paint()
        with self.assertRaisesRegex(MaterialRoutingError, "this printer"):
            native_colour_tool_maps([{"colour_paint": painting}], printer_id="other",
                                    tool_bindings={"bay-3": 2})

    def test_legacy_paint_is_not_silently_dropped(self):
        raw, painting = fixture_paint()
        legacy = {"version": 1, "signature": painting["signature"],
                  "palette": painting["palette"], "faces": {"0": 2}}
        item = {"x_mm": 0, "y_mm": 0, "rotation_deg": 0,
                "scale_percent": 100, "colour_paint": legacy}
        with self.assertRaisesRegex(MaterialRoutingError, "legacy"):
            native_colour_tool_maps([item], printer_id="printer",
                                    tool_bindings={"bay-3": 2})

    def test_annotated_model_rejects_unverified_paint_palette(self):
        raw, painting = fixture_paint()
        item = {"x_mm": 0, "y_mm": 0, "rotation_deg": 0,
                "scale_percent": 100, "colour_paint": painting}
        with self.assertRaisesRegex(SlicerProfileError, "verified native"):
            build_plate_3mf([(item, raw)], bed_width=220, bed_depth=220)
