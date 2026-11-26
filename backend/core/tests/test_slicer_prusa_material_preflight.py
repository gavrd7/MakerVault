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
    return SimpleNamespace(kind=kind, owner_id=owner_id, engine=engine)


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

    def test_indx_scale_tools_do_not_enter_xl_offline_worker(self):
        values,assets=self.parts()
        values["filament_profiles"].append(profile("filament"))
        values["tools"]=[1,6]
        xl={key:values[key] for key in (
            "owner_id","printer_profile","process_profile","filament_profiles",
            "rows","tools","bed_width","bed_depth")}
        assets[0]=ini(",".join(["0.4"]*6),"0")
        assets.append(assets[-1])
        with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
                   side_effect=assets):
            with self.assertRaises(SlicerProfileError):
                prepare_prusa_offline_xl_candidate(**xl)

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

