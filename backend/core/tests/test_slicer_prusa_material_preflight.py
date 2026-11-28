"""Complete Prusa MMU candidate preflight stays private and non-dispatchable."""
from types import SimpleNamespace, ModuleType
from unittest import TestCase
from unittest.mock import patch, Mock
import uuid
import io
import zipfile

from core.slicer_prusa_material_preflight import (prepare_prusa_offline_mmu_candidate,
    prepare_prusa_offline_xl_candidate, slice_prusa_offline_mmu_candidate,
    slice_prusa_offline_xl_candidate)
from core.slicer_profiles import SlicerProfileError
from core.tests.test_slicer_prusa_machine_topology import ini
from core.tests.test_slicer_prusa_plate import cube, item
from slicer_worker.prusa_3mf_validation import validate_prusa_native_3mf
from slicer_worker.runner import WorkerError


def profile(kind, owner_id=42, engine="prusaslicer"):
    return SimpleNamespace(kind=kind, owner_id=owner_id, engine=engine,
                           engine_version="2.9.7")


class PrusaOfflineMmuPreflightTests(TestCase):
    @staticmethod
    def offline_worker_stub():
        # The lightweight worker contract intentionally lacks Django/requests.
        # Supply a module-local fake without importing the HTTP transport.
        module = ModuleType("core.slicer_worker_client")
        module.run_remote_job = Mock()
        return module.run_remote_job, patch.dict(
            "sys.modules", {"core.slicer_worker_client": module})

    def parts(self, *, owner_id=42):
        printer=profile("printer",owner_id)
        process=profile("process",owner_id)
        filaments=[profile("filament",owner_id) for _ in range(5)]
        raw_printer=ini("0.4,0.4,0.4,0.4,0.4","1")
        raw_process=b"layer_height = 0.2\nwipe_tower = 0\n"
        raw_filaments=[
            (f"filament_diameter = 1.75\ntemperature = {temp}\n"
             f"first_layer_temperature = {temp}\n").encode()
            for temp in (205,220,210,205,205)]
        data={
            "owner_id":owner_id,"printer_profile":printer,
            "process_profile":process,"filament_profiles":filaments,
            "rows":[(item(x_mm=-35),cube()),(item(x_mm=35),cube())],
            "tools":[1,2],
            "purge_matrix":[[0 if i==j else 80+20*i+j for j in range(5)]
                            for i in range(5)],
            "tower_xy":(55,150),"bed_width":250,"bed_depth":210,
        }
        return data,[raw_printer,raw_process,*raw_filaments]

    def test_fifteen_prusa_mmu_models_can_reuse_five_native_tools(self):
        from slicer_worker.prusa_material_validation import validate_prusa_material_candidate
        values, assets = self.parts()
        values["rows"] = [
            (item(x_mm=x_mm, y_mm=y_mm), cube(size=8))
            for y_mm in (-73, -43, 17)
            for x_mm in (-90, -45, 0, 45, 90)
        ]
        values["tools"] = list(range(1, 6)) * 3
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            prepared = prepare_prusa_offline_mmu_candidate(**values)
        self.assertEqual(prepared["expected_tools"], (1, 2, 3, 4, 5))
        self.assertEqual(
            validate_prusa_material_candidate(
                prepared["model"], printer_ini=prepared["printer"],
                tools=values["tools"], tower=prepared["tower"])["objects"], 15)
        values["rows"] = [values["rows"][0]] * 201
        values["tools"] = [1, 2] * 100 + [1]
        with self.assertRaisesRegex(SlicerProfileError, "models, tools"):
            prepare_prusa_offline_mmu_candidate(**values)

    def test_mmu_applies_only_bounded_owner_scoped_global_native_settings(self):
        values, assets = self.parts()
        assets[1] = (b"layer_height = 0.2\nperimeters = 2\n"
                     b"fill_density = 15%\ntop_solid_layers = 3\n"
                     b"bottom_solid_layers = 3\nwipe_tower = 0\n")
        values["process_overrides"] = {
            "layer_height": .16, "wall_loops": 4,
            "sparse_infill_density": 27, "top_shell_layers": 5,
        }
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            result = prepare_prusa_offline_mmu_candidate(**values)
        for setting in (b"layer_height = 0.16\n",
                        b"perimeters = 4\n",
                        b"fill_density = 27%\n",
                        b"top_solid_layers = 5\n",
                        b"wipe_tower = 1\n"):
            self.assertIn(setting, result["process"])
        self.assertIn(b"wiping_volumes_matrix = ", result["process"])

    def test_xl_keeps_overrides_but_never_adds_an_mmu_tower(self):
        values, assets = self.parts()
        assets[0] = ini("0.4,0.4,0.4,0.4,0.4", "0")
        assets[1] = b"layer_height = 0.2\nperimeters = 2\n"
        xl = {key: values[key] for key in (
            "owner_id", "printer_profile", "process_profile", "filament_profiles",
            "rows", "tools", "bed_width", "bed_depth")}
        xl["process_overrides"] = {"layer_height": .12, "wall_loops": 3}
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            result = prepare_prusa_offline_xl_candidate(**xl)
        self.assertIn(b"layer_height = 0.12\n", result["process"])
        self.assertIn(b"perimeters = 3\n", result["process"])
        self.assertNotIn(b"wipe_tower = 1", result["process"])

    def test_mmu_rejects_unsafe_process_overrides_before_worker(self):
        for bad in (
            {"layer_height": 1.5}, {"wall_loops": True},
            {"layer_height": float("inf")}, {"layer_height": "0.12"},
            {"post_process": "G28"}, [], False,
        ):
            with self.subTest(bad=bad):
                values, assets = self.parts()
                values["process_overrides"] = bad
                with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                           side_effect=assets):
                    with self.assertRaises(ValueError):
                        prepare_prusa_offline_mmu_candidate(**values)

    def test_front_painted_xl_owner_profiles_and_worker_contract(self):
        from core.slicer_prusa_material_preflight import (
            prepare_prusa_offline_xl_colour_candidate)
        from scripts.prusa_generate_mmu_paint import fixture
        from slicer_worker.service import _decode_payload
        import base64
        source, _mesh, _states, paint=fixture(include_paint=True)
        values,assets=self.parts()
        assets[0]=ini("0.4,0.4,0.4,0.4,0.4","0")
        row={"asset_id":"native-xl-front","x_mm":0,"y_mm":0,"z_mm":0,
             "rotation_deg":0,"scale_percent":100,"colour_paint":paint,
             "process_overrides":{"wall_loops":5,
                                  "sparse_infill_density":35}}
        params={key:values[key] for key in (
            "owner_id","printer_profile","process_profile",
            "filament_profiles","bed_width","bed_depth")}
        params.update(rows=[(row,source)],tools=[1],colour_tool_indices={1:1},
                      process_overrides={"layer_height": .16})
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            prepared=prepare_prusa_offline_xl_colour_candidate(**params)
        self.assertEqual(prepared["tool"],1)
        self.assertIn(b"layer_height = 0.16\n", prepared["process"])
        self.assertNotIn("tower",prepared)
        self.assertNotIn("wipe_tower = 1",prepared["process"].decode())
        from defusedxml import ElementTree as SafeET
        with zipfile.ZipFile(io.BytesIO(prepared["model"])) as archive:
            native=SafeET.fromstring(
                archive.read("Metadata/Slic3r_PE_model.config"))
        object_settings={node.get("key"):node.get("value")
                         for node in native.findall("./object/metadata")}
        self.assertEqual(object_settings["perimeters"],"5")
        self.assertEqual(object_settings["fill_density"],"35%")
        encode=lambda data:base64.b64encode(data).decode("ascii")
        request={"job_id":str(uuid.uuid4()),"engine":"prusaslicer",
                 "engine_version":"2.9.7","model_format":"3mf",
                 "model":encode(prepared["model"]),
                 "printer_profile":encode(prepared["printer"]),
                 "filament_profile":encode(prepared["filament"]),
                 "process_profile":encode(prepared["process"]),
                 "prusa_offline_xl_colour":{"tool":1}}
        self.assertEqual(
            _decode_payload(request)["prusa_offline_xl_colour"],
            {"tool":1,"partial_wall":False,"partial_top":False,"partial_slanted":False})
        for invalid in ({"tool":True},{"tool":5},{"tool":0},
                        {"tool":1,"tower":[55,150,0,250,210]}):
            with self.subTest(invalid=invalid),self.assertRaises(WorkerError):
                _decode_payload({**request,"prusa_offline_xl_colour":invalid})
        with self.assertRaises(WorkerError):
            _decode_payload({**request,"prusa_offline_mmu":{
                "tools":[1,2],"tower":[55,150,0,250,210]}})

    def test_indx_eight_head_printer_reuses_native_independent_paint(self):
        from core.slicer_prusa_material_preflight import prepare_prusa_offline_xl_colour_candidate
        from scripts.prusa_generate_mmu_paint import fixture
        from slicer_worker.service import _decode_payload
        import base64
        stl,_mesh,_states,paint=fixture(include_paint=True)
        values,assets=self.parts()
        assets[0]=ini(",".join(["0.4"]*8),"0")
        values["filament_profiles"]=[profile("filament") for _ in range(8)]
        assets=assets[:2]+[
            (b"filament_diameter = 1.75\ntemperature = 210\n"
             b"first_layer_temperature = 210\n") for _ in range(8)]
        settings={key:values[key] for key in (
            "owner_id","printer_profile","process_profile","filament_profiles",
            "bed_width","bed_depth")}
        settings.update(
            rows=[({"asset_id":"indx-paint","x_mm":0,"y_mm":0,"z_mm":0,
                    "rotation_deg":0,"scale_percent":100,"colour_paint":paint},stl)],
            tools=[1],colour_tool_indices={1:1})
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            result=prepare_prusa_offline_xl_colour_candidate(**settings)
        self.assertEqual(result["tool"],1)
        self.assertNotIn("tower",result)
        self.assertIsInstance(result["filament"], bytes)
        encode=lambda data:base64.b64encode(data).decode("ascii")
        payload={"job_id":str(uuid.uuid4()),"engine":"prusaslicer",
                 "engine_version":"2.9.7","model_format":"3mf",
                 "model":encode(result["model"]),
                 "printer_profile":encode(result["printer"]),
                 "filament_profile":encode(result["filament"]),
                 "process_profile":encode(result["process"]),
                 "prusa_offline_xl_colour":{"tool":1}}
        self.assertEqual(_decode_payload(payload)["prusa_offline_xl_colour"],
                         {"tool":1,"partial_wall":False,"partial_top":False,"partial_slanted":False})
        for alternate in (5,6,7):
            with self.subTest(native_tool=alternate):
                settings["colour_tool_indices"]={1:alternate}
                with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                           side_effect=assets):
                    mapped=prepare_prusa_offline_xl_colour_candidate(**settings)
                self.assertEqual(mapped["tool"],alternate)
                request={**payload,
                         "model":encode(mapped["model"]),
                         "prusa_offline_xl_colour":{"tool":alternate}}
                self.assertEqual(
                    _decode_payload(request)["prusa_offline_xl_colour"],
                    {"tool":alternate,"partial_wall":False,"partial_top":False,"partial_slanted":False})
        for invalid in (8,True,-1):
            with self.subTest(invalid=invalid),self.assertRaises(SlicerProfileError):
                settings["colour_tool_indices"]={1:invalid}
                with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                           side_effect=assets):
                    prepare_prusa_offline_xl_colour_candidate(**settings)

    def test_xl_two_painted_walls_use_native_independent_head_contract(self):
        from core.slicer_prusa_material_preflight import prepare_prusa_offline_xl_colour_candidate
        from core.slicer_plate_3mf import _triangles
        from core.slicer_native_support_paint import _fingerprint
        from scripts.prusa_generate_mmu_paint import fixture
        from slicer_worker.service import _decode_payload
        import base64
        source, _mesh, _states, paint = fixture(include_paint=True)
        triangles = list(_triangles(source))
        lo=[min(v[a] for face in triangles for v in face) for a in range(3)]
        hi=[max(v[a] for face in triangles for v in face) for a in range(3)]
        origin=((lo[0]+hi[0])/2,(lo[1]+hi[1])/2,lo[2])
        local=[[tuple(v[a]-origin[a] for a in range(3)) for v in face]
               for face in triangles]
        back=[{"face":i,"polygon":[list(v) for v in face]}
              for i,face in enumerate(local)
              if all(abs(v[1]-10)<1e-5 for v in face)]
        self.assertEqual(len(back),2)
        paint={**paint,"signature":_fingerprint(local),
               "palette":[*paint["palette"],{"color":"#fadd4d","label":"rear"}],
               "regions":[*paint["regions"],{"slot":2,"patches":back}]}
        values,assets=self.parts()
        assets[0]=ini("0.4,0.4,0.4,0.4,0.4","0")
        params={key:values[key] for key in (
            "owner_id","printer_profile","process_profile","filament_profiles",
            "bed_width","bed_depth")}
        params.update(rows=[({"asset_id":"xl-two-wall","x_mm":0,"y_mm":0,
                              "z_mm":0,"rotation_deg":0,"scale_percent":100,
                              "colour_paint":paint},source)],tools=[1],
                      colour_tool_indices={2:2,1:1},
                      process_overrides={"layer_height":.16})
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            candidate=prepare_prusa_offline_xl_colour_candidate(**params)
        self.assertEqual(candidate["tools"],[1,2])
        self.assertNotIn("tower",candidate)
        self.assertIn(b"layer_height = 0.16\n",candidate["process"])
        # The browser's saved colour IDs do not change when the model
        # rotates. The owner-scoped preflight must rediscover the opposite
        # wall ordering from the *baked native* 3MF, not the swatch list.
        rotated_row={**params["rows"][0][0],"rotation_deg":90}
        rotated_settings={**params,"rows":[(rotated_row,source)]}
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            rotated=prepare_prusa_offline_xl_colour_candidate(
                **rotated_settings)
        self.assertEqual(rotated["tools"],[2,1])
        self.assertNotIn("tower",rotated)
        encode=lambda data:base64.b64encode(data).decode("ascii")
        payload={"job_id":str(uuid.uuid4()),"engine":"prusaslicer",
                 "engine_version":"2.9.7","model_format":"3mf",
                 "model":encode(candidate["model"]),
                 "printer_profile":encode(candidate["printer"]),
                 "filament_profile":encode(candidate["filament"]),
                 "process_profile":encode(candidate["process"]),
                 "prusa_offline_xl_colour":{"tools":[1,2]}}
        self.assertEqual(_decode_payload(payload)["prusa_offline_xl_colour"],
                         {"tools":[1,2]})
        for wrong in ([1,1],[2,1],[1,5],[True,2]):
            with self.subTest(wrong=wrong),self.assertRaises(WorkerError):
                _decode_payload({**payload,"prusa_offline_xl_colour":{"tools":wrong}})
        with self.assertRaises(WorkerError):
            _decode_payload({**payload,"prusa_offline_xl_colour":{
                "tools":[1,2],"tower":[55,150,0,250,210]}})

    def test_xl_four_complete_walls_are_owner_bound_and_worker_authenticated(self):
        from core.slicer_prusa_material_preflight import (
            prepare_prusa_offline_xl_colour_candidate)
        from core.slicer_plate_3mf import _triangles
        from core.slicer_native_support_paint import _fingerprint
        from scripts.prusa_generate_mmu_paint import fixture
        from slicer_worker.service import _decode_payload
        import base64
        raw,_,_,paint=fixture(include_paint=True)
        faces=list(_triangles(raw))
        lo=[min(p[i] for face in faces for p in face) for i in range(3)]
        hi=[max(p[i] for face in faces for p in face) for i in range(3)]
        pivot=((lo[0]+hi[0])/2,(lo[1]+hi[1])/2,lo[2])
        local=[[tuple(p[i]-pivot[i] for i in range(3)) for p in face]
               for face in faces]
        selections=[]
        for axis,coord,slot in ((0,-10,1),(0,10,2),
                                (1,-10,3),(1,10,4)):
            patches=[{"face":index,"polygon":[list(p) for p in face]}
                     for index,face in enumerate(local)
                     if all(abs(p[axis]-coord)<.00001 for p in face)]
            self.assertEqual(len(patches),2)
            selections.append({"slot":slot,"patches":patches})
        painted={**paint,"signature":_fingerprint(local),
                 "palette":[{"color":"#aaaaaa","label":"base"}]+[
                     {"color":f"#{tool*0x202020:06X}","label":f"T{tool}"}
                     for tool in range(1,5)],
                 "regions":selections}
        values,assets=self.parts()
        assets[0]=ini("0.4,0.4,0.4,0.4,0.4","0")
        row={"asset_id":"four-colour-xl","x_mm":0,"y_mm":0,"z_mm":0,
             "rotation_deg":0,"scale_percent":100,"colour_paint":painted}
        params={key:values[key] for key in (
            "owner_id","printer_profile","process_profile",
            "filament_profiles","bed_width","bed_depth")}
        params.update(rows=[(row,raw)],tools=[1],
                      colour_tool_indices={1:1,2:2,3:3,4:4})
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            candidate=prepare_prusa_offline_xl_colour_candidate(**params)
        self.assertEqual(candidate["tools"],[1,2,3,4])
        self.assertNotIn("tower",candidate)
        encode=lambda value:base64.b64encode(value).decode("ascii")
        request={"job_id":str(uuid.uuid4()),"engine":"prusaslicer",
                 "engine_version":"2.9.7","model_format":"3mf",
                 "model":encode(candidate["model"]),
                 "printer_profile":encode(candidate["printer"]),
                 "filament_profile":encode(candidate["filament"]),
                 "process_profile":encode(candidate["process"]),
                 "prusa_offline_xl_colour":{"tools":[1,2,3,4]}}
        self.assertEqual(
            _decode_payload(request)["prusa_offline_xl_colour"],
            {"tools":[1,2,3,4]})
        for bad in ([2,1,3,4],[1,2,3,3],[1,2,3]):
            with self.subTest(bad=bad),self.assertRaises(WorkerError):
                _decode_payload({**request,
                                 "prusa_offline_xl_colour":{"tools":bad}})

    def test_single_front_painted_mmu_owns_tool_palette_tower_and_surface(self):
        from core.slicer_prusa_material_preflight import prepare_prusa_offline_colour_candidate
        from scripts.prusa_generate_mmu_paint import fixture
        values,assets=self.parts()
        source,_model,_states,paint=fixture(include_paint=True)
        row={"asset_id":"painted-model","x_mm":0,"y_mm":0,"z_mm":0,
             "rotation_deg":0,"scale_percent":100,"colour_paint":paint,
             "process_overrides":{"wall_loops":5,
                                  "sparse_infill_density":35}}
        colour={key:values[key] for key in (
            "owner_id","printer_profile","process_profile","filament_profiles",
            "purge_matrix","tower_xy","bed_width","bed_depth")}
        colour.update(rows=[(row,source)],tools=[1],
                      colour_slot=1,colour_tool=2,
                      process_overrides={"layer_height": .16})
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            candidate=prepare_prusa_offline_colour_candidate(**colour)
        self.assertEqual(candidate["tool"],2)
        self.assertIn(b"layer_height = 0.16\n", candidate["process"])
        self.assertEqual(candidate["tower"],(55,150,0,250,210))
        from slicer_worker.prusa_material_validation import validate_prusa_material_candidate
        receipt=validate_prusa_material_candidate(
            candidate["model"],printer_ini=candidate["printer"],colour=True,
            tower=candidate["tower"])
        self.assertEqual(receipt["tools"],(1,3))
        self.assertTrue(receipt["wipe_tower"])
        from defusedxml import ElementTree as SafeET
        with zipfile.ZipFile(io.BytesIO(candidate["model"])) as zipped:
            xml=SafeET.fromstring(
                zipped.read("Metadata/Slic3r_PE_model.config"))
        settings={node.get("key"):node.get("value")
                  for node in xml.findall("./object/metadata")}
        self.assertEqual(settings["perimeters"],"5")
        self.assertEqual(settings["fill_density"],"35%")
        from slicer_worker.service import _decode_payload
        import base64
        encode=lambda value:base64.b64encode(value).decode("ascii")
        payload={
            "job_id":str(uuid.uuid4()),"engine":"prusaslicer",
            "engine_version":"2.9.7","model_format":"3mf",
            "model":encode(candidate["model"]),
            "printer_profile":encode(candidate["printer"]),
            "filament_profile":encode(candidate["filament"]),
            "process_profile":encode(candidate["process"]),
            "prusa_offline_colour":{
                "tool":candidate["tool"],"tower":list(candidate["tower"])},
        }
        checked=_decode_payload(payload)
        self.assertEqual(checked["prusa_offline_colour"]["tool"],2)
        for corrupt in (
            {"tool":1,"tower":list(candidate["tower"])},
            {"tool":5,"tower":list(candidate["tower"])},
            {"tool":2,"tower":list(candidate["tower"]),"script":"G28"},
        ):
            with self.subTest(corrupt=corrupt), self.assertRaises(WorkerError):
                _decode_payload({**payload,"prusa_offline_colour":corrupt})
        with self.assertRaises(WorkerError):
            _decode_payload({**payload,"prusa_offline_xl":{"tools":[1,2]}})

    def test_owner_prusa_colour_compound_requires_both_spatial_audits(self):
        from core.slicer_prusa_material_preflight import (
            prepare_prusa_offline_colour_candidate,
            slice_prusa_offline_colour_candidate)
        from scripts.prusa_generate_mmu_paint import fixture
        from core.tests.test_slicer_prusa_3mf import volume
        values,assets=self.parts()
        source,_,_,paint=fixture(include_paint=True)
        modifier={**volume("modifier",{"sparse_infill_density":85}),
                  "width_mm":6,"x_mm":-6}
        cavity={**volume("negative"),"width_mm":6,"x_mm":6}
        row={"asset_id":"compound-owner","x_mm":0,"y_mm":0,
             "z_mm":0,"rotation_deg":0,"scale_percent":100,
             "colour_paint":paint,"process_overrides":{"wall_loops":4},
             "modifier_volumes":[modifier,cavity]}
        data={key:values[key] for key in (
            "owner_id","printer_profile","process_profile","filament_profiles",
            "purge_matrix","tower_xy","bed_width","bed_depth")}
        data.update(rows=[(row,source)],tools=[1],
                    colour_slot=1,colour_tool=1)
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            prepared=prepare_prusa_offline_colour_candidate(**data)
        self.assertEqual(prepared["tools"],(1,))
        self.assertTrue(prepared["compound_volume"])
        self.assertFalse(prepared["partial_wall"])
        from slicer_worker.prusa_offline_contract import validate_prusa_offline_colour_inputs
        receipt=validate_prusa_offline_colour_inputs(
            project=prepared["model"],printer=prepared["printer"],
            filament=prepared["filament"],process=prepared["process"],
            tool=1,tower=list(prepared["tower"]))
        self.assertTrue(receipt["compound_volume"])
        remote,context=self.offline_worker_stub()
        remote.return_value=b"fake-G-code"
        with context,patch(
            "core.slicer_prusa_material_preflight.prepare_prusa_offline_colour_candidate",
            return_value=prepared),patch(
            "slicer_worker.prusa_colour_gcode_audit.audit_prusa_offline_colour_gcode"
        ) as colour,patch(
            "slicer_worker.modifier_gcode_audit.audit_modifier_positive_e",
            return_value={"modifier_count":2,"negative_volume_count":1,
                          "modifier_region_paths":[10,0]}
        ) as cavities:
            output=slice_prusa_offline_colour_candidate(
                str(uuid.uuid4()),**data)
        colour.assert_called_once()
        cavities.assert_called_once_with(
            output,prepared["model"],"prusaslicer")
        self.assertEqual(output,b"fake-G-code")
        bad=dict(row)
        bad["modifier_volumes"]=[
            modifier,{**cavity,"shape":"sphere"}]
        data["rows"]=[(bad,source)]
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets),self.assertRaises(SlicerProfileError):
            prepare_prusa_offline_colour_candidate(**data)
        bad["modifier_volumes"]=[modifier,{**cavity,"x_mm":-6}]
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets),self.assertRaises(WorkerError):
            prepare_prusa_offline_colour_candidate(**data)

    def test_mmu_colour_and_opposite_fuzzy_owner_worker_both_require_deposition(self):
        from core.slicer_prusa_material_preflight import (
            prepare_prusa_offline_colour_candidate,
            slice_prusa_offline_colour_candidate)
        from core.slicer_plate_3mf import _triangles
        from core.slicer_native_support_paint import _fingerprint
        from scripts.prusa_generate_mmu_paint import fixture
        from slicer_worker.service import _decode_payload
        import base64
        values,assets=self.parts()
        source,_,_,paint=fixture(include_paint=True)
        faces=list(_triangles(source))
        low=[min(p[i] for face in faces for p in face) for i in range(3)]
        high=[max(p[i] for face in faces for p in face) for i in range(3)]
        center=((low[0]+high[0])/2,(low[1]+high[1])/2,low[2])
        local=[[tuple(p[i]-center[i] for i in range(3)) for p in face]
               for face in faces]
        back=[{"face":i,"polygon":[list(p) for p in face]}
              for i,face in enumerate(local)
              if all(abs(p[1]-10)<.00001 for p in face)]
        fuzzy={"version":2,"signature":_fingerprint(local),
               "regions":[{"slot":0,"patches":back}]}
        row={"asset_id":"native-colour-and-fuzzy",
             "x_mm":0,"y_mm":0,"z_mm":0,
             "rotation_deg":0,"scale_percent":100,
             "colour_paint":paint,"fuzzy_skin_paint":fuzzy}
        data={key:values[key] for key in (
            "owner_id","printer_profile","process_profile","filament_profiles",
            "purge_matrix","tower_xy","bed_width","bed_depth")}
        data.update(rows=[(row,source)],tools=[1],
                    colour_slot=1,colour_tool=1)
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            prepared=prepare_prusa_offline_colour_candidate(**data)
        self.assertTrue(prepared["colour_fuzzy"])
        self.assertFalse(prepared["partial_wall"])
        self.assertFalse(prepared["compound_volume"])
        encode=lambda body:base64.b64encode(body).decode("ascii")
        request={"job_id":str(uuid.uuid4()),"engine":"prusaslicer",
                 "engine_version":"2.9.7","model_format":"3mf",
                 "model":encode(prepared["model"]),
                 "printer_profile":encode(prepared["printer"]),
                 "filament_profile":encode(prepared["filament"]),
                 "process_profile":encode(prepared["process"]),
                 "prusa_offline_colour":{
                     "tool":1,"tower":list(prepared["tower"])}}
        receipt=_decode_payload(request)["prusa_offline_colour"]
        self.assertTrue(receipt["colour_fuzzy"])
        with self.assertRaises(WorkerError):
            _decode_payload({**request,"prusa_offline_colour":{
                **request["prusa_offline_colour"],"colour_fuzzy":True}})
        remote,context=self.offline_worker_stub()
        remote.return_value=b"native-mixed-colour-fuzzy"
        with context,patch(
            "core.slicer_prusa_material_preflight.prepare_prusa_offline_colour_candidate",
            return_value=prepared),patch(
            "slicer_worker.prusa_colour_gcode_audit.audit_prusa_offline_colour_gcode"
        ) as colour,patch(
            "slicer_worker.prusa_colour_fuzzy.audit_prusa_colour_fuzzy_gcode"
        ) as textured:
            output=slice_prusa_offline_colour_candidate(
                str(uuid.uuid4()),**data)
        colour.assert_called_once()
        textured.assert_called_once_with(output,prepared["model"])
        # A support channel on the same painted source must not be silently
        # dropped or accepted merely because the qualified fuzzy exists.
        invalid={**row,"support_paint":{"regions":[{"slot":0}]}}
        data["rows"]=[(invalid,source)]
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets),self.assertRaises(SlicerProfileError):
            prepare_prusa_offline_colour_candidate(**data)

    def test_partial_wall_mmu_is_authentically_admitted_and_full_wall_gate_stays_strict(self):
        from core.slicer_prusa_material_preflight import (
            prepare_prusa_offline_colour_candidate,
            slice_prusa_offline_colour_candidate)
        from core.slicer_plate_3mf import _triangles
        from core.slicer_native_support_paint import _fingerprint
        from scripts.prusa_generate_mmu_paint import fixture
        from slicer_worker.service import _decode_payload
        import base64
        values, assets = self.parts()
        source, _, _, paint = fixture(include_paint=True)
        faces = list(_triangles(source))
        low = [min(p[i] for face in faces for p in face) for i in range(3)]
        high = [max(p[i] for face in faces for p in face) for i in range(3)]
        origin = ((low[0]+high[0])/2, (low[1]+high[1])/2, low[2])
        local = [[tuple(v[i]-origin[i] for i in range(3)) for v in face]
                 for face in faces]
        target = paint["regions"][0]["patches"][0]["face"]
        a, b, c = local[target]
        partial = {**paint, "signature": _fingerprint(local),
                   "regions": [{"slot": 1, "patches": [{
                       "face": target,
                       "polygon": [list(a),
                                   [(a[i]+b[i])/2 for i in range(3)],
                                   [(a[i]+c[i])/2 for i in range(3)]],
                   }]}]}
        row = {"asset_id": "split-wall", "x_mm": 0, "y_mm": 0,
               "z_mm": 0, "rotation_deg": 0, "scale_percent": 100,
               "colour_paint": partial}
        colour = {key: values[key] for key in (
            "owner_id", "printer_profile", "process_profile",
            "filament_profiles", "purge_matrix", "tower_xy",
            "bed_width", "bed_depth")}
        colour.update(rows=[(row, source)], tools=[1],
                      colour_slot=1, colour_tool=1)
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            candidate = prepare_prusa_offline_colour_candidate(**colour)
        self.assertTrue(candidate["partial_wall"])
        request = {
            "job_id": str(uuid.uuid4()), "engine": "prusaslicer",
            "engine_version": "2.9.7", "model_format": "3mf",
            "model": base64.b64encode(candidate["model"]).decode(),
            "printer_profile": base64.b64encode(candidate["printer"]).decode(),
            "filament_profile": base64.b64encode(candidate["filament"]).decode(),
            "process_profile": base64.b64encode(candidate["process"]).decode(),
            "prusa_offline_colour": {
                "tool": candidate["tool"], "tower": list(candidate["tower"])},
        }
        decoded = _decode_payload(request)
        self.assertTrue(decoded["prusa_offline_colour"]["partial_wall"])
        # No browser-controlled skip-audit bit: derive it only from signed 3MF.
        with self.assertRaises(WorkerError):
            _decode_payload({**request, "prusa_offline_colour": {
                **request["prusa_offline_colour"], "partial_wall": False}})
        remote, context = self.offline_worker_stub()
        remote.return_value = b"audited worker G-code"
        with context, patch(
            "core.slicer_prusa_material_preflight.prepare_prusa_offline_colour_candidate",
            return_value=candidate), patch(
            "slicer_worker.prusa_partial_surface.audit_prusa_partial_wall_gcode"
        ) as audit:
            output = slice_prusa_offline_colour_candidate(
                str(uuid.uuid4()), **colour)
        self.assertEqual(output, b"audited worker G-code")
        audit.assert_called_once_with(
            output, candidate["model"], tool=1, tower=candidate["tower"])

        # The identical signed split-wall mask also qualifies the real XL5
        # independent-head path, but without MMU wipe-tower requirements.
        from core.slicer_prusa_material_preflight import (
            prepare_prusa_offline_xl_colour_candidate,
            slice_prusa_offline_xl_colour_candidate)
        assets[0] = ini("0.4,0.4,0.4,0.4,0.4", "0")
        xl = {key: colour[key] for key in (
            "owner_id", "printer_profile", "process_profile",
            "filament_profiles", "bed_width", "bed_depth", "rows", "tools")}
        xl["colour_tool_indices"] = {1: 1}
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            selected_xl = prepare_prusa_offline_xl_colour_candidate(**xl)
        self.assertTrue(selected_xl["partial_wall"])
        xl_request = {
            **request, "model": base64.b64encode(
                selected_xl["model"]).decode(),
            "printer_profile": base64.b64encode(
                selected_xl["printer"]).decode(),
            "filament_profile": base64.b64encode(
                selected_xl["filament"]).decode(),
            "process_profile": base64.b64encode(
                selected_xl["process"]).decode(),
        }
        xl_request.pop("prusa_offline_colour")
        xl_request["prusa_offline_xl_colour"] = {"tool": 1}
        self.assertEqual(_decode_payload(xl_request)[
            "prusa_offline_xl_colour"], {"tool": 1, "partial_wall": True,
                                         "partial_top": False,"partial_slanted": False})
        with self.assertRaises(WorkerError):
            _decode_payload({**xl_request,
                             "prusa_offline_xl_colour": {
                                 "tool": 1, "partial_wall": True}})
        remote, context = self.offline_worker_stub()
        remote.return_value = b"audited XL G-code"
        with context, patch(
            "core.slicer_prusa_material_preflight.prepare_prusa_offline_xl_colour_candidate",
            return_value=selected_xl), patch(
            "slicer_worker.prusa_partial_surface.audit_prusa_partial_wall_gcode"
        ) as xl_audit:
            output = slice_prusa_offline_xl_colour_candidate(
                str(uuid.uuid4()), **xl)
        xl_audit.assert_called_once_with(
            output, selected_xl["model"], tool=1)

    def test_rotated_partial_face_xl5_follows_signed_3d_worker_audit(self):
        from core.slicer_prusa_material_preflight import (
            prepare_prusa_offline_xl_colour_candidate,
            slice_prusa_offline_xl_colour_candidate)
        from core.slicer_plate_3mf import _triangles
        from core.slicer_native_support_paint import _fingerprint
        from scripts.prusa_generate_mmu_paint import fixture
        from slicer_worker.service import _decode_payload
        from slicer_worker.prusa_slanted_surface import inspect_prusa_slanted_surface
        import base64
        values,assets=self.parts()
        assets[0]=ini("0.4,0.4,0.4,0.4,0.4","0")
        stl,_,_,paint=fixture(include_paint=True)
        faces=list(_triangles(stl))
        lo=[min(p[a] for f in faces for p in f) for a in range(3)]
        hi=[max(p[a] for f in faces for p in f) for a in range(3)]
        origin=((lo[0]+hi[0])/2,(lo[1]+hi[1])/2,lo[2])
        local=[[tuple(p[a]-origin[a] for a in range(3)) for p in f]
               for f in faces]
        index=paint["regions"][0]["patches"][0]["face"]
        a,b,c=local[index]
        split={**paint,"signature":_fingerprint(local),
               "regions":[{"slot":1,"patches":[{"face":index,
                   "polygon":[list(a),
                       [(a[i]+b[i])/2 for i in range(3)],
                       [(a[i]+c[i])/2 for i in range(3)]]}]}]}
        row={"asset_id":"slanted-native","x_mm":0,"y_mm":0,"z_mm":0,
             "rotation_deg":0,"rotation_xyz_deg":[30,0],
             "scale_percent":100,"colour_paint":split}
        params={key:values[key] for key in (
            "owner_id","printer_profile","process_profile",
            "filament_profiles","bed_width","bed_depth")}
        params.update(rows=[(row,stl)],tools=[1],colour_tool_indices={1:1})
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            prepared=prepare_prusa_offline_xl_colour_candidate(**params)
        self.assertTrue(prepared["partial_slanted"])
        self.assertFalse(prepared["partial_top"])
        self.assertFalse(prepared["partial_wall"])
        self.assertGreater(
            abs(inspect_prusa_slanted_surface(
                prepared["model"],1)["normal"][2]), .1)
        encode=lambda body:base64.b64encode(body).decode("ascii")
        request={"job_id":str(uuid.uuid4()),"engine":"prusaslicer",
                 "engine_version":"2.9.7","model_format":"3mf",
                 "model":encode(prepared["model"]),
                 "printer_profile":encode(prepared["printer"]),
                 "filament_profile":encode(prepared["filament"]),
                 "process_profile":encode(prepared["process"]),
                 "prusa_offline_xl_colour":{"tool":1}}
        receipt=_decode_payload(request)
        self.assertTrue(receipt["prusa_offline_xl_colour"]["partial_slanted"])
        with self.assertRaises(WorkerError):
            _decode_payload({**request,"prusa_offline_xl_colour":{
                "tool":1,"partial_slanted":True}})
        remote,context=self.offline_worker_stub()
        remote.return_value=b"audited-slanted"
        with context,patch(
            "core.slicer_prusa_material_preflight.prepare_prusa_offline_xl_colour_candidate",
            return_value=prepared),patch(
            "slicer_worker.prusa_slanted_surface.audit_prusa_slanted_surface_gcode"
        ) as audit:
            output=slice_prusa_offline_xl_colour_candidate(
                str(uuid.uuid4()),**params)
        audit.assert_called_once_with(
            output,prepared["model"],tool=1)
        self.assertEqual(output,b"audited-slanted")

    def test_horizontal_top_brush_uses_separate_xl5_and_mmu_audits(self):
        from core.slicer_prusa_material_preflight import (
            prepare_prusa_offline_xl_colour_candidate,
            slice_prusa_offline_xl_colour_candidate,
            prepare_prusa_offline_colour_candidate,
            slice_prusa_offline_colour_candidate)
        from core.slicer_plate_3mf import _triangles
        from core.slicer_native_support_paint import _fingerprint
        from scripts.prusa_generate_mmu_paint import fixture
        from slicer_worker.service import _decode_payload
        import base64
        values,assets=self.parts()
        source,_,_,paint=fixture(include_paint=True)
        faces=list(_triangles(source))
        low=[min(p[i] for face in faces for p in face) for i in range(3)]
        high=[max(p[i] for face in faces for p in face) for i in range(3)]
        origin=((low[0]+high[0])/2,(low[1]+high[1])/2,low[2])
        local=[[tuple(p[i]-origin[i] for i in range(3)) for p in face]
               for face in faces]
        z=high[2]-low[2]
        face=next(i for i,tri in enumerate(local)
                  if all(abs(p[2]-z)<.00001 for p in tri))
        a,b,c=local[face]
        partial={**paint,"signature":_fingerprint(local),
                 "regions":[{"slot":1,"patches":[{"face":face,
                 "polygon":[list(a),
                            [(a[i]+b[i])/2 for i in range(3)],
                            [(a[i]+c[i])/2 for i in range(3)]]}]}]}
        row={"asset_id":"xl5-top-paint","x_mm":0,"y_mm":0,"z_mm":0,
             "rotation_deg":0,"scale_percent":100,"colour_paint":partial}
        params={key:values[key] for key in (
            "owner_id","printer_profile","process_profile","filament_profiles",
            "bed_width","bed_depth")}
        params.update(rows=[(row,source)],tools=[1],
                      colour_tool_indices={1:1})
        assets[0]=ini("0.4,0.4,0.4,0.4,0.4","0")
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            prepared=prepare_prusa_offline_xl_colour_candidate(**params)
        self.assertFalse(prepared["partial_wall"])
        self.assertTrue(prepared["partial_top"])
        encode=lambda payload:base64.b64encode(payload).decode("ascii")
        request={"job_id":str(uuid.uuid4()),"engine":"prusaslicer",
                 "engine_version":"2.9.7","model_format":"3mf",
                 "model":encode(prepared["model"]),
                 "printer_profile":encode(prepared["printer"]),
                 "filament_profile":encode(prepared["filament"]),
                 "process_profile":encode(prepared["process"]),
                 "prusa_offline_xl_colour":{"tool":1}}
        self.assertEqual(_decode_payload(request)["prusa_offline_xl_colour"],
                         {"tool":1,"partial_wall":False,"partial_top":True,"partial_slanted":False})
        with self.assertRaises(WorkerError):
            _decode_payload({**request,"prusa_offline_xl_colour":{
                "tool":1,"partial_top":True}})
        remote,context=self.offline_worker_stub()
        remote.return_value=b"audited-top"
        with context,patch(
            "core.slicer_prusa_material_preflight.prepare_prusa_offline_xl_colour_candidate",
            return_value=prepared),patch(
            "slicer_worker.prusa_top_surface.audit_prusa_partial_top_gcode"
        ) as audit:
            result=slice_prusa_offline_xl_colour_candidate(
                str(uuid.uuid4()),**params)
        self.assertEqual(result,b"audited-top")
        audit.assert_called_once_with(result,prepared["model"],tool=1)
        # The same mask independently qualifies MMU only when its native
        # single-nozzle tower metadata and two-tool purges are present.
        assets[0]=ini("0.4,0.4,0.4,0.4,0.4","1")
        mmu={key:values[key] for key in (
            "owner_id","printer_profile","process_profile","filament_profiles",
            "purge_matrix","tower_xy","bed_width","bed_depth")}
        mmu.update(rows=[(row,source)],tools=[1],
                   colour_slot=1,colour_tool=1)
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            prepared_mmu=prepare_prusa_offline_colour_candidate(**mmu)
        self.assertTrue(prepared_mmu["partial_top"])
        self.assertFalse(prepared_mmu["partial_wall"])
        mmu_request={**request,"model":encode(prepared_mmu["model"]),
                     "printer_profile":encode(prepared_mmu["printer"]),
                     "filament_profile":encode(prepared_mmu["filament"]),
                     "process_profile":encode(prepared_mmu["process"])}
        mmu_request.pop("prusa_offline_xl_colour")
        mmu_request["prusa_offline_colour"]={
            "tool":1,"tower":list(prepared_mmu["tower"])}
        decoded=_decode_payload(mmu_request)
        self.assertTrue(decoded["prusa_offline_colour"]["partial_top"])
        with self.assertRaises(WorkerError):
            _decode_payload({**mmu_request,"prusa_offline_colour":{
                **mmu_request["prusa_offline_colour"],"partial_top":True}})
        remote,context=self.offline_worker_stub()
        remote.return_value=b"audited-MMU-top"
        with context,patch(
            "core.slicer_prusa_material_preflight.prepare_prusa_offline_colour_candidate",
            return_value=prepared_mmu),patch(
            "slicer_worker.prusa_top_surface.audit_prusa_partial_top_gcode"
        ) as mmu_audit:
            result=slice_prusa_offline_colour_candidate(
                str(uuid.uuid4()),**mmu)
        self.assertEqual(result,b"audited-MMU-top")
        mmu_audit.assert_called_once_with(
            result,prepared_mmu["model"],tool=1,tower=prepared_mmu["tower"])

    def test_two_painted_mmu_walls_bind_explicit_tools_and_worker_bytes(self):
        from core.slicer_prusa_material_preflight import prepare_prusa_offline_colour_candidate
        from core.slicer_plate_3mf import _triangles
        from core.slicer_native_support_paint import _fingerprint
        from scripts.prusa_generate_mmu_paint import fixture
        from slicer_worker.service import _decode_payload
        import base64
        source, _mesh, _states, paint = fixture(include_paint=True)
        triangles = list(_triangles(source))
        lo = [min(p[a] for tri in triangles for p in tri) for a in range(3)]
        hi = [max(p[a] for tri in triangles for p in tri) for a in range(3)]
        centre = ((lo[0]+hi[0])/2,(lo[1]+hi[1])/2,lo[2])
        local = [[tuple(p[a]-centre[a] for a in range(3)) for p in tri]
                 for tri in triangles]
        back = [{"face":i,"polygon":[list(p) for p in tri]}
                for i,tri in enumerate(local)
                if all(abs(p[1]-10)<1e-5 for p in tri)]
        self.assertEqual(len(back),2)
        paint = {**paint, "signature":_fingerprint(local),
                 "palette":[*paint["palette"],{"color":"#fadd4d","label":"rear"}],
                 "regions":[*paint["regions"],{"slot":2,"patches":back}]}
        values,assets = self.parts()
        settings = {key:values[key] for key in (
            "owner_id","printer_profile","process_profile","filament_profiles",
            "purge_matrix","tower_xy","bed_width","bed_depth")}
        settings.update(rows=[({"asset_id":"two-swatch","x_mm":0,"y_mm":0,
                               "z_mm":0,"rotation_deg":0,"scale_percent":100,
                               "colour_paint":paint},source)],tools=[1],
                        colour_tool_indices={2:2,1:1})
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            candidate=prepare_prusa_offline_colour_candidate(**settings)
        self.assertEqual(candidate["tools"],(1,2))
        self.assertNotIn("tool",candidate)
        encode=lambda value:base64.b64encode(value).decode("ascii")
        payload={
            "job_id":str(uuid.uuid4()),"engine":"prusaslicer",
            "engine_version":"2.9.7","model_format":"3mf",
            "model":encode(candidate["model"]),
            "printer_profile":encode(candidate["printer"]),
            "filament_profile":encode(candidate["filament"]),
            "process_profile":encode(candidate["process"]),
            "prusa_offline_colour":{"tools":[1,2],"tower":list(candidate["tower"])},
        }
        checked=_decode_payload(payload)
        self.assertEqual(checked["prusa_offline_colour"]["tools"],[1,2])
        for wrong in ([1,1],[2,1],[1,5],[True,2]):
            with self.subTest(wrong=wrong),self.assertRaises(WorkerError):
                _decode_payload({**payload,"prusa_offline_colour":{
                    "tools":wrong,"tower":list(candidate["tower"])}})

    def test_signed_two_partial_mmu_colours_keep_independent_worker_audit(self):
        from core.slicer_prusa_material_preflight import (
            prepare_prusa_offline_colour_candidate,
            slice_prusa_offline_colour_candidate)
        from core.slicer_plate_3mf import _triangles
        from core.slicer_native_support_paint import _fingerprint
        from scripts.prusa_generate_mmu_paint import fixture
        from slicer_worker.service import _decode_payload
        import base64
        source,_,_,paint=fixture(include_paint=True)
        faces=list(_triangles(source))
        lo=[min(p[i] for face in faces for p in face) for i in range(3)]
        hi=[max(p[i] for face in faces for p in face) for i in range(3)]
        origin=((lo[0]+hi[0])/2,(lo[1]+hi[1])/2,lo[2])
        local=[[tuple(p[i]-origin[i] for i in range(3)) for p in face]
               for face in faces]
        regions=[]
        for slot,side in ((1,-10),(2,10)):
            index=next(i for i,face in enumerate(local)
                       if all(abs(p[1]-side)<.00001 for p in face))
            a,b,c=local[index]
            regions.append({"slot":slot,"patches":[{
                "face":index,"polygon":[list(a),
                    [(a[i]+b[i])/2 for i in range(3)],
                    [(a[i]+c[i])/2 for i in range(3)]]}]})
        painted={**paint,"signature":_fingerprint(local),
                 "palette":[*paint["palette"],
                            {"color":"#fadd4d","label":"native T2"}],
                 "regions":regions}
        values,assets=self.parts()
        plan={key:values[key] for key in (
            "owner_id","printer_profile","process_profile","filament_profiles",
            "purge_matrix","tower_xy","bed_width","bed_depth")}
        row={"asset_id":"two-partial","x_mm":0,"y_mm":0,"z_mm":0,
             "rotation_deg":0,"scale_percent":100,"colour_paint":painted}
        plan.update(rows=[(row,source)],tools=[1],
                    colour_tool_indices={2:2,1:1})
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            prepared=prepare_prusa_offline_colour_candidate(**plan)
        self.assertEqual(prepared["tools"],(1,2))
        self.assertTrue(prepared["dual_partial"])
        encode=lambda data:base64.b64encode(data).decode("ascii")
        request={"job_id":str(uuid.uuid4()),"engine":"prusaslicer",
                 "engine_version":"2.9.7","model_format":"3mf",
                 "model":encode(prepared["model"]),
                 "printer_profile":encode(prepared["printer"]),
                 "filament_profile":encode(prepared["filament"]),
                 "process_profile":encode(prepared["process"]),
                 "prusa_offline_colour":{
                     "tools":[1,2],"tower":list(prepared["tower"])}}
        decoded=_decode_payload(request)
        self.assertTrue(decoded["prusa_offline_colour"]["dual_partial"])
        with self.assertRaises(WorkerError):
            _decode_payload({**request,"prusa_offline_colour":{
                "tools":[1,2],"tower":list(prepared["tower"]),
                "dual_partial":True}})
        remote,context=self.offline_worker_stub()
        remote.return_value=b"verified-two-partial"
        with context,patch(
            "core.slicer_prusa_material_preflight.prepare_prusa_offline_colour_candidate",
            return_value=prepared),patch(
            "slicer_worker.prusa_dual_partial.audit_prusa_dual_partial_gcode"
        ) as audit:
            result=slice_prusa_offline_colour_candidate(
                str(uuid.uuid4()),**plan)
        self.assertEqual(result,b"verified-two-partial")
        audit.assert_called_once_with(
            result,prepared["model"],printer_ini=prepared["printer"],
            tools=prepared["tools"],tower=prepared["tower"])

    def test_painted_mmu_refuses_foreign_preset_before_reading_any_file(self):
        from core.slicer_prusa_material_preflight import prepare_prusa_offline_colour_candidate
        from scripts.prusa_generate_mmu_paint import fixture
        values,_assets=self.parts()
        source,_model,_states,paint=fixture(include_paint=True)
        colour={key:values[key] for key in (
            "owner_id","printer_profile","process_profile","filament_profiles",
            "purge_matrix","tower_xy","bed_width","bed_depth")}
        colour.update(
            rows=[({"x_mm":0,"y_mm":0,"colour_paint":paint},source)],
            tools=[1],colour_slot=1,colour_tool=1)
        colour["filament_profiles"][1]=profile("filament",owner_id=77)
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile") as source_profile:
            with self.assertRaises(SlicerProfileError):
                prepare_prusa_offline_colour_candidate(**colour)
        source_profile.assert_not_called()

    def test_complete_candidate_roundtrips_but_worker_refuses_admission(self):
        values,assets=self.parts()
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets) as load:
            result=prepare_prusa_offline_mmu_candidate(**values)
        self.assertEqual(load.call_count,7)
        self.assertEqual(result["expected_tools"],(1,2))
        self.assertTrue(result["research_only"])
        self.assertEqual(result["topology"],"single_nozzle_changer")
        self.assertIn(b"temperature = 205,220,210,205,205\n",result["filament"])
        self.assertIn(b"wiping_volumes_matrix = 0,81",result["process"])
        with zipfile.ZipFile(io.BytesIO(result["model"])) as archive:
            self.assertIn("Metadata/Prusa_Slicer_wipe_tower_information.xml",
                          archive.namelist())
        with self.assertRaises(WorkerError):
            validate_prusa_native_3mf(result["model"])

    def test_foreign_profile_refused_without_reading_private_assets(self):
        for kind in ("printer","process","filament"):
            with self.subTest(kind=kind):
                values,_=self.parts()
                if kind=="filament":
                    values["filament_profiles"][3]=profile("filament",43)
                else:
                    values[kind+"_profile"]=profile(kind,43)
                with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile") as load:
                    with self.assertRaises(SlicerProfileError):
                        prepare_prusa_offline_mmu_candidate(**values)
                load.assert_not_called()

    def test_xl_and_wrong_tower_or_model_tools_rejected(self):
        values,assets=self.parts()
        for name,change in (
            ("xl",{"raw_printer":ini("0.4,0.4,0.4,0.4,0.4","0")}),
            ("wrong tool",{"tools":[1,6]}),
            ("unsafe tower",{"tower_xy":(249,150)}),
            ("wrong purge",{"purge_matrix":[[0,80],[80,0]]}),
        ):
            with self.subTest(name=name):
                data=dict(values)
                next_assets=list(assets)
                if "raw_printer" in change:
                    next_assets[0]=change["raw_printer"]
                else:
                    data.update(change)
                with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                           side_effect=next_assets):
                    with self.assertRaises((SlicerProfileError,ValueError,WorkerError)):
                        prepare_prusa_offline_mmu_candidate(**data)

    def test_independent_xl_uses_no_mmu_purge_or_tower(self):
        values,assets=self.parts()
        assets[0]=ini("0.4,0.4,0.4,0.4,0.4","0")
        xl={k:values[k] for k in (
            "owner_id","printer_profile","process_profile","filament_profiles",
            "rows","tools","bed_width","bed_depth")}
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            result=prepare_prusa_offline_xl_candidate(**xl)
        self.assertEqual(result["topology"],"independent_tools")
        self.assertTrue(result["research_only"])
        self.assertEqual(result["process"],assets[1])
        self.assertIn(b"temperature = 205,220,210,205,205",result["filament"])
        with zipfile.ZipFile(io.BytesIO(result["model"])) as archive:
            self.assertNotIn("Metadata/Prusa_Slicer_wipe_tower_information.xml",
                             archive.namelist())
        with self.assertRaises(WorkerError):
            validate_prusa_native_3mf(result["model"])

    def test_xl_does_not_accept_mmu_or_foreign_filaments(self):
        values,assets=self.parts()
        xl={k:values[k] for k in (
            "owner_id","printer_profile","process_profile","filament_profiles",
            "rows","tools","bed_width","bed_depth")}
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            with self.assertRaises(SlicerProfileError):
                prepare_prusa_offline_xl_candidate(**xl)
        xl["filament_profiles"][1]=profile("filament",43)
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile") as load:
            with self.assertRaises(SlicerProfileError):
                prepare_prusa_offline_xl_candidate(**xl)
        load.assert_not_called()

    def test_indx_six_to_eight_tools_use_independent_native_worker(self):
        for n in (6, 7, 8):
            with self.subTest(logical_tools=n):
                values, assets = self.parts()
                values["filament_profiles"] += [profile("filament") for _ in range(n-5)]
                assets += [assets[-1]] * (n-5)
                values["tools"] = [1, n]
                xl = {key: values[key] for key in (
                    "owner_id", "printer_profile", "process_profile",
                    "filament_profiles", "rows", "tools", "bed_width", "bed_depth")}
                assets[0] = ini(",".join(["0.4"]*n), "0")
                with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                           side_effect=assets):
                    result = prepare_prusa_offline_xl_candidate(**xl)
                self.assertEqual(result["topology"], "indx")
                self.assertEqual(result["expected_tools"], (1,n))
                self.assertNotIn(b"wipe_tower = 1", result["process"])


    def test_indx_owner_project_preserves_native_modifier_and_cavity(self):
        from core.tests.test_slicer_prusa_3mf import volume
        from slicer_worker.prusa_material_validation import validate_prusa_material_candidate
        values,assets=self.parts()
        values["filament_profiles"] += [profile("filament") for _ in range(3)]
        assets += [assets[-1]] * 3
        assets[0]=ini(",".join(["0.4"]*8),"0")
        modifier=volume("modifier",{"sparse_infill_density":75})
        modifier.update(width_mm=3,depth_mm=3,height_mm=5,x_mm=-35,y_mm=0,z_mm=4)
        cavity=volume("negative",{})
        cavity.update(width_mm=3,depth_mm=3,height_mm=5,x_mm=35,y_mm=0,z_mm=4)
        values["rows"]=[
            (item(x_mm=-35,modifier_volumes=[modifier]),cube()),
            (item(x_mm=35,modifier_volumes=[cavity],
                  variable_layer_profile={"version":1,"bands":[
                      {"from_mm":2,"to_mm":6,"layer_mm":.12}]}),cube())]
        values["tools"]=[1,8]
        xl={key:values[key] for key in
            ("owner_id","printer_profile","process_profile",
             "filament_profiles","rows","tools","bed_width","bed_depth")}
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            candidate=prepare_prusa_offline_xl_candidate(**xl)
        from defusedxml import ElementTree as SafeET
        with zipfile.ZipFile(io.BytesIO(candidate["model"])) as archive:
            config=SafeET.fromstring(archive.read("Metadata/Slic3r_PE_model.config"))
        self.assertEqual(len(config.findall("object")),2)
        self.assertEqual(sum(len(obj.findall("volume"))-1
                             for obj in config.findall("object")),2)
        with zipfile.ZipFile(io.BytesIO(candidate["model"])) as archive:
            self.assertIn("Metadata/Prusa_Slicer_layer_config_ranges.xml",
                          archive.namelist())
        self.assertEqual(validate_prusa_material_candidate(
            candidate["model"],printer_ini=assets[0],tools=[1,8])["tools"],(1,8))

    def test_five_explicit_mmu_models_preserve_tool_order(self):
        values,assets=self.parts()
        values["rows"]=[
            (item(x_mm=x),cube()) for x in (-88,-44,0,44,88)]
        values["tools"]=[5,3,1,2,4]
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            result=prepare_prusa_offline_mmu_candidate(**values)
        self.assertEqual(result["expected_tools"],(1,2,3,4,5))
        with zipfile.ZipFile(io.BytesIO(result["model"])) as archive:
            from defusedxml import ElementTree as SafeET
            model=SafeET.fromstring(archive.read("Metadata/Slic3r_PE_model.config"))
        selected=[
            meta.get("value") for obj in model.findall("object")
            for meta in obj.findall("metadata") if meta.get("key")=="extruder"]
        self.assertEqual(selected,["5","3","1","2","4"])

    def test_five_independent_xl_heads_preserve_explicit_tool_order(self):
        values,assets=self.parts()
        assets[0]=ini("0.4,0.4,0.4,0.4,0.4","0")
        xl={key:values[key] for key in (
            "owner_id","printer_profile","process_profile","filament_profiles",
            "rows","tools","bed_width","bed_depth")}
        xl["rows"]=[(item(x_mm=x),cube()) for x in (-88,-44,0,44,88)]
        xl["tools"]=[5,3,1,2,4]
        xl["bed_width"]=360
        xl["bed_depth"]=360
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            result=prepare_prusa_offline_xl_candidate(**xl)
        self.assertEqual(result["expected_tools"],(1,2,3,4,5))
        self.assertEqual(result["topology"],"independent_tools")
        with zipfile.ZipFile(io.BytesIO(result["model"])) as archive:
            from defusedxml import ElementTree as SafeET
            self.assertNotIn("Metadata/Prusa_Slicer_wipe_tower_information.xml",
                             archive.namelist())
            model=SafeET.fromstring(archive.read("Metadata/Slic3r_PE_model.config"))
        selected=[
            meta.get("value") for obj in model.findall("object")
            for meta in obj.findall("metadata") if meta.get("key")=="extruder"]
        self.assertEqual(selected,["5","3","1","2","4"])

    def test_ephemeral_owned_mmu_executor_audits_worker_result(self):
        remote, scope = self.offline_worker_stub()
        scope.start()
        self.addCleanup(scope.stop)
        values,assets=self.parts()
        from core.tests.test_slicer_prusa_material_gcode_audit import toolpaths
        remote.return_value=toolpaths(include_tower=True)
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            output=slice_prusa_offline_mmu_candidate(uuid.uuid4(),**values)
        self.assertEqual(output,toolpaths(include_tower=True))
        self.assertEqual(remote.call_args.kwargs["prusa_offline_mmu"],
                         {"tools":[1,2],"tower":[55,150,0,250,210]})
        self.assertEqual(remote.call_args.kwargs["model_format"],"3mf")
        self.assertEqual(remote.call_args.args[1:3],("prusaslicer","2.9.7"))

    def test_ephemeral_mmu_worker_never_receives_foreign_profiles(self):
        remote, scope = self.offline_worker_stub()
        scope.start()
        self.addCleanup(scope.stop)
        values,_=self.parts()
        values["filament_profiles"][1]=profile("filament",43)
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile") as load:
            with self.assertRaises(SlicerProfileError):
                slice_prusa_offline_mmu_candidate(uuid.uuid4(),**values)
        load.assert_not_called()
        remote.assert_not_called()

    def test_ephemeral_mmu_worker_refuses_misassigned_output(self):
        remote, scope = self.offline_worker_stub()
        scope.start()
        self.addCleanup(scope.stop)
        values,assets=self.parts()
        from core.tests.test_slicer_prusa_material_gcode_audit import toolpaths
        remote.return_value=toolpaths(leak=True,include_tower=True)
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            with self.assertRaises(WorkerError):
                slice_prusa_offline_mmu_candidate(uuid.uuid4(),**values)

    def test_independent_head_variable_layers_require_actual_object_z_audit(self):
        values, assets = self.parts()
        assets[0] = ini("0.4,0.4,0.4,0.4,0.4", "0")
        kwargs = {key: values[key] for key in (
            "owner_id", "printer_profile", "process_profile",
            "filament_profiles", "rows", "tools", "bed_width", "bed_depth")}
        kwargs["rows"] = list(values["rows"])
        model = dict(kwargs["rows"][0][0])
        model["variable_layer_profile"] = {"version": 1, "bands": [
            {"from_mm": 2, "to_mm": 6, "layer_mm": .12}]}
        kwargs["rows"][0] = (model, kwargs["rows"][0][1])
        remote, scope = self.offline_worker_stub()
        scope.start()
        self.addCleanup(scope.stop)
        remote.return_value = b"test audited toolpath"
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets) as resolved, patch(
                       "slicer_worker.prusa_material_gcode_audit.audit_prusa_material_model_gcode"
                   ) as tools_audit, patch(
                       "core.slicer_prusa_spatial_layers.audit_prusa_multi_object_layer_ranges",
                       return_value=[{"object": 1, "verified_steps": 20}]
                   ) as layer_audit:
            result = slice_prusa_offline_xl_candidate(uuid.uuid4(), **kwargs)
            self.assertEqual(result, remote.return_value)
            tools_audit.assert_called_once()
            layer_audit.assert_called_once()
            self.assertEqual(layer_audit.call_args.kwargs["base_layer_mm"], .2)
            self.assertEqual(layer_audit.call_args.kwargs["bed_width"], 250)

            layer_audit.side_effect = ValueError("wrong layer schedule")
            resolved.side_effect = assets
            with self.assertRaisesRegex(SlicerProfileError,
                                         "did not preserve each requested"):
                slice_prusa_offline_xl_candidate(uuid.uuid4(), **kwargs)

    def test_ephemeral_xl_offline_executor_enforces_independent_topology(self):
        values,assets=self.parts()
        assets[0]=ini("0.4,0.4,0.4,0.4,0.4","0")
        arguments={k:values[k] for k in (
            "owner_id","printer_profile","process_profile","filament_profiles",
            "rows","tools","bed_width","bed_depth")}
        from core.tests.test_slicer_prusa_material_gcode_audit import toolpaths
        remote,scope=self.offline_worker_stub()
        scope.start()
        self.addCleanup(scope.stop)
        remote.return_value=toolpaths()
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            result=slice_prusa_offline_xl_candidate(uuid.uuid4(),**arguments)
        self.assertEqual(result,toolpaths())
        self.assertEqual(remote.call_args.kwargs["prusa_offline_xl"],{"tools":[1,2]})
        self.assertNotIn("prusa_offline_mmu",remote.call_args.kwargs)
        self.assertEqual(remote.call_args.kwargs["model_format"],"3mf")

