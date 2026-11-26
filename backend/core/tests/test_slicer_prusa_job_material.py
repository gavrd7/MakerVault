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

    def test_rejects_incomplete_or_ambiguous_bound_materials(self):
        for change in (
            lambda j:j.settings["material_tool_bindings"].pop(),
            lambda j:j.settings["material_tool_bindings"][1].update(tool_index=0),
            lambda j:j.settings["slot_filament_profiles"].pop(),
            lambda j:j.settings["slot_filament_profiles"][1].update(profile_id="999"),
            lambda j:j.settings["plate_objects"][1]["material_slot"].update(slot_id="unknown"),
            lambda j:j.settings.update(material_topology="toolchanger"),
            lambda j:j.settings["plate_objects"][1].update(
                process_overrides={"sparse_infill_density":80}),
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

    def test_xl_rejects_tower_and_unsupported_indx_mechanism(self):
        job,filaments,raw=fixture("xl")
        self.resolve(job,filaments,raw)
        job.settings["prime_tower"]={"x":55,"y":150}
        with self.assertRaises(SlicerProfileError):
            prepare_prusa_workbench_material(job)
        job,filaments,raw=fixture("xl",6)
        self.resolve(job,filaments,raw)
        with self.assertRaises(SlicerProfileError):
            prepare_prusa_workbench_material(job)

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
