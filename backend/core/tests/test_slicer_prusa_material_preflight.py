"""Complete Prusa MMU candidate preflight stays private and non-dispatchable."""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import io
import zipfile

from core.slicer_prusa_material_preflight import prepare_prusa_offline_mmu_candidate
from core.slicer_profiles import SlicerProfileError
from core.tests.test_slicer_prusa_machine_topology import ini
from core.tests.test_slicer_prusa_plate import cube, item
from slicer_worker.prusa_3mf_validation import validate_prusa_native_3mf
from slicer_worker.runner import WorkerError


def profile(kind, owner_id=42, engine="prusaslicer"):
    return SimpleNamespace(kind=kind, owner_id=owner_id, engine=engine)


class PrusaOfflineMmuPreflightTests(TestCase):
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
