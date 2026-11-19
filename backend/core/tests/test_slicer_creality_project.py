"""Creality native plate geometry candidate retains exact positions and tools."""
import io
import zipfile
from defusedxml import ElementTree as ET
from django.test import SimpleTestCase

from core.slicer_approval import fixture_stl
from core.slicer_creality_project import build_creality_positioned_plate
from core.slicer_plate_3mf import NS
from core.slicer_profiles import SlicerProfileError


class CrealityPositionedPlateTests(SimpleTestCase):
    def _objects(self):
        return [
            ({"x_mm": -18, "y_mm": 0, "rotation_deg": 0,
              "scale_percent": 100}, fixture_stl()),
            ({"x_mm": 18, "y_mm": 0, "rotation_deg": 0,
              "scale_percent": 100}, fixture_stl()),
        ]

    def test_positions_and_materials_remain_distinct(self):
        project = build_creality_positioned_plate(
            self._objects(), bed_width=260, bed_depth=260, tool_ids=[0, 1])
        with zipfile.ZipFile(io.BytesIO(project)) as zipped:
            root = ET.fromstring(zipped.read("3D/3dmodel.model"))
            settings = ET.fromstring(zipped.read("Metadata/model_settings.config"))
        ns = "{" + NS + "}"
        objects = root.findall("./" + ns + "resources/" + ns + "object")
        x_centres = []
        for obj in objects:
            xs = [float(v.attrib["x"]) for v in obj.findall(
                "./" + ns + "mesh/" + ns + "vertices/" + ns + "vertex")]
            x_centres.append((min(xs) + max(xs)) / 2)
        self.assertAlmostEqual(x_centres[0], 112, places=3)
        self.assertAlmostEqual(x_centres[1], 148, places=3)
        tools = [
            [m.attrib["value"] for m in obj.findall("metadata")
             if m.attrib.get("key") == "extruder"]
            for obj in settings.findall("object")
        ]
        self.assertEqual(tools, [["1"], ["2"]])

    def test_creality_self_contained_project_embeds_profiles_and_bounded_tower(self):
        import json
        from core.slicer_creality_project import build_creality_project_candidate
        plate = build_creality_positioned_plate(
            self._objects(), bed_width=260, bed_depth=260, tool_ids=[0, 1])
        printer = json.dumps({
            "type": "machine", "name": "Creality K2 0.4 nozzle",
            "printable_height": "260",
            "printable_area": ["0x0", "260x0", "260x260", "0x260"],
        }).encode()
        process = json.dumps({
            "type": "process", "name": "0.20mm Standard",
            "enable_prime_tower": "1", "prime_tower_width": "40",
            "layer_height": "0.2",
        }).encode()
        filament = lambda name, temp: json.dumps({
            "type": "filament", "name": name,
            "filament_type": "PLA", "nozzle_temperature": str(temp),
        }).encode()
        result = build_creality_project_candidate(
            plate, printer=printer, process=process,
            filaments=[filament("grey", 210), filament("yellow", 220)],
            bed_width=260, bed_depth=260)
        with zipfile.ZipFile(io.BytesIO(result)) as package:
            self.assertEqual(len(package.namelist()), 6)
            self.assertIn("Metadata/creality.config", package.namelist())
            project = json.loads(package.read("Metadata/project_settings.config"))
            model_root = ET.fromstring(package.read("3D/3dmodel.model"))
            app = [n.text for n in model_root if n.tag.endswith("metadata")
                   and n.attrib.get("name") == "Application"]
            self.assertEqual(app, ["Creality_Print V7.3.1"])
        self.assertEqual(project["filament_settings_id"], ["grey", "yellow", "grey", "yellow"])
        self.assertEqual(project["nozzle_temperature"], ["210", "220", "210", "220"])
        self.assertEqual(project["from"], "project")
        self.assertEqual(project["name"], "project_settings")
        self.assertEqual(len(project["wipe_tower_x"]), 1)
        self.assertLess(float(project["wipe_tower_x"][0]), 260)
        self.assertLess(float(project["wipe_tower_y"][0]), 260)
        # Keep the tower off the front-left corner on a mostly empty K2
        # plate, without claiming that this can replace cleaning the bed.
        self.assertGreater(float(project["wipe_tower_y"][0]), 130)
        self.assertGreater(float(project["wipe_tower_x"][0]), 130)

    def test_creality_native_project_preserves_explicit_tower_and_directional_flush(self):
        import json
        from core.slicer_creality_project import build_creality_project_candidate
        plate = build_creality_positioned_plate(
            self._objects(), bed_width=260, bed_depth=260, tool_ids=[0, 1])
        printer = json.dumps({
            "type": "machine", "name": "Creality K2",
            "printable_area": ["0x0", "260x0", "260x260", "0x260"],
        }).encode()
        process = json.dumps({
            "type": "process", "name": "0.20mm Standard",
            "enable_prime_tower": "1", "prime_tower_width": "40",
            "flush_volumes_matrix": ["0", "140", "140", "0"],
        }).encode()
        filament = lambda name: json.dumps({
            "type": "filament", "name": name,
            "filament_type": "PLA", "nozzle_temperature": "210",
        }).encode()
        setting = {
            "multiplier": None, "prime_tower": "enabled",
            "transitions": [
                {"from_slot_id": "grey-id", "to_slot_id": "yellow-id", "volume_mm3": 370},
                {"from_slot_id": "yellow-id", "to_slot_id": "grey-id", "volume_mm3": 175},
            ],
        }
        def build(settings=setting, bindings=None):
            return build_creality_project_candidate(
                plate, printer=printer, process=process,
                filaments=[filament("grey"), filament("yellow")],
                prime_tower={"x": 170, "y": 170}, bed_width=260, bed_depth=260,
                flush_settings=settings, tool_bindings=bindings or {
                    "grey-id": 0, "yellow-id": 1,
                })
        with zipfile.ZipFile(io.BytesIO(build())) as package:
            result = json.loads(package.read("Metadata/project_settings.config"))
        self.assertEqual(result["wipe_tower_x"], ["170"])
        self.assertEqual(result["wipe_tower_y"], ["170"])
        self.assertEqual(result["enable_prime_tower"], "1")
        self.assertEqual(result["flush_volumes_matrix"][1], "370.0")
        self.assertEqual(result["flush_volumes_matrix"][4], "175.0")
        self.assertEqual(result["flush_volumes_matrix"][2], "0")
        self.assertEqual(len(result["flush_volumes_matrix"]), 16)
        with self.assertRaisesMessage(SlicerProfileError, "unmapped physical"):
            build({**setting, "transitions": [{
                "from_slot_id": "unrelated-slot", "to_slot_id": "yellow-id",
                "volume_mm3": 300,
            }]})
        with self.assertRaisesMessage(SlicerProfileError, "multiplier"):
            build({**setting, "multiplier": 1.5})
        with self.assertRaisesMessage(SlicerProfileError, "two verified"):
            build(bindings={"grey-id": 0, "yellow-id": 0})

    def test_one_painted_model_retains_native_facets_in_final_creality_project(self):
        """Creality must receive one object and real colour facet metadata."""
        import json
        from core.slicer_creality_project import (
            build_creality_project_candidate, build_creality_positioned_plate,
        )
        from core.tests.test_slicer_colour_native_3mf import fixture_paint, PRINTER_ID
        raw, paint = fixture_paint()
        # The shared Orca fixture intentionally contains unused swatches with
        # placeholder printer IDs. Creality must receive a fully valid palette,
        # even when only one secondary swatch is painted.
        for swatch in paint["palette"]:
            swatch["printer_id"] = PRINTER_ID
        paint["palette"][2].update({
            "printer_id": PRINTER_ID,
            "slot_id": "bay-2",
            "slot_index": 1,
            "color": "#FADD4D",
        })
        item = {
            "x_mm": 0, "y_mm": 0, "rotation_deg": 0,
            "scale_percent": 100, "color": "#111111",
            "material_slot": {
                "printer_id": PRINTER_ID,
                "slot_id": "bay-1", "slot_index": 0,
            },
            "colour_paint": paint,
        }
        geometry = build_creality_positioned_plate(
            [(item, raw)], bed_width=260, bed_depth=260,
            tool_ids=[0], colour_tool_maps=({2: 1},),
        )
        with zipfile.ZipFile(io.BytesIO(geometry)) as package:
            root = ET.fromstring(package.read("3D/3dmodel.model"))
            settings = ET.fromstring(package.read("Metadata/model_settings.config"))
        triangles = root.findall(".//{%s}triangle" % NS)
        self.assertTrue(any(face.attrib.get("paint_color") == "8" for face in triangles))
        self.assertTrue(any("paint_color" not in face.attrib for face in triangles))
        self.assertEqual(len(settings.findall("object")), 1)
        printer = json.dumps({
            "type": "machine", "name": "Creality K2 0.4 nozzle",
            "printable_height": "260",
            "printable_area": ["0x0", "260x0", "260x260", "0x260"],
        }).encode()
        process = json.dumps({
            "type": "process", "name": "Standard",
            "enable_prime_tower": "1", "prime_tower_width": "40",
        }).encode()
        filament = lambda name: json.dumps({
            "type": "filament", "name": name, "filament_type": "PLA",
            "nozzle_temperature": "210",
        }).encode()
        project = build_creality_project_candidate(
            geometry, printer=printer, process=process,
            filaments=[filament("grey"), filament("yellow")],
            tool_colours=("#111111", "#FADD4D"),
            bed_width=260, bed_depth=260,
        )
        with zipfile.ZipFile(io.BytesIO(project)) as package:
            final = ET.fromstring(package.read("3D/3dmodel.model"))
            config = ET.fromstring(package.read("Metadata/model_settings.config"))
        self.assertEqual(len(config.findall("object")), 1)
        self.assertTrue(any(
            face.attrib.get("paint_color") == "8"
            for face in final.findall(".//{%s}triangle" % NS)
        ))

    def test_single_creality_model_without_paint_cannot_invent_second_tool(self):
        from core.slicer_creality_project import build_creality_positioned_plate
        with self.assertRaises(SlicerProfileError):
            build_creality_positioned_plate(
                [(self._objects()[0][0], fixture_stl())],
                bed_width=260, bed_depth=260, tool_ids=[0],
            )

    def test_filament_option_merge_flattens_native_singleton_vectors(self):
        import json
        from core.slicer_creality_project import build_creality_project_candidate
        plate = build_creality_positioned_plate(
            self._objects(), bed_width=260, bed_depth=260, tool_ids=[0, 1])
        printer = json.dumps({
            "type": "machine", "name": "Creality K2",
            "nozzle_diameter": ["0.4"],
        }).encode()
        process = json.dumps({
            "type": "process", "name": "0.20mm",
            "enable_prime_tower": "0",
        }).encode()
        filament = lambda name, temp: json.dumps({
            "type": "filament", "name": name,
            "filament_type": ["PLA"], "filament_diameter": ["1.75"],
            "nozzle_temperature": [str(temp)],
            "fan_cooling_layer_time": ["12"],
            "filament_minimal_purge_on_wipe_tower": ["15"],
            "filament_shrinkage_compensation_z": ["100%"],
        }).encode()
        result = build_creality_project_candidate(
            plate, printer=printer, process=process,
            filaments=[filament("grey", 210), filament("yellow", 220)])
        with zipfile.ZipFile(io.BytesIO(result)) as package:
            config = json.loads(package.read("Metadata/project_settings.config"))
        self.assertEqual(config["nozzle_temperature"], ["210", "220", "210", "220"])
        self.assertEqual(config["filament_diameter"], ["1.75", "1.75", "1.75", "1.75"])
        self.assertEqual(config["fan_cooling_layer_time"], ["12", "12", "12", "12"])
        self.assertEqual(config["filament_minimal_purge_on_wipe_tower"], ["15", "15", "15", "15"])
        self.assertEqual(config["filament_shrinkage_compensation_z"], ["100%", "100%", "100%", "100%"])
        self.assertEqual(config["nozzle_diameter"], ["0.4"])
        self.assertEqual(config["filament_map"], ["1", "1", "1", "1"])
        self.assertEqual(len(config["flush_volumes_matrix"]), 16)
        self.assertEqual(len(config["flush_volumes_vector"]), 8)

    def test_native_object_parts_and_assembly_preserve_exact_positions(self):
        import json
        from core.slicer_creality_project import build_creality_project_candidate
        source = build_creality_positioned_plate(
            self._objects(), bed_width=260, bed_depth=260, tool_ids=[0, 1])
        printer = json.dumps({"type": "machine", "name": "K2", "nozzle_diameter": ["0.4"]}).encode()
        process = json.dumps({"type": "process", "name": "Standard", "enable_prime_tower": "0"}).encode()
        filament = lambda name: json.dumps({
            "type": "filament", "name": name, "filament_type": ["PLA"]}).encode()
        result = build_creality_project_candidate(
            source, printer=printer, process=process,
            filaments=[filament("grey"), filament("yellow")])
        with zipfile.ZipFile(io.BytesIO(source)) as z:
            original = ET.fromstring(z.read("3D/3dmodel.model"))
        with zipfile.ZipFile(io.BytesIO(result)) as z:
            model = ET.fromstring(z.read("3D/3dmodel.model"))
            settings = ET.fromstring(z.read("Metadata/model_settings.config"))
        ns = "{" + NS + "}"
        self.assertEqual(
            [v.attrib for v in original.findall(".//" + ns + "vertex")],
            [v.attrib for v in model.findall(".//" + ns + "vertex")])
        self.assertEqual([obj.find("part").get("subtype")
                          for obj in settings.findall("object")],
                         ["normal_part", "normal_part"])
        self.assertEqual(len(settings.findall("./assemble/assemble_item")), 2)
        self.assertEqual(
            [row.get("value") for obj in settings.findall("object")
             for row in obj.findall("metadata") if row.get("key") == "extruder"],
            ["1", "2"])

    def test_two_slot_flush_matrix_expands_without_erasing_transitions(self):
        from core.slicer_creality_project import _native_palette_settings
        project = {
            "filament_settings_id": ["PLA grey", "PLA yellow"],
            "filament_type": ["PLA", "PLA"],
            "flush_volumes_matrix": ["0", "180", "210", "0"],
            "flush_volumes_vector": ["140", "140", "140", "140"],
        }
        self.assertEqual(_native_palette_settings(project, [None, None]), 4)
        self.assertEqual(project["filament_settings_id"],
                         ["PLA grey", "PLA yellow", "PLA grey", "PLA yellow"])
        self.assertEqual(project["flush_volumes_matrix"][1], "180")
        self.assertEqual(project["flush_volumes_matrix"][4], "210")
        self.assertEqual(project["flush_volumes_matrix"][11], "180")
        self.assertEqual(len(project["flush_volumes_vector"]), 8)
        self.assertEqual(project["filament_type"], ["PLA"] * 4)

    def test_reference_schema_required_cfs_keys(self):
        import json
        from core.slicer_creality_project import build_creality_project_candidate
        plate = build_creality_positioned_plate(
            self._objects(), bed_width=260, bed_depth=260, tool_ids=[0, 1])
        printer = json.dumps({"type": "machine", "name": "K2",
                              "nozzle_diameter": ["0.4"]}).encode()
        process = json.dumps({"type": "process", "name": "Standard",
                              "enable_prime_tower": "0"}).encode()
        filament = lambda name: json.dumps({
            "type": "filament", "name": name,
            "filament_type": ["PLA"], "nozzle_temperature": ["220"]}).encode()
        result = build_creality_project_candidate(
            plate, printer=printer, process=process,
            filaments=[filament("grey"), filament("yellow")])
        with zipfile.ZipFile(io.BytesIO(result)) as package:
            config = json.loads(package.read("Metadata/project_settings.config"))
        # Structure observed in a native Creality Print 7.3.2 K2 3MF,
        # without copying any user-specific source settings or scripts.
        expected_lengths = {
            "filament_settings_id": 4, "filament_map": 4,
            "filament_map_2": 4, "filament_colour_type": 4,
            "filament_volume_map": 4, "nozzle_temperature": 4,
            "filament_type": 4, "flush_volumes_matrix": 16,
            "flush_volumes_vector": 8,
        }
        for key, count in expected_lengths.items():
            self.assertIn(key, config)
            self.assertEqual(len(config[key]), count, key)
        self.assertEqual(config["filament_map_mode"], "AutoForSaving")

    def test_creality_machine_polygon_is_serialised_as_project_vector(self):
        import json
        from core.slicer_creality_project import build_creality_project_candidate
        plate = build_creality_positioned_plate(
            self._objects(), bed_width=260, bed_depth=260, tool_ids=[0, 1])
        process = json.dumps({"type": "process", "enable_prime_tower": "0"}).encode()
        filaments = [json.dumps({"type": "filament", "name": name,
                                  "filament_type": ["PLA"]}).encode()
                     for name in ("grey", "yellow")]
        machine = json.dumps({
            "type": "machine", "name": "K2",
            "printable_area": "0x0,260x0,260x260,0x260"}).encode()
        project = build_creality_project_candidate(
            plate, printer=machine, process=process, filaments=filaments,
            bed_width=260, bed_depth=260)
        with zipfile.ZipFile(io.BytesIO(project)) as archive:
            settings = json.loads(archive.read("Metadata/project_settings.config"))
        self.assertEqual(settings["printable_area"],
                         ["0x0", "260x0", "260x260", "0x260"])
        wrong_bed = json.dumps({
            "type": "machine", "printable_area": "0x0,300x0,300x300,0x300"}).encode()
        with self.assertRaisesRegex(SlicerProfileError, "verified bed"):
            build_creality_project_candidate(
                plate, printer=wrong_bed, process=process,
                filaments=filaments, bed_width=260, bed_depth=260)

    def test_physical_filament_colour_vector_matches_four_native_slots(self):
        from core.slicer_creality_project import _native_palette_settings
        project = {
            "filament_settings_id": ["Grey PLA", "Yellow PLA"],
            "filament_diameter": ["1.75", "1.75"],
            "default_filament_colour": ["#808080", "#FFFF00"],
        }
        _native_palette_settings(project, [None, None])
        self.assertEqual(project["filament_colour"],
                         ["#808080", "#FFFF00", "#808080", "#FFFF00"])
        self.assertEqual(len(project["filament_diameter"]), 4)
        self.assertEqual(len(project["filament_settings_id"]), 4)

    def test_missing_source_colours_keep_full_physical_material_count(self):
        from core.slicer_creality_project import _native_palette_settings
        project = {"filament_settings_id": ["A", "B"],
                   "filament_type": ["PLA", "PLA"]}
        _native_palette_settings(project, [None, None])
        self.assertEqual(project["filament_colour"], ["#FFFFFF"] * 4)

    def test_invalid_palette_fails_before_native_engine(self):
        with self.assertRaises(SlicerProfileError):
            build_creality_positioned_plate(
                self._objects(), bed_width=260, bed_depth=260, tool_ids=[0, 0])

    def test_selected_colours_override_neutral_profile_colours_without_changing_nozzle_map(self):
        import json
        from core.slicer_creality_project import build_creality_project_candidate
        plate = build_creality_positioned_plate(
            self._objects(), bed_width=260, bed_depth=260, tool_ids=[0, 1])
        printer = json.dumps({"type": "machine", "name": "K2",
                              "nozzle_diameter": ["0.4"]}).encode()
        process = json.dumps({"type": "process", "name": "Standard",
                              "enable_prime_tower": "0"}).encode()
        filaments = [json.dumps({"type": "filament", "name": name,
                                  "filament_type": ["PLA-Silk"],
                                  "filament_colour": ["#FFFFFF"]}).encode()
                     for name in ("Grey", "Yellow")]
        result = build_creality_project_candidate(
            plate, printer=printer, process=process, filaments=filaments,
            tool_colours=("#777777", "#ffcc00"))
        with zipfile.ZipFile(io.BytesIO(result)) as archive:
            settings = json.loads(archive.read("Metadata/project_settings.config"))
        self.assertEqual(settings["filament_colour"],
                         ["#777777", "#FFCC00", "#777777", "#FFCC00"])
        self.assertEqual(settings["filament_map"], ["1", "1", "1", "1"])
        self.assertEqual(settings["filament_type"], ["PLA-Silk"] * 4)

    def test_invalid_selected_colours_fail_closed(self):
        import json
        from core.slicer_creality_project import build_creality_project_candidate
        plate = build_creality_positioned_plate(
            self._objects(), bed_width=260, bed_depth=260, tool_ids=[0, 1])
        machine = json.dumps({"type": "machine", "nozzle_diameter": ["0.4"]}).encode()
        process = json.dumps({"type": "process", "enable_prime_tower": "0"}).encode()
        filaments = [json.dumps({"type": "filament", "name": name}).encode()
                     for name in ("A", "B")]
        for colours in (("#FFFFFF",), ("red", "#FFFFFF"),
                        ("#FFFFFF", "#GGGGGG"), ("#FFFFFF", None)):
            with self.subTest(colours=colours):
                with self.assertRaises(SlicerProfileError):
                    build_creality_project_candidate(
                        plate, printer=machine, process=process,
                        filaments=filaments, tool_colours=colours)
