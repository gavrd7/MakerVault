"""Offline Prusa MMU worker request must re-verify exact resolved native data."""
import base64
import uuid
from unittest import TestCase
from unittest.mock import patch

from core.tests.test_slicer_prusa_material_preflight import PrusaOfflineMmuPreflightTests
from slicer_worker.service import _decode_payload
from slicer_worker.runner import WorkerError


def encoded(raw):
    return base64.b64encode(raw).decode("ascii")


def request():
    values, assets = PrusaOfflineMmuPreflightTests().parts()
    from core.slicer_prusa_material_preflight import prepare_prusa_offline_mmu_candidate
    with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
               side_effect=assets):
        compiled = prepare_prusa_offline_mmu_candidate(**values)
    return {
        "job_id":str(uuid.uuid4()),"engine":"prusaslicer","engine_version":"2.9.7",
        "model_format":"3mf","model":encoded(compiled["model"]),
        "printer_profile":encoded(compiled["printer"]),
        "filament_profile":encoded(compiled["filament"]),
        "process_profile":encoded(compiled["process"]),
        "prusa_offline_mmu":{"tools":[1,2],"tower":[55,150,0,250,210]},
    }



def xl_request():
    values,assets=PrusaOfflineMmuPreflightTests().parts()
    from core.slicer_prusa_material_preflight import prepare_prusa_offline_xl_candidate
    from core.tests.test_slicer_prusa_machine_topology import ini
    assets[0]=ini("0.4,0.4,0.4,0.4,0.4","0")
    settings={k:values[k] for k in (
        "owner_id","printer_profile","process_profile","filament_profiles",
        "rows","tools","bed_width","bed_depth")}
    with patch("core.slicer_prusa_material_preflight.resolved_prusa_profile",
               side_effect=assets):
        candidate=prepare_prusa_offline_xl_candidate(**settings)
    return {
        "job_id":str(uuid.uuid4()),"engine":"prusaslicer",
        "engine_version":"2.9.7","model_format":"3mf",
        "model":encoded(candidate["model"]),
        "printer_profile":encoded(candidate["printer"]),
        "filament_profile":encoded(candidate["filament"]),
        "process_profile":encoded(candidate["process"]),
        "prusa_offline_xl":{"tools":[1,2]},
    }


class PrusaOfflineWorkerProtocolTests(TestCase):
    def test_xl_independent_heads_admit_no_mmu_tower(self):
        result=_decode_payload(xl_request())
        self.assertEqual(result["prusa_offline_xl"]["tools"],[1,2])
        self.assertNotIn("prusa_offline_mmu",result)

    def test_xl_rejects_forged_tower_and_incompatible_profiles(self):
        original=xl_request()
        for changes in (
            {"engine":"orcaslicer"},
            {"engine_version":"2.9.6"},
            {"prusa_offline_xl":{"tools":[1,2],"tower":[55,150,0,250,210]}},
            {"prusa_offline_xl":{"tools":[1,1]}},
            {"prusa_offline_xl":{"tools":[1,6]}},
            {"prusa_offline_mmu":{"tools":[1,2],"tower":[55,150,0,250,210]}},
        ):
            with self.subTest(changes=changes),self.assertRaises(WorkerError):
                _decode_payload({**original,**changes})
        altered=dict(original)
        altered["process_profile"]=encoded(
            base64.b64decode(original["process_profile"]).replace(
                b"wipe_tower = 0",b"wipe_tower = 1"))
        with self.assertRaises(WorkerError):
            _decode_payload(altered)


    def test_exact_mmu_preflight_bytes_are_accepted(self):
        payload=request()
        result=_decode_payload(payload)
        self.assertEqual(result["prusa_offline_mmu"]["tools"],[1,2])
        self.assertEqual(result["prusa_offline_mmu"]["tower"],[55,150,0,250,210])

    def test_missing_flag_fails_as_untrusted_material_archive(self):
        payload=request()
        payload.pop("prusa_offline_mmu")
        with self.assertRaises(WorkerError):
            _decode_payload(payload)

    def test_wrong_engine_version_or_conflicting_options_are_rejected(self):
        payload=request()
        for changes in (
            {"engine":"orcaslicer"},{"engine_version":"2.9.6"},
            {"model_format":"stl"},{"native_modifier_project":True},
            {"prusa_placed_stl":True},{"filament_profiles":[payload["filament_profile"]]*2},
            {"prusa_offline_mmu":{"tools":[1,2],"tower":[55,150,0,250,210],"cmd":"rm"}},
            {"prusa_offline_mmu":{"tools":[1,True],"tower":[55,150,0,250,210]}},
            {"prusa_offline_mmu":{"tools":[1,3],"tower":[55,150,0,250,210]}},
            {"prusa_offline_mmu":{"tools":[1,2],"tower":[249,150,0,250,210]}},
        ):
            with self.subTest(changes=changes), self.assertRaises(WorkerError):
                _decode_payload({**payload,**changes})

    def test_material_vector_and_purge_modifications_fail_closed(self):
        payload=request()
        for key,old,new in (
            ("filament_profile",b"temperature = 205,220,210,205,205",
             b"temperature = 205,220"),
            ("process_profile",b"wipe_into_objects = 0",b"wipe_into_objects = 1"),
            ("process_profile",b"wiping_volumes_matrix =",b"wiping_volumes_matrix = -5,"),
        ):
            candidate=dict(payload)
            raw=base64.b64decode(candidate[key])
            self.assertIn(old,raw)
            candidate[key]=encoded(raw.replace(old,new))
            with self.subTest(key=key), self.assertRaises(WorkerError):
                _decode_payload(candidate)
