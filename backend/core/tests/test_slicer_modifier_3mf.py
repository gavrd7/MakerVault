"""Structural BBS-family modifier fixtures (not real-engine acceptance)."""
import io
import uuid
import zipfile
from defusedxml import ElementTree as ET
from django.test import SimpleTestCase

from core.slicer_approval import fixture_stl
from core.slicer_modifier_3mf import export_modifier_3mf_fixture
from core.slicer_plate_3mf import NS
from core.slicer_profiles import SlicerProfileError


def item(shape="box", *, x=0, y=0, z=5, infill=50):
    return {
        "instance_id": str(uuid.uuid4()), "asset_id": str(uuid.uuid4()),
        "x_mm": 0, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100,
        "color": "#00aaff",
        "modifier_volumes": [{
            "id": str(uuid.uuid4()), "shape": shape,
            "width_mm": 7, "depth_mm": 7, "height_mm": 7,
            "x_mm": x, "y_mm": y, "z_mm": z,
            "settings": {"sparse_infill_density": infill},
        }],
    }


class NativeModifierProjectTests(SimpleTestCase):
    def test_modifier_is_nonprinting_child_with_native_metadata_for_each_shape(self):
        for shape in ("box", "cylinder", "sphere", "cone", "disc", "torus"):
            with self.subTest(shape=shape):
                output = export_modifier_3mf_fixture(
                    [(item(shape), fixture_stl())], bed_width=220, bed_depth=220)
                with zipfile.ZipFile(io.BytesIO(output)) as archive:
                    root = ET.fromstring(archive.read("3D/3dmodel.model"))
                    manifest = ET.fromstring(archive.read("Metadata/model_settings.config"))
                ns = "{" + NS + "}"
                build = root.findall(f"./{ns}build/{ns}item")
                self.assertEqual(len(build), 1, "Modifiers must never create plate items")
                parent = root.find(f"./{ns}resources/{ns}object[@id='1']")
                children = parent.findall(f"./{ns}components/{ns}component")
                self.assertEqual(len(children), 2)
                self.assertEqual(build[0].attrib["objectid"], "1")
                native_parts = manifest.findall("./object[@id='1']/part")
                self.assertEqual([p.attrib["subtype"] for p in native_parts],
                                 ["normal_part", "modifier_part"])
                modifier_id = children[1].attrib["objectid"]
                self.assertEqual(native_parts[1].attrib["id"], modifier_id)
                attrs = {m.attrib["key"]: m.attrib["value"]
                         for m in native_parts[1].findall("metadata")}
                self.assertEqual(attrs["sparse_infill_density"], "50.0%")
                mesh = root.find(f"./{ns}resources/{ns}object[@id='{modifier_id}']/{ns}mesh")
                self.assertIsNotNone(mesh)
                self.assertGreater(len(mesh.findall(f"./{ns}triangles/{ns}triangle")), 0)


    def test_modifier_respects_rotated_anisotropic_parent_and_bed_elevation(self):
        # A modifier follows the same local->bed transform as the preview,
        # never the parent's rotated world-space bounding-box midpoint.
        parent = item(x=3, y=4, z=6)
        parent.update({"x_mm": 10, "y_mm": -15, "z_mm": 2,
                       "rotation_deg": 90, "scale_xyz_percent": [200, 100, 50]})
        output = export_modifier_3mf_fixture(
            [(parent, fixture_stl())], bed_width=220, bed_depth=220)
        with zipfile.ZipFile(io.BytesIO(output)) as archive:
            root = ET.fromstring(archive.read("3D/3dmodel.model"))
        ns = "{" + NS + "}"
        child = root.find(f"./{ns}resources/{ns}object[@id='3']/{ns}mesh")
        self.assertIsNotNone(child)
        vertices = [
            tuple(float(row.attrib[axis]) for axis in ("x", "y", "z"))
            for row in child.findall(f"./{ns}vertices/{ns}vertex")
        ]
        centroid = tuple(sum(v[axis] for v in vertices) / len(vertices)
                         for axis in range(3))
        # X=(bed 110 + position 10) - local Y(4) * scaleY(1)
        # Y=(bed 110 + position -15) + local X(3) * scaleX(2)
        # Z=bed lift 2 + local Z(6) * scaleZ(.5)
        for actual, expected in zip(centroid, (116, 101, 5)):
            self.assertAlmostEqual(actual, expected, places=4)

    def test_non_intersecting_modifier_fails_closed(self):
        with self.assertRaisesRegex(SlicerProfileError, "does not intersect"):
            export_modifier_3mf_fixture(
                [(item(x=500), fixture_stl())], bed_width=220, bed_depth=220)

    def test_unverified_modifier_is_never_silently_dropped_by_standard_export(self):
        from core.slicer_plate_3mf import build_plate_3mf
        with self.assertRaisesRegex(SlicerProfileError, "cannot discard"):
            build_plate_3mf(
                [(item(), fixture_stl())], bed_width=220, bed_depth=220)

    def test_normal_plate_without_modifiers_keeps_existing_path(self):
        from core.slicer_plate_3mf import build_plate_3mf
        plain = item()
        del plain["modifier_volumes"]
        data = build_plate_3mf([(plain, fixture_stl())],
                               bed_width=220, bed_depth=220)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            root = ET.fromstring(archive.read("3D/3dmodel.model"))
        ns = "{" + NS + "}"
        self.assertEqual(len(root.findall(f"./{ns}resources/{ns}object")), 1)
