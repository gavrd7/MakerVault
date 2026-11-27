"""Prusa native MMU colour candidate uses the real application exporter.

Never infer approval for the authenticated worker from a valid research 3MF.
"""
import io
import struct
import zipfile
from unittest import TestCase
from defusedxml import ElementTree as SafeET

from core.slicer_prusa_colour_project import build_prusa_colour_candidate
from core.slicer_profiles import SlicerProfileError
from core.tests.test_slicer_prusa_machine_topology import ini
from scripts.prusa_generate_mmu_paint import fixture
from slicer_worker.prusa_material_validation import validate_prusa_material_candidate
from slicer_worker.runner import WorkerError

NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"


class PrusaNativeColourProjectTests(TestCase):
    def candidate(self, *, settings=None, source=None, tool_map=None):
        stl, _painted, _states, paint = fixture(include_paint=True)
        row = {
            "asset_id": "synthetic-mm3-painted",
            "x_mm": 0, "y_mm": 0, "z_mm": 0,
            "rotation_deg": 0, "scale_percent": 100,
            "colour_paint": paint,
        }
        row.update(settings or {})
        return build_prusa_colour_candidate(
            row, source if source is not None else stl,
            printer_ini=ini("0.4,0.4,0.4,0.4,0.4", "1"),
            colour_tool_indices=tool_map if tool_map is not None else {1: 1},
            bed_width=250, bed_depth=210)

    def test_native_colour_structure_and_tool_selection(self):
        project = self.candidate()
        with zipfile.ZipFile(io.BytesIO(project)) as archive:
            self.assertEqual(len(archive.namelist()), len(set(archive.namelist())))
            xml = archive.read("3D/3dmodel.model")
            config = SafeET.fromstring(archive.read("Metadata/Slic3r_PE_model.config"))
        self.assertIn(b'xmlns:slic3rpe="http://schemas.slic3r.org/3mf/2017/06"', xml)
        self.assertIn(b'slic3rpe:mmu_segmentation="8"', xml)
        self.assertIn(b'name="slic3rpe:MmPaintingVersion"', xml)
        root = SafeET.fromstring(xml)
        metadata = root.findall(NS+"metadata")
        self.assertEqual(sum(x.get("name")=="slic3rpe:MmPaintingVersion"
                             for x in metadata),1)
        self.assertEqual(config.find("./object/volume/metadata[@key='extruder']").get("value"),"1")

    def test_five_tool_prusa_leaf_states_are_verified_by_independent_worker(self):
        machine = ini("0.4,0.4,0.4,0.4,0.4", "1")
        for selected, state in ((1, "8"), (2, "0C"), (3, "1C"), (4, "2C")):
            with self.subTest(native_tool=selected):
                data = self.candidate(tool_map={1:selected})
                with zipfile.ZipFile(io.BytesIO(data)) as source:
                    model = source.read("3D/3dmodel.model")
                self.assertIn(('slic3rpe:mmu_segmentation="' + state + '"').encode(), model)
                receipt = validate_prusa_material_candidate(
                    data, printer_ini=machine, colour=True)
                self.assertEqual(receipt["tools"], (1, selected+1))
                self.assertGreater(receipt["colour_facets"], 0)

    def test_two_distinct_wall_colours_retain_three_independent_native_tools(self):
        from core.slicer_plate_3mf import _triangles
        from core.slicer_native_support_paint import _fingerprint
        stl, _painted, _states, existing = fixture(include_paint=True)
        faces = list(_triangles(stl))
        minimum = [min(v[a] for face in faces for v in face) for a in range(3)]
        maximum = [max(v[a] for face in faces for v in face) for a in range(3)]
        origin = ((minimum[0]+maximum[0])/2,
                  (minimum[1]+maximum[1])/2, minimum[2])
        local = [[tuple(v[a]-origin[a] for a in range(3)) for v in face]
                 for face in faces]
        back = [{"face":i, "polygon":[list(v) for v in face]}
                for i,face in enumerate(local)
                if all(abs(v[1]-10)<.00001 for v in face)]
        self.assertEqual(len(back),2)
        paint = {**existing, "signature":_fingerprint(local),
                 "palette":[*existing["palette"],
                            {"color":"#fadd4d","label":"T2"}],
                 "regions":[*existing["regions"],
                            {"slot":2,"patches":back}]}
        project = self.candidate(settings={"colour_paint":paint},
                                 tool_map={1:1,2:2})
        with zipfile.ZipFile(io.BytesIO(project)) as z:
            raw = z.read("3D/3dmodel.model")
        self.assertIn(b'slic3rpe:mmu_segmentation="8"',raw)
        self.assertIn(b'slic3rpe:mmu_segmentation="0C"',raw)
        receipt = validate_prusa_material_candidate(
            project, printer_ini=ini("0.4,0.4,0.4,0.4,0.4","1"),
            colour=True)
        self.assertEqual(receipt["tools"],(1,2,3))
        self.assertGreater(receipt["colour_facets"],3)
        from slicer_worker.prusa_colour_gcode_audit import _two_painted_wall_regions
        regions = _two_painted_wall_regions(project, (1,2))
        self.assertLess(regions["front"][3], regions["back"][2])
        with self.assertRaises((SlicerProfileError, ValueError)):
            self.candidate(settings={"colour_paint":paint},
                           tool_map={1:1})

    def test_indx_eight_head_native_colour_accepts_all_seven_alternate_facets(self):
        printer=ini(",".join(["0.4"]*8),"0")
        stl,_mesh,_states,paint=fixture(include_paint=True)
        row={"asset_id":"indx-eight","x_mm":0,"y_mm":0,"z_mm":0,
             "rotation_deg":0,"scale_percent":100,"colour_paint":paint}
        for selected,state in ((1,"8"),(2,"0C"),(3,"1C"),(4,"2C"),
                               (5,"3C"),(6,"4C"),(7,"5C")):
            with self.subTest(selected=selected):
                project=build_prusa_colour_candidate(
                    row,stl,printer_ini=printer,
                    colour_tool_indices={1:selected},bed_width=250,bed_depth=210)
                with zipfile.ZipFile(io.BytesIO(project)) as archive:
                    self.assertIn(
                        ('slic3rpe:mmu_segmentation="'+state+'"').encode(),
                        archive.read("3D/3dmodel.model"))
                receipt=validate_prusa_material_candidate(
                    project,printer_ini=printer,colour=True,
                    independent_colour=True)
                self.assertEqual(receipt["tools"],(1,selected+1))
        # More than eight toolheads remain unavailable on this printer,
        # even though the underlying TriangleSelector supports more states.
        for selected in (0,8,9):
            with self.subTest(selected=selected),self.assertRaises(SlicerProfileError):
                build_prusa_colour_candidate(
                    row,stl,printer_ini=printer,
                    colour_tool_indices={1:selected},bed_width=250,bed_depth=210)

    def test_painted_tools_outside_native_printer_capacity_are_blocked(self):
        candidate = self.candidate(tool_map={1:4})
        for count in (2,3,4):
            with self.subTest(logical_count=count), self.assertRaises(WorkerError):
                validate_prusa_material_candidate(
                    candidate, printer_ini=ini(",".join(["0.4"]*count), "1"),
                    colour=True)

    def test_malformed_or_recursive_painted_leaf_states_fail_closed(self):
        data = self.candidate(tool_map={1:2})
        with zipfile.ZipFile(io.BytesIO(data)) as source:
            parts = {name:source.read(name) for name in source.namelist()}
        for invalid in (b'9', b'3C', b'8C', b'0c', b''):
            with self.subTest(state=invalid):
                altered = dict(parts)
                altered["3D/3dmodel.model"] = altered["3D/3dmodel.model"].replace(
                    b'slic3rpe:mmu_segmentation="0C"',
                    b'slic3rpe:mmu_segmentation="' + invalid + b'"')
                output = io.BytesIO()
                with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target:
                    for name, content in altered.items():
                        target.writestr(name, content)
                with self.assertRaises(WorkerError):
                    validate_prusa_material_candidate(
                        output.getvalue(),
                        printer_ini=ini("0.4,0.4,0.4,0.4,0.4", "1"), colour=True)

    def test_painted_wall_research_uses_actual_printer_bed_center(self):
        from scripts.prusa_native_five_colour_paint_smoke import painted_external_walls
        native = (b"G90\nM83\nT1\n;TYPE:External perimeter\n"
                  b"G0 X170 Y170\nG1 X171 Y170 E.1\n"
                  b"T0\n;TYPE:External perimeter\n"
                  b"G0 X170 Y190\nG1 X171 Y190 E.1\n")
        self.assertEqual(painted_external_walls(native)[1]["front"],0)
        xl=painted_external_walls(native,center_x=180,center_y=180)
        self.assertEqual(xl[1]["front"],1)
        self.assertEqual(xl[0]["back"],1)
        self.assertEqual(xl[1]["back"],0)

    def test_multi_swatch_research_counts_only_moving_matching_wall_paths(self):
        from scripts.prusa_native_five_colour_paint_smoke import painted_external_walls
        commands = [
            "M82", "G92 E0", "T1",
            "G0 X120 Y95", "G1 X121 Y95 E0.5",
            "G1 E0.6",  # stationary recovery is never wall deposition
            "T2", "G0 X120 Y115", "G1 X121 Y115 E1.0",
            "G1 X121 Y95 E1.3",  # crosses two regions: neither endpoint pair qualifies
            "T0", "G0 X120 Y115", "G1 E1.7",
        ]
        encoded = (";TYPE:External perimeter\n" +
                   "\n".join(commands) + "\n").encode()
        counts = painted_external_walls(encoded)
        self.assertEqual(counts[1], {"front":1, "back":0})
        self.assertEqual(counts[2], {"front":0, "back":1})
        self.assertEqual(counts[0], {"front":0, "back":0})

    def test_invalid_tool_mapping_and_mixed_features_refused(self):
        for mapping in ({1:5},{1:True},{True:1},{}, {1:0}, {1:-1}, {1:"2"}):
            with self.subTest(mapping=mapping):
                if mapping == {1:0}:
                    # A painting assignment to T0 cannot prove a second tool.
                    with self.assertRaises((SlicerProfileError,ValueError)):
                        self.candidate(tool_map=mapping)
                else:
                    with self.assertRaises((SlicerProfileError,ValueError)):
                        self.candidate(tool_map=mapping)
        for field,value in (("modifier_volumes",[{"id":"unsafe"}]),
                            ("process_overrides",{"wall_loops":3}),
                            ("support_paint",{"regions":[{"slot":0}]}),
                            ("material_slot",1)):
            with self.subTest(field=field),self.assertRaises(SlicerProfileError):
                self.candidate(settings={field:value})

    def test_source_fingerprint_must_match(self):
        stl, *_ = fixture()
        # Change actual facet vertex geometry, not the unused STL normal.
        tampered = stl[:96] + struct.pack('<f', 4.0) + stl[100:]
        with self.assertRaises((SlicerProfileError,ValueError)):
            self.candidate(source=tampered)


class PrusaPaintedWallMotionTests(TestCase):
    """Worker must not mistake stationary E, G91 or a crossing path for paint."""

    def source(self, *, stationary=False, crossing=False, relative_xy=False):
        lines = ["M83", "G90", "G92 E0"]
        for tool, y in ((1, 95), (0, 115)):
            lines += [f"T{tool}", ";TYPE:External perimeter",
                      f"G0 X115 Y{y}"]
            if relative_xy:
                lines.append("G91")
            for n in range(25):
                if stationary:
                    lines.append("G1 E0.03")
                elif crossing:
                    if relative_xy:
                        lines += ["G90", f"G0 X110 Y{y}",
                                  f"G1 X120 Y{y} E0.03", "G91"]
                    else:
                        lines += [f"G0 X110 Y{y}", f"G1 X120 Y{y} E0.03"]
                elif relative_xy:
                    lines.append("G1 X0.5 Y0 E0.03")
                else:
                    lines.append(f"G1 X{115+(n+1)*.5:.2f} Y{y} E0.03")
            if relative_xy:
                lines.append("G90")
            lines += [";TYPE:Wipe tower", "G0 X55 Y155"]
            for n in range(12):
                lines.append(f"G1 X{55+(n+1)*.5:.2f} Y155 E0.03")
        return ("\n".join(lines)+"\n").encode()

    def checked(self, data):
        from unittest.mock import patch
        from slicer_worker.prusa_colour_gcode_audit import audit_prusa_offline_colour_gcode
        with patch(
            "slicer_worker.prusa_colour_gcode_audit.validate_prusa_material_candidate",
            return_value={"tools": (1, 2)}
        ), patch(
            "slicer_worker.prusa_colour_gcode_audit._wall_regions",
            return_value=((114, 136, 93, 97), (114, 136, 113, 117))
        ):
            return audit_prusa_offline_colour_gcode(
                data, b"verified-project", printer_ini=b"verified-printer",
                tool=1, tower=(55, 150, 0, 250, 210))

    def test_both_native_xy_modes_count_only_deposited_wall_paths(self):
        for relative in (False, True):
            with self.subTest(relative_xy=relative):
                result = self.checked(self.source(relative_xy=relative))
                self.assertEqual(result["painted_wall_moves"][1]["front"], 25)
                self.assertEqual(result["painted_wall_moves"][0]["back"], 25)
                self.assertGreaterEqual(result["tower_extrusion_moves"][0], 10)
                self.assertGreaterEqual(result["tower_extrusion_moves"][1], 10)

    def test_stationary_and_crossing_paths_never_qualify_painted_wall(self):
        for mode in ({"stationary": True}, {"crossing": True}):
            with self.subTest(mode=mode), self.assertRaises(WorkerError):
                self.checked(self.source(**mode))

    def test_genuine_stationary_purge_at_tower_is_valid_but_not_at_model(self):
        data = self.source()
        # Prusa MMU3 legitimately purges at a stationary tower XY. Model
        # paint still requires *moving* deposition on the selected wall.
        import re
        data = re.sub(rb"G1 X\d+(?:\.\d+)? Y155 E0\.03",
                      b"G1 E0.03", data)
        observed=self.checked(data)
        self.assertGreaterEqual(observed["tower_extrusion_moves"][0],10)
        self.assertGreaterEqual(observed["tower_extrusion_moves"][1],10)
        with self.assertRaises(WorkerError):
            self.checked(data.replace(b"G0 X55 Y155",b"G0 X155 Y155"))


class PrusaDualColourResearchTests(TestCase):
    """Do not enable MMU multi-swatch until the actual native G-code qualifies."""

    def gcode(self, *, crossing=False, stationary_tower=False, wrong_tool=False):
        lines=["G90", "M83", "G92 E0"]
        for tool, y in ((1,95),(2,115)):
            actual=0 if wrong_tool and tool==2 else tool
            lines += [f"T{actual}", ";TYPE:External perimeter",
                      f"G0 X115 Y{y}"]
            for n in range(25):
                if crossing:
                    lines += [f"G0 X110 Y{y}", f"G1 X120 Y{y} E0.03"]
                else:
                    lines.append(f"G1 X{115+(n+1)*.5:.2f} Y{y} E0.03")
        for tool in (0,1,2):
            lines += [f"T{tool}", ";TYPE:Wipe tower", "G0 X55 Y155"]
            for n in range(15):
                lines.append(("G1 E0.03" if stationary_tower else
                              f"G1 X{55+(n+1)*.5:.2f} Y155 E0.03"))
        return ("\n".join(lines)+"\n").encode()

    def audit(self, data):
        from unittest.mock import patch
        from slicer_worker.prusa_colour_gcode_audit import audit_prusa_dual_colour_gcode
        with patch(
            "slicer_worker.prusa_colour_gcode_audit.validate_prusa_material_candidate",
            return_value={"tools":(1,2,3)}
        ), patch(
            "slicer_worker.prusa_colour_gcode_audit._two_painted_wall_regions",
            return_value={"front":(114,136,93,97),
                          "back":(114,136,113,117)}
        ):
            return audit_prusa_dual_colour_gcode(
                data, b"controlled-native", printer_ini=b"controlled-printer",
                tools=(1,2), tower=(55,150,0,250,210))

    def test_independent_native_walls_and_all_three_purge_tools(self):
        receipt=self.audit(self.gcode())
        self.assertEqual(receipt["wall_moves"][1]["front"],25)
        self.assertEqual(receipt["wall_moves"][2]["back"],25)
        self.assertEqual(receipt["wall_moves"][0],{"front":0,"back":0})
        self.assertTrue(all(v>=10 for v in receipt["tower_extrusion_moves"].values()))

    def test_native_base_t0_may_deposit_corner_perimeters_on_both_painted_walls(self):
        material = self.gcode() + (
            b"T0\n;TYPE:External perimeter\n"
            b"G0 X115 Y95\nG1 X116 Y95 E.03\n"
            b"G0 X115 Y115\nG1 X116 Y115 E.03\n")
        result=self.audit(material)
        self.assertEqual(result["wall_moves"][0],{"front":1,"back":1})
        self.assertEqual(result["wall_moves"][1]["back"],0)
        self.assertEqual(result["wall_moves"][2]["front"],0)

    def test_wrong_tool_or_cross_wall_paths_fail_closed(self):
        for variant in ({"crossing":True},{"wrong_tool":True}):
            with self.subTest(variant=variant),self.assertRaises(WorkerError):
                self.audit(self.gcode(**variant))
        with self.assertRaises(WorkerError):
            self.audit(self.gcode().replace(b"T2",b"T7"))
        stationary=self.audit(self.gcode(stationary_tower=True))
        self.assertTrue(all(value>=10 for value
                            in stationary["tower_extrusion_moves"].values()))

    def test_official_indx_cleaner_excludes_only_signed_bounded_flush_strokes(self):
        from unittest.mock import patch
        native=self.gcode()
        insert=(b"T2\n;TYPE:External perimeter\nG0 X115 Y95\n"
                b"G12 S90\nG91\n;FLUSH_START\n"
                b"G1 X-0.2 E0\nG1 X0.4 E1\nG1 Y-1.2 E1\n"
                b"G1 X-0.4 E1\nG1 Y1.2 E1\nG1 X0.2 E.2\n"
                b";FLUSH_END\nG90\nG12 S91\nG0 X115 Y115")
        native=native.replace(
            b"T2\n;TYPE:External perimeter\nG0 X115 Y115",insert)
        self.assertIn(b";FLUSH_START",native)
        with self.assertRaises(WorkerError):
            self.audit(native)
        with patch(
            "slicer_worker.prusa_material_gcode_audit._trusted_indx_cleaner_profile",
            return_value=True
        ):
            result=self.audit(native)
            self.assertEqual(result["wall_moves"][1]["front"],25)
            self.assertEqual(result["wall_moves"][2]["back"],25)
            self.assertEqual(result["wall_moves"][2]["front"],0)
            for malicious in (
                native.replace(b"G1 X0.4 E1",b"G1 X40 E1"),
                native.replace(b";FLUSH_END",b";UNTRUSTED_END"),
                native.replace(b"G12 S91",b"G12 S90"),
                native.replace(b"G1 Y1.2 E1",b"G1 Y1.2 E90"),
            ):
                with self.subTest(malicious=malicious[-70:]),self.assertRaises(WorkerError):
                    self.audit(malicious)

    def test_independent_xl_reuses_dual_wall_audit_without_mmu_purge(self):
        from unittest.mock import patch
        from slicer_worker.prusa_colour_gcode_audit import audit_prusa_dual_colour_gcode
        with patch(
            "slicer_worker.prusa_colour_gcode_audit.validate_prusa_material_candidate",
            return_value={"tools":(1,2,3),"wipe_tower":False}
        ) as validate, patch(
            "slicer_worker.prusa_colour_gcode_audit._two_painted_wall_regions",
            return_value={"front":(114,136,93,97),"back":(114,136,113,117)}
        ):
            output=audit_prusa_dual_colour_gcode(
                self.gcode(),b"controlled-xl-project",
                printer_ini=b"owned-independent-xl",tools=(1,2),tower=None)
            self.assertEqual(output["wall_moves"][1]["front"],25)
            self.assertEqual(output["wall_moves"][2]["back"],25)
            self.assertEqual(output["tower_extrusion_moves"],{})
            self.assertFalse(output["wipe_tower"])
            self.assertTrue(validate.call_args.kwargs["independent_colour"])
            with self.assertRaises(WorkerError):
                audit_prusa_dual_colour_gcode(
                    self.gcode(wrong_tool=True),b"controlled-xl-project",
                    printer_ini=b"owned-independent-xl",tools=(1,2),tower=None)
            with self.assertRaises(WorkerError):
                audit_prusa_dual_colour_gcode(
                    self.gcode(crossing=True),b"controlled-xl-project",
                    printer_ini=b"owned-independent-xl",tools=(1,2),tower=None)

    def test_non_distinct_and_unqualified_tool_assignments_rejected(self):
        from slicer_worker.prusa_colour_gcode_audit import _two_painted_wall_regions
        for tools in ((1,1),(0,2),(1,5),(True,2),(1,2,3)):
            with self.subTest(tools=tools),self.assertRaises(WorkerError):
                _two_painted_wall_regions(b"not-an-archive", tools)


class PrusaXLNativeColourAuditTests(TestCase):
    """Independent XL T0/Tn face painting never inherits MMU wipe semantics."""

    def project(self):
        stl,_mesh,_states,paint=fixture(include_paint=True)
        project=build_prusa_colour_candidate(
            {"asset_id":"xl-colour","x_mm":0,"y_mm":0,"z_mm":0,
             "rotation_deg":0,"scale_percent":100,"colour_paint":paint},
            stl,printer_ini=ini("0.4,0.4,0.4,0.4,0.4","0"),
            colour_tool_indices={1:1},bed_width=250,bed_depth=210)
        return project

    def output(self, *, wrong_tool=False, stationary=False):
        lines=["G90","M83","T1",";TYPE:External perimeter",
               "G0 X115 Y95"]
        for n in range(25):
            lines.append(("G1 E.03" if stationary else
                          f"G1 X{115+(n+1)*.5:.3f} Y95 E.03"))
        lines.extend(["T0",";TYPE:External perimeter","G0 X115 Y115"])
        for n in range(25):
            lines.append(f"G1 X{115+(n+1)*.5:.3f} Y115 E.03")
        if wrong_tool:
            lines.extend(["T1",";TYPE:External perimeter",
                          "G0 X115 Y115","G1 X115.5 Y115 E.03",
                          "G1 X116 Y115 E.03","G1 X116.5 Y115 E.03"])
        return ("\n".join(lines)+"\n").encode()

    def test_worker_proves_t1_front_and_t0_back_without_tower(self):
        from slicer_worker.prusa_colour_gcode_audit import audit_prusa_xl_colour_gcode
        receipt=audit_prusa_xl_colour_gcode(
            self.output(),self.project(),
            printer_ini=ini("0.4,0.4,0.4,0.4,0.4","0"),tool=1)
        self.assertEqual(receipt["painted_wall_moves"][1]["front"],25)
        self.assertEqual(receipt["painted_wall_moves"][0]["back"],25)
        self.assertIs(receipt["wipe_tower"],False)

    def test_unassigned_tools_and_wrong_wall_deposition_fail_closed(self):
        from slicer_worker.prusa_colour_gcode_audit import audit_prusa_xl_colour_gcode
        for raw in (self.output(wrong_tool=True),
                    self.output(stationary=True),
                    self.output().replace(b"T1",b"T7")):
            with self.subTest(raw=raw[-40:]),self.assertRaises(WorkerError):
                audit_prusa_xl_colour_gcode(
                    raw,self.project(),
                    printer_ini=ini("0.4,0.4,0.4,0.4,0.4","0"),tool=1)
        with self.assertRaises(WorkerError):
            audit_prusa_xl_colour_gcode(
                self.output(),self.project(),
                printer_ini=ini("0.4,0.4,0.4,0.4,0.4","1"),tool=1)
