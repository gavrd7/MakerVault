"""Prusa-only workbench admission: never reinterpret physical slots as tools."""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from core.slicer_prusa_job_material import (
    prepare_prusa_workbench_material, slice_prusa_workbench_material,
)
from core.slicer_profiles import SlicerProfileError
from core.tests.test_slicer_prusa_machine_topology import ini


def profile(kind, pk, owner=42, engine="prusaslicer"):
    return SimpleNamespace(
        pk=pk, owner_id=owner, kind=kind, engine=engine,
        engine_version="2.9.7",
    )


def fixture(kind="mmu", count=2):
    printer=profile("printer", 100)
    process=profile("process", 101)
    filaments=[profile("filament", n + 1) for n in range(count)]
    slots=["explicit-slot-" + str(n) for n in range(count)]
    objects=[
        {"asset_id":str(n+1), "x_mm": (-35 + n * 70), "y_mm":0,
         "z_mm":0,"material_slot":{"slot_id":slots[n],
            "printer_id":"42-printer", "slot_index":n}}
        for n in range(2)
    ]
    settings={
        "multi_material_test":True,
        "material_topology":"single_nozzle_changer" if kind=="mmu"
                            else "independent_toolheads",
        "plate_objects":objects,
        "material_tool_bindings":[
            {"slot_id":slot, "tool_index":n} for n,slot in enumerate(slots)],
        "slot_filament_profiles":[
            {"slot_id":slot, "profile_id":str(n+1)}
            for n,slot in enumerate(slots)],
    }
    if kind=="mmu":
        settings["prime_tower"]={"x":55,"y":150}
        settings["flush_settings"]={
            "multiplier":None,"prime_tower":"enabled",
            "transitions":[{"from_slot_id":a,"to_slot_id":b,"volume_mm3":80}
                for a in slots for b in slots if a != b],
        }
    job=SimpleNamespace(
        pk="job-id",engine="prusaslicer",engine_version="2.9.7",
        printer_id="42-printer",owner_id=42,
        printer_profile_id=100,printer_profile=printer,
        process_profile_id=101,process_profile=process,
        filament_profile_id=1,settings=settings,
    )
    raw=ini(",".join(["0.4"]*count), "1" if kind=="mmu" else "0")
    return job,filaments,raw


class PrusaWorkbenchMaterialTests(TestCase):
    def resolve(self, job, filaments, raw):
        from contextlib import ExitStack
        scope=ExitStack()
        self.addCleanup(scope.close)
        scope.enter_context(patch(
            "core.slicer_prusa_job_material.resolved_prusa_profile",
            return_value=raw))
        scope.enter_context(patch(
            "core.slicer_prusa_job_material.trusted_plate_dimensions",
            return_value=(250,210)))
        lookup=scope.enter_context(patch(
            "core.slicer_prusa_job_material.SlicerProfile.objects.filter",
            return_value=filaments))
        return lookup

    def test_mmu_two_tools_and_all_directional_transitions(self):
        job,filaments,raw=fixture()
        lookup=self.resolve(job,filaments,raw)
        kind,plan=prepare_prusa_workbench_material(job)
        self.assertEqual(kind,"mmu")
        self.assertEqual(plan["tools"],[1,2])
        self.assertEqual(plan["purge_matrix"],[[0,80],[80,0]])
        self.assertEqual(plan["tower_xy"],(55,150))
        self.assertEqual(plan["filament_profiles"],filaments)
        self.assertEqual(lookup.call_args.kwargs["owner_id"],42)

    def test_xl_multi_head_path_has_no_mmu_purge(self):
        job,filaments,raw=fixture("xl")
        self.resolve(job,filaments,raw)
        kind,plan=prepare_prusa_workbench_material(job)
        self.assertEqual(kind,"xl")
        self.assertEqual(plan["tools"],[1,2])
        self.assertNotIn("purge_matrix",plan)
        self.assertNotIn("tower_xy",plan)

    def test_dispatch_uses_the_qualified_owner_bound_worker(self):
        job,filaments,raw=fixture()
        self.resolve(job,filaments,raw)
        with patch("core.slicer_prusa_job_material.slice_prusa_offline_mmu_candidate",
                   return_value=b"audited-gcode") as worker:
            result=slice_prusa_workbench_material(
                job,[(dict(row),b"stl") for row in job.settings["plate_objects"]])
        self.assertEqual(result,b"audited-gcode")
        self.assertEqual(worker.call_args.args,("job-id",))
        self.assertEqual(worker.call_args.kwargs["tools"],[1,2])
        self.assertEqual(len(worker.call_args.kwargs["rows"]),2)

    def test_validated_physical_slots_are_excluded_from_native_project(self):
        job, filaments, raw = fixture()
        self.resolve(job, filaments, raw)
        source = [(dict(row), b"native-stl") for row in job.settings["plate_objects"]]
        with patch("core.slicer_prusa_job_material.slice_prusa_offline_mmu_candidate",
                   return_value=b"audited-gcode") as run:
            self.assertEqual(slice_prusa_workbench_material(job,source),b"audited-gcode")
        native = run.call_args.kwargs["rows"]
        self.assertEqual(len(native), 2)
        self.assertTrue(all("material_slot" not in row for row,_ in native))
        self.assertEqual([raw for _,raw in native],[b"native-stl"]*2)
        self.assertEqual([row["material_slot"]["slot_id"] for row,_ in source],
                         ["explicit-slot-0","explicit-slot-1"])
        self.assertEqual(run.call_args.kwargs["tools"],[1,2])

    def test_qualified_global_overrides_follow_the_tool_and_filament_plan(self):
        for mode in ("mmu", "xl"):
            with self.subTest(mode=mode):
                job,filaments,raw=fixture(mode)
                self.resolve(job,filaments,raw)
                job.settings["process_overrides"] = {
                    "layer_height":.16, "wall_loops":3,
                    "sparse_infill_density":25,
                    "outer_wall_speed":25, "inner_wall_speed":45,
                    "sparse_infill_speed":60, "travel_speed":140,
                    "top_surface_speed":30,
                }
                kind,plan=prepare_prusa_workbench_material(job)
                self.assertEqual(kind,mode)
                self.assertEqual(plan["process_overrides"],job.settings["process_overrides"])
                with patch("core.slicer_prusa_job_material.slice_prusa_offline_"+
                           ("mmu" if mode=="mmu" else "xl")+"_candidate",
                           return_value=b"audited-gcode") as run:
                    slice_prusa_workbench_material(job,[
                        (dict(item),b"stl") for item in job.settings["plate_objects"]])
                self.assertEqual(run.call_args.kwargs["process_overrides"],
                                 job.settings["process_overrides"])

    def test_native_advanced_geometry_is_forwarded_to_mmu_xl_and_indx(self):
        for mode, count in (("xl", 2), ("xl", 5), ("xl", 8)):
            with self.subTest(mode=mode, count=count):
                job, filaments, raw = fixture(mode, count)
                self.resolve(job, filaments, raw)
                job.settings["plate_objects"][0]["modifier_volumes"] = [{
                    "id": "checked-native-region", "kind": "modifier"
                }]
                job.settings["plate_objects"][1]["variable_layer_profile"] = {
                    "version": 1, "bands": [
                        {"from_mm": 2, "to_mm": 6, "layer_mm": .12}]}
                kind, plan = prepare_prusa_workbench_material(job)
                self.assertEqual(kind, "indx" if count > 5 else "xl")
                self.assertEqual(plan["tools"], [1, 2])
                with patch("core.slicer_prusa_job_material.slice_prusa_offline_xl_candidate",
                           return_value=b"audited") as worker:
                    self.assertEqual(slice_prusa_workbench_material(
                        job, [(dict(row), b"STL")
                              for row in job.settings["plate_objects"]]),
                        b"audited")
                received = worker.call_args.kwargs["rows"]
                self.assertIn("modifier_volumes", received[0][0])
                self.assertIn("variable_layer_profile", received[1][0])
        mmu, filaments, raw = fixture("mmu")
        self.resolve(mmu, filaments, raw)
        from core.tests.test_slicer_prusa_3mf import volume
        mmu.settings["plate_objects"][0]["modifier_volumes"] = [
            volume("modifier", {"sparse_infill_density": 80})]
        kind, plan = prepare_prusa_workbench_material(mmu)
        self.assertEqual(kind, "mmu")
        with patch("core.slicer_prusa_job_material.slice_prusa_offline_mmu_candidate",
                   return_value=b"audited-native") as worker:
            self.assertEqual(slice_prusa_workbench_material(
                mmu, [(dict(row), b"STL")
                      for row in mmu.settings["plate_objects"]]),
                             b"audited-native")
        routed = worker.call_args.kwargs["rows"]
        self.assertEqual(routed[0][0]["modifier_volumes"][0]["kind"], "modifier")
        self.assertFalse(routed[1][0].get("variable_layer_profile"))
        mmu.settings["plate_objects"][1]["variable_layer_profile"] = {
            "version": 1, "bands": [
                {"from_mm": 2, "to_mm": 6, "layer_mm": .12}]}
        with self.assertRaisesRegex(SlicerProfileError, "unqualified edits"):
            prepare_prusa_workbench_material(mmu)

    def test_multi_tool_global_overrides_refuse_unqualified_controls(self):
        for value in (
            {"wipe_tower":1},{"machine_start_gcode":"G28"},{"prime_tower_width":40},
            {"brim_width":2},{"skirt_loops":2},
            {"layer_height":"0.2"},{"wall_loops":True},["layer_height"],
        ):
            with self.subTest(value=value):
                job,filaments,raw=fixture()
                self.resolve(job,filaments,raw)
                job.settings["process_overrides"]=value
                if isinstance(value,dict) and set(value)<={"layer_height","wall_loops"}:
                    # Numeric validation occurs at the native preflight,
                    # after exact owner-scoped process profile resolution.
                    continue
                with self.assertRaises(SlicerProfileError):
                    prepare_prusa_workbench_material(job)

    def test_native_five_head_acceptance_qualifies_bounded_object_wall_settings(self):
        for mode in ("mmu", "xl"):
            with self.subTest(mode=mode):
                job, filaments, raw = fixture(mode)
                self.resolve(job, filaments, raw)
                job.settings["plate_objects"][0]["process_overrides"] = {
                    "wall_loops": 1, "sparse_infill_density": 15}
                job.settings["plate_objects"][1]["process_overrides"] = {
                    "wall_loops": 5, "sparse_infill_density": 35}
                kind, plan = prepare_prusa_workbench_material(job)
                self.assertEqual(kind, mode)
                self.assertEqual(plan["tools"], [1, 2])
                with patch("core.slicer_prusa_job_material.slice_prusa_offline_" +
                           ("mmu" if mode=="mmu" else "xl") + "_candidate",
                           return_value=b"audited-G-code") as worker:
                    slice_prusa_workbench_material(job,[
                        (dict(row),b"stl")
                        for row in job.settings["plate_objects"]])
                rows=worker.call_args.kwargs["rows"]
                self.assertEqual([r["process_overrides"]["wall_loops"]
                                  for r,_ in rows],[1,5])
                self.assertTrue(all("material_slot" not in r for r,_ in rows))
                self.assertEqual(worker.call_args.kwargs["tools"],[1,2])

    def test_mmu_xl_and_indx_shell_overrides_remain_object_local(self):
        for mode, count in (("mmu", 2), ("xl", 2), ("xl", 8)):
            with self.subTest(mode=mode, tools=count):
                job, filaments, raw = fixture(mode, count)
                self.resolve(job, filaments, raw)
                left, right = job.settings["plate_objects"]
                left["process_overrides"] = {
                    "top_shell_layers": 0, "bottom_shell_layers": 1}
                right["process_overrides"] = {
                    "top_shell_layers": 8, "bottom_shell_layers": 7}
                kind, prepared = prepare_prusa_workbench_material(job)
                self.assertEqual(kind, "mmu" if mode == "mmu" else
                                 "indx" if count > 5 else "xl")
                self.assertEqual(prepared["tools"], [1, 2])
                route = ("slice_prusa_offline_mmu_candidate" if mode == "mmu"
                         else "slice_prusa_offline_xl_candidate")
                with patch("core.slicer_prusa_job_material." + route,
                           return_value=b"verified") as worker:
                    slice_prusa_workbench_material(job, [
                        (dict(row), b"stl") for row in job.settings["plate_objects"]])
                rows = worker.call_args.kwargs["rows"]
                self.assertEqual(rows[0][0]["process_overrides"]["top_shell_layers"], 0)
                self.assertEqual(rows[1][0]["process_overrides"]["bottom_shell_layers"], 7)

    def test_multi_tool_object_edits_fail_closed_outside_native_qualified_keys(self):
        for overrides in (
            {"travel_speed":120}, {"brim_width":5},
            {"post_process":"G28"}, {"wall_loops":0},
            {"wall_loops":True}, {"wall_loops":"3"},
            {"sparse_infill_density":110}, {"sparse_infill_density":float("nan")},
            ["wall_loops"], False,
        ):
            with self.subTest(overrides=overrides):
                job,filaments,raw=fixture()
                self.resolve(job,filaments,raw)
                job.settings["plate_objects"][1]["process_overrides"]=overrides
                with self.assertRaises(SlicerProfileError):
                    prepare_prusa_workbench_material(job)

    def test_rejects_incomplete_or_ambiguous_bound_materials(self):
        for change in (
            lambda j:j.settings["material_tool_bindings"].pop(),
            lambda j:j.settings["material_tool_bindings"][1].update(tool_index=0),
            lambda j:j.settings["slot_filament_profiles"].pop(),
            lambda j:j.settings["slot_filament_profiles"][1].update(profile_id="999"),
            lambda j:j.settings["plate_objects"][1]["material_slot"].update(slot_id="unknown"),
            lambda j:j.settings.update(material_topology="toolchanger"),
            lambda j:j.settings["plate_objects"][1].update(
                process_overrides={"travel_speed":120}),
            lambda j:j.settings["plate_objects"][1].update(
                colour_paint={"regions":[{"slot":1}]}),
            lambda j:j.settings.update(
                plates=[{"id":"plate-1","objects":[],"volumes":[]}],
                active_plate_id="plate-1"),
        ):
            job,filaments,raw=fixture()
            self.resolve(job,filaments,raw)
            change(job)
            with self.subTest(change=change),self.assertRaises(SlicerProfileError):
                prepare_prusa_workbench_material(job)

    def test_mmu_requires_complete_explicit_purge_not_guesses(self):
        for change in (
            lambda j:j.settings.pop("flush_settings"),
            lambda j:j.settings["flush_settings"]["transitions"].pop(),
            lambda j:j.settings["flush_settings"].update(multiplier=1.5),
            lambda j:j.settings["flush_settings"]["transitions"][0].update(volume_mm3=0),
            lambda j:j.settings.pop("prime_tower"),
        ):
            job,filaments,raw=fixture()
            self.resolve(job,filaments,raw)
            change(job)
            with self.subTest(change=change),self.assertRaises(
                    (SlicerProfileError, ValueError)):
                kind,plan=prepare_prusa_workbench_material(job)
                # The upstream compile validates numeric purge ranges.
                from core.slicer_prusa_purge import compile_prusa_purge_matrix
                compile_prusa_purge_matrix(raw,b"layer_height = 0.2\n",plan["purge_matrix"])

    def test_indx_six_to_eight_tools_and_xl_tower_rejection(self):
        job,filaments,raw=fixture("xl")
        self.resolve(job,filaments,raw)
        job.settings["prime_tower"]={"x":55,"y":150}
        with self.assertRaises(SlicerProfileError):
            prepare_prusa_workbench_material(job)
        for n in (6,7,8):
            with self.subTest(tools=n):
                job,filaments,raw=fixture("xl",n)
                self.resolve(job,filaments,raw)
                kind,plan=prepare_prusa_workbench_material(job)
                self.assertEqual(kind,"indx")
                self.assertEqual(plan["tools"],[1,2])
                self.assertEqual(len(plan["filament_profiles"]),n)
                with patch("core.slicer_prusa_job_material.slice_prusa_offline_xl_candidate",
                           return_value=b"audited-indx-gcode") as run:
                    output=slice_prusa_workbench_material(
                        job,[(dict(row),b"STL") for row in job.settings["plate_objects"]])
                self.assertEqual(output,b"audited-indx-gcode")
                run.assert_called_once()
                self.assertNotIn("purge_matrix",run.call_args.kwargs)

    def test_cross_engine_filament_and_missing_primary_rejected(self):
        job,filaments,raw=fixture()
        self.resolve(job,[filaments[0], profile("filament",2,engine="orcaslicer")],raw)
        with self.assertRaises(SlicerProfileError):
            prepare_prusa_workbench_material(job)
        job,filaments,raw=fixture()
        self.resolve(job,filaments,raw)
        job.filament_profile_id=99
        with self.assertRaises(SlicerProfileError):
            prepare_prusa_workbench_material(job)


class PrusaVirtualToolDraftTests(TestCase):
    def config(self):
        from uuid import UUID
        a,b = ("11111111-1111-4111-8111-111111111111",
               "22222222-2222-4222-8222-222222222222")
        job,filaments,raw = fixture("mmu")
        job.settings.pop("slot_filament_profiles")
        job.settings.pop("material_tool_bindings")
        job.settings.pop("flush_settings")
        filaments[0].pk=UUID(a)
        filaments[1].pk=UUID(b)
        job.filament_profile_id=UUID(a)
        mids=("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
              "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
        for row,mid in zip(job.settings["plate_objects"],mids):
            row.pop("material_slot")
            row["instance_id"]=mid
        job.settings["prusa_native_tools"]={
            "version":1,"mode":"mmu","tool_count":2,
            "filament_profile_ids":[a,b],
            "model_tools":[{"instance_id":mid,"tool":i+1}
                           for i,mid in enumerate(mids)],
            "purge_matrix":[[0,80],[90,0]],
        }
        return job,filaments,raw

    def test_painted_single_model_uses_owned_virtual_mmu_palette(self):
        from scripts.prusa_generate_mmu_paint import fixture as painted_fixture
        job,filaments,raw=self.config()
        source,_mesh,_states,paint=painted_fixture(include_paint=True)
        job.settings["plate_objects"]=job.settings["plate_objects"][:1]
        job.settings["plate_objects"][0]["colour_paint"]=paint
        job.settings["prusa_native_tools"]["model_tools"]=job.settings[
            "prusa_native_tools"]["model_tools"][:1]
        job.settings["prusa_native_tools"]["colour_tools"]=[{"slot":1,"tool":2}]
        PrusaWorkbenchMaterialTests.resolve(self,job,filaments,raw)
        job.settings["process_overrides"] = {"layer_height": .16, "wall_loops": 3}
        mode,plan=prepare_prusa_workbench_material(job)
        self.assertEqual(mode,"colour")
        self.assertEqual(plan["process_overrides"], job.settings["process_overrides"])
        self.assertEqual(plan["tools"],[1])
        self.assertEqual(plan["colour_tool"],1)
        self.assertEqual(plan["colour_slot"],1)
        self.assertEqual(plan["filament_profiles"],filaments)
        with patch("core.slicer_prusa_job_material.slice_prusa_offline_colour_candidate",
                   return_value=b"audited-paint") as worker:
            output=slice_prusa_workbench_material(
                job,[(dict(job.settings["plate_objects"][0]),source)])
        self.assertEqual(output,b"audited-paint")
        self.assertEqual(worker.call_args.kwargs["colour_tool"],1)
        self.assertEqual(worker.call_args.kwargs["process_overrides"], job.settings["process_overrides"])
        self.assertEqual(len(worker.call_args.kwargs["rows"]),1)

    def test_painted_mmu_rejects_unqualified_or_ambiguous_tool_assignments(self):
        from scripts.prusa_generate_mmu_paint import fixture as painted_fixture
        _source,_mesh,_states,paint=painted_fixture(include_paint=True)
        for change in (
            lambda j:j.settings["prusa_native_tools"].update(colour_tools=[]),
            lambda j:j.settings["prusa_native_tools"].update(colour_tools=[{"slot":0,"tool":2}]),
            lambda j:j.settings["prusa_native_tools"].update(colour_tools=[{"slot":1,"tool":1}]),
            lambda j:j.settings["prusa_native_tools"]["model_tools"][0].update(tool=2),
            lambda j:j.settings.update(process_overrides={"post_process":"G28"}),
            lambda j:j.settings["plate_objects"][0].update(support_paint={"regions":[{"slot":0}]}),
        ):
            with self.subTest(change=change):
                job,filaments,raw=self.config()
                job.settings["plate_objects"]=job.settings["plate_objects"][:1]
                job.settings["plate_objects"][0]["colour_paint"]=paint
                job.settings["prusa_native_tools"]["model_tools"]=job.settings[
                    "prusa_native_tools"]["model_tools"][:1]
                job.settings["prusa_native_tools"]["colour_tools"]=[{"slot":1,"tool":2}]
                PrusaWorkbenchMaterialTests.resolve(self,job,filaments,raw)
                change(job)
                with self.assertRaises((SlicerProfileError,ValueError)):
                    prepare_prusa_workbench_material(job)

    def test_saved_virtual_mmu_uses_only_explicit_native_tools(self):
        job,filaments,raw=self.config()
        PrusaWorkbenchMaterialTests.resolve(self,job,filaments,raw)
        kind,result=prepare_prusa_workbench_material(job)
        self.assertEqual(kind,"mmu")
        self.assertEqual(result["tools"],[1,2])
        self.assertEqual(result["purge_matrix"],[[0.0,80.0],[90.0,0.0]])
        self.assertEqual(result["filament_profiles"],filaments)

    def test_incomplete_virtual_draft_can_be_saved_not_executed(self):
        from core.slicer_prusa_tool_configuration import validate_prusa_native_tools
        job,filaments,raw=self.config()
        PrusaWorkbenchMaterialTests.resolve(self,job,filaments,raw)
        job.settings["prusa_native_tools"]["filament_profile_ids"][1]=""
        self.assertEqual(validate_prusa_native_tools(
            job.settings["prusa_native_tools"])["filament_profile_ids"][1],"")
        with self.assertRaises(SlicerProfileError):
            prepare_prusa_workbench_material(job)

    def test_mmu_purge_and_native_topology_must_match(self):
        job,filaments,raw=self.config()
        PrusaWorkbenchMaterialTests.resolve(self,job,filaments,raw)
        job.settings["prusa_native_tools"]["purge_matrix"][1][0]=None
        with self.assertRaises(SlicerProfileError):
            prepare_prusa_workbench_material(job)
        job.settings["prusa_native_tools"]["purge_matrix"][1][0]=80
        job.settings["prusa_native_tools"]["mode"]="xl"
        job.settings["prusa_native_tools"]["purge_matrix"]=None
        with self.assertRaises(SlicerProfileError):
            prepare_prusa_workbench_material(job)

    def test_rejects_forged_model_identity_and_foreign_filaments(self):
        job,filaments,raw=self.config()
        PrusaWorkbenchMaterialTests.resolve(self,job,filaments,raw)
        job.settings["prusa_native_tools"]["model_tools"][1]["instance_id"]=(
            "cccccccc-cccc-4ccc-8ccc-cccccccccccc")
        with self.assertRaises(SlicerProfileError):
            prepare_prusa_workbench_material(job)
        job,filaments,raw=self.config()
        filaments[1].owner_id=91
        PrusaWorkbenchMaterialTests.resolve(self,job,filaments,raw)
        with self.assertRaises(SlicerProfileError):
            prepare_prusa_workbench_material(job)

    def test_virtual_xl_profile_rejects_forged_indx_mode(self):
        job, filaments, _ = self.config()
        job.settings["prusa_native_tools"]["mode"] = "indx"
        job.settings["prusa_native_tools"]["purge_matrix"] = None
        job.settings.pop("prime_tower")
        PrusaWorkbenchMaterialTests.resolve(self, job, filaments, ini("0.4,0.4", "0"))
        with self.assertRaisesRegex(SlicerProfileError, "tool"):
            prepare_prusa_workbench_material(job)

    def test_virtual_xl_rejects_mmu_purge_and_requires_xl_native_profile(self):
        job,filaments,raw=self.config()
        job.settings["prusa_native_tools"]["mode"]="xl"
        job.settings["prusa_native_tools"]["purge_matrix"]=None
        job.settings["prime_tower"]=None
        PrusaWorkbenchMaterialTests.resolve(self,job,filaments,raw)
        with self.assertRaises(SlicerProfileError):
            prepare_prusa_workbench_material(job)
        job,filaments,_=self.config()
        job.settings["prusa_native_tools"]["mode"]="xl"
        job.settings["prusa_native_tools"]["purge_matrix"]=None
        job.settings.pop("prime_tower")
        PrusaWorkbenchMaterialTests.resolve(self,job,filaments,ini("0.4,0.4","0"))
        kind,result=prepare_prusa_workbench_material(job)
        self.assertEqual(kind,"xl")
        self.assertNotIn("purge_matrix",result)

    def test_indx_eight_head_painted_workbench_keeps_all_native_filaments(self):
        from uuid import UUID
        from scripts.prusa_generate_mmu_paint import fixture as painted_fixture
        job,filaments,_ = self.config()
        source,_mesh,_states,paint=painted_fixture(include_paint=True)
        for digit in range(3,9):
            ident=f"{digit}"*8+"-"+f"{digit}"*4+"-4"+f"{digit}"*3+"-8"+f"{digit}"*3+"-"+f"{digit}"*12
            filaments.append(profile("filament",UUID(ident)))
        job.settings["plate_objects"]=job.settings["plate_objects"][:1]
        job.settings["plate_objects"][0]["colour_paint"]=paint
        config=job.settings["prusa_native_tools"]
        config.update(mode="indx",tool_count=8,purge_matrix=None,
                      filament_profile_ids=[str(p.pk) for p in filaments],
                      model_tools=config["model_tools"][:1],
                      colour_tools=[{"slot":1,"tool":2}])
        job.settings.pop("prime_tower")
        PrusaWorkbenchMaterialTests.resolve(
            self,job,filaments,ini(",".join(["0.4"]*8),"0"))
        mode,plan=prepare_prusa_workbench_material(job)
        self.assertEqual(mode,"xl_colour")
        self.assertEqual(len(plan["filament_profiles"]),8)
        self.assertEqual(plan["colour_tool_indices"],{1:1})
        with patch("core.slicer_prusa_job_material.slice_prusa_offline_xl_colour_candidate",
                   return_value=b"audited-indx-paint") as worker:
            result=slice_prusa_workbench_material(
                job,[(dict(job.settings["plate_objects"][0]),source)])
        self.assertEqual(result,b"audited-indx-paint")
        self.assertEqual(worker.call_args.kwargs["filament_profiles"],filaments)
        self.assertNotIn("tower_xy",worker.call_args.kwargs)

    def test_painted_xl_two_wall_workbench_dispatch(self):
        from scripts.prusa_generate_mmu_paint import fixture as painted_fixture
        job, filaments, _ = self.config()
        _source, _mesh, _states, paint = painted_fixture(include_paint=True)
        # Workbench validates palette identities; native 3MF preflight
        # separately verifies exact fingerprinted wall geometry.
        dual = {**paint, "regions":[
            *paint["regions"], {"slot":2,"patches":[{"face":0,"polygon":[]}]}]}
        job.settings["plate_objects"] = job.settings["plate_objects"][:1]
        job.settings["plate_objects"][0]["colour_paint"] = dual
        config = job.settings["prusa_native_tools"]
        from uuid import UUID
        third_id = "33333333-3333-4333-8333-333333333333"
        filaments.append(profile("filament", UUID(third_id)))
        config.update(mode="xl", tool_count=3, purge_matrix=None,
                      filament_profile_ids=[*config["filament_profile_ids"], third_id],
                      model_tools=config["model_tools"][:1],
                      colour_tools=[{"slot":1,"tool":2},{"slot":2,"tool":3}])
        job.settings.pop("prime_tower")
        PrusaWorkbenchMaterialTests.resolve(
            self, job, filaments, ini("0.4,0.4,0.4", "0"))
        with patch("core.slicer_prusa_job_material.slice_prusa_offline_xl_colour_candidate",
                   return_value=b"audited-dual-xl") as worker:
            result=slice_prusa_workbench_material(
                job,[(dict(job.settings["plate_objects"][0]),b"source")])
        self.assertEqual(result,b"audited-dual-xl")
        self.assertEqual(worker.call_args.kwargs["colour_tool_indices"],{1:1,2:2})
        self.assertNotIn("tower_xy",worker.call_args.kwargs)

    def test_painted_xl_workbench_dispatch_uses_only_xl_candidate_arguments(self):
        from scripts.prusa_generate_mmu_paint import fixture as painted_fixture
        from inspect import signature
        from core.slicer_prusa_material_preflight import prepare_prusa_offline_xl_colour_candidate
        job, filaments, _ = self.config()
        source, _mesh, _states, paint = painted_fixture(include_paint=True)
        job.settings["plate_objects"] = job.settings["plate_objects"][:1]
        job.settings["plate_objects"][0]["colour_paint"] = paint
        config = job.settings["prusa_native_tools"]
        config.update(mode="xl", purge_matrix=None,
                      model_tools=config["model_tools"][:1],
                      colour_tools=[{"slot": 1, "tool": 2}])
        job.settings.pop("prime_tower")
        PrusaWorkbenchMaterialTests.resolve(self, job, filaments, ini("0.4,0.4", "0"))
        job.settings["process_overrides"] = {"layer_height": .16, "wall_loops": 3}
        mode, plan = prepare_prusa_workbench_material(job)
        self.assertEqual(mode, "xl_colour")
        self.assertEqual(plan["process_overrides"], job.settings["process_overrides"])
        self.assertEqual(plan["colour_tool_indices"], {1: 1})
        rows = [(dict(job.settings["plate_objects"][0]), source)]
        with patch("core.slicer_prusa_job_material.slice_prusa_offline_xl_colour_candidate",
                   return_value=b"audited-xl-paint") as worker:
            self.assertEqual(slice_prusa_workbench_material(job, rows), b"audited-xl-paint")
        # Bind the dispatched keywords against the real candidate signature,
        # not merely the permissive mock accepting arbitrary keyword arguments.
        signature(prepare_prusa_offline_xl_colour_candidate).bind(**worker.call_args.kwargs)
        self.assertNotIn("colour_tool", worker.call_args.kwargs)
        self.assertNotIn("colour_slot", worker.call_args.kwargs)
        self.assertNotIn("tower_xy", worker.call_args.kwargs)
