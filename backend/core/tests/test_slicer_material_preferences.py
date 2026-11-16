"""Native slot profile preferences survive drafts, reloads, slot moves and changes."""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import (
    FileAsset, Printer, PrinterFilamentSlot, SlicerProfile,
    SlicerMaterialProfilePreference,
)
from core.slicer_material_preferences import material_identity


class SlicerMaterialPreferenceTests(TestCase):
    url = "/api/printing/slicer/material-profile-preferences/"

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="material-owner")
        self.other = User.objects.create_user(username="material-other")
        self.client.force_login(self.user)
        self.printer = Printer.objects.create(owner=self.user, name="K2", model="K2 Combo")
        self.other_printer = Printer.objects.create(owner=self.other, name="Other K2", model="K2")
        self.asset = FileAsset.objects.create(
            owner=self.user, name="CR-PLA.json", category="other",
            file="files/native-cr-pla.json",
        )
        self.pla = SlicerProfile.objects.create(
            owner=self.user, engine="orcaslicer", engine_version="2.5.0",
            kind="filament", name="CR-PLA @K2", file_asset=self.asset,
            content_sha256="a"*64,
        )
        self.abs = SlicerProfile.objects.create(
            owner=self.user, engine="orcaslicer", engine_version="2.5.0",
            kind="filament", name="CR-ABS @K2", file_asset=self.asset,
            content_sha256="b"*64,
        )
        self.pla_slot = PrinterFilamentSlot.objects.create(
            printer=self.printer, slot_index=0, material="PLA",
            color_hex="#6699cc",
            metadata={"vendor":"Creality","product_name":"PLA Basic"},
        )

    def params(self):
        return {"printer_id":str(self.printer.pk), "engine":"orcaslicer", "version":"2.5.0"}

    def post(self, slot=None, profile=None, **extra):
        payload={**self.params(), "slot_id": str((slot or self.pla_slot).pk),
                 "profile_id": str(profile.pk) if profile is not None else None,
                 **extra}
        return self.client.post(self.url, data=json.dumps(payload),
                                content_type="application/json")

    def test_remembers_per_material_not_by_bay_and_can_clear(self):
        self.assertEqual(self.client.get(self.url,self.params()).json()["assignments"], [])
        result=self.post(profile=self.pla)
        self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(result.json()["profile_id"],str(self.pla.pk))
        recovered=self.client.get(self.url,self.params()).json()["assignments"]
        self.assertEqual(len(recovered),1)
        self.assertEqual(recovered[0]["profile"]["name"],self.pla.name)
        # Another feeder with identical product/colour picks up the same
        # native profile; a different product in the original bay does not.
        second=PrinterFilamentSlot.objects.create(
            printer=self.printer, slot_index=1, material="PLA",
            color_hex="#6699cc",
            metadata={"vendor":"Creality","product_name":"PLA Basic"},
        )
        self.assertEqual(len(self.client.get(self.url,self.params()).json()["assignments"]),2)
        self.pla_slot.metadata={"vendor":"Creality","product_name":"PLA Silk"}
        self.pla_slot.save(update_fields=["metadata"])
        restored=self.client.get(self.url,self.params()).json()["assignments"]
        self.assertEqual([r["slot_id"] for r in restored],[str(second.pk)])
        # Bring the original product back: its selected profile remains.
        self.pla_slot.metadata={"vendor":"Creality","product_name":"PLA Basic"}
        self.pla_slot.save(update_fields=["metadata"])
        self.assertEqual(len(self.client.get(self.url,self.params()).json()["assignments"]),2)
        self.assertEqual(self.post(profile=None).status_code,200)
        self.assertEqual(self.client.get(self.url,self.params()).json()["assignments"],[])
        self.assertFalse(SlicerMaterialProfilePreference.objects.exists())

    def test_engine_version_and_printer_ownership_are_isolated(self):
        self.assertEqual(self.post(profile=self.pla).status_code,200)
        foreign={**self.params(),"printer_id":str(self.other_printer.pk)}
        self.assertEqual(self.client.get(self.url,foreign).status_code,404)
        self.assertEqual(self.post(profile=self.pla,printer_id=str(self.other_printer.pk)).status_code,404)
        self.assertEqual(self.post(profile=self.pla,version="2.4.2").status_code,404)
        self.assertEqual(self.client.get(self.url,{**self.params(),"version":"2.4.2"}).json()["assignments"],[])
        self.assertEqual(self.client.get(self.url,{**self.params(),"engine":"cura"}).json()["assignments"],[])
        self.assertEqual(self.post(profile=self.abs).status_code,200)
        self.assertEqual(SlicerMaterialProfilePreference.objects.count(),1)
        self.assertEqual(self.client.get(self.url,self.params()).json()["assignments"][0]["profile_id"],
                         str(self.abs.pk))

    def test_sparse_unidentified_slots_are_not_automatically_matched(self):
        unidentified=PrinterFilamentSlot.objects.create(
            printer=self.printer,slot_index=2,is_loaded=True)
        self.assertIsNone(material_identity(unidentified))
        self.assertEqual(self.post(slot=unidentified,profile=self.pla).status_code,400)
        self.assertEqual(self.post(profile=self.pla,slot_id="not-a-uuid").status_code,400)

    def test_anonymous_requests_do_not_read_or_change_preferences(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url,self.params()).status_code,302)
        self.assertEqual(self.post(profile=self.pla).status_code,302)
