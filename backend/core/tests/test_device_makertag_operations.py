"""MakerTag clean/remove lifecycle regression checks."""
import json
from datetime import timedelta
from django.utils import timezone
from core.device_tag_operations_model import DeviceMakerTagOperation as Operation
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from core.device_api_keys import generate_token
from core.models import ConnectedDevice, InventoryItem, MakerTag, UserApiKey

@override_settings(DEBUG=True)
class MakerTagOperationTests(TestCase):
    def setUp(self):
        User=get_user_model()
        self.owner=User.objects.create_user(username="clean-test",password="pass")
        for code in ("view_makertag","change_makertag","delete_makertag"):
            self.owner.user_permissions.add(Permission.objects.get(content_type__app_label="core",codename=code))
        self.item=InventoryItem.objects.create(owner=self.owner,inventory_id="OTH-9921",
            item_type="other",custom_name="Clean test",quantity=1)
        self.tag=MakerTag.objects.create(owner=self.owner,kind="nfc",code="04AABBCCDDEEFF",
            target_type="inventory",target_id=self.item.pk)
        token=generate_token()
        key=UserApiKey.objects.create(owner=self.owner,name="Clean",identifier=token.identifier,
            secret_digest=token.digest,scopes=["tags:write","tags:read"])
        self.token=token.plaintext
        self.device=ConnectedDevice.objects.create(owner=self.owner,device_uid="clean-terminal",
            name="Clean",device_type="rfid_terminal",api_key=key,capabilities=["ntag215_ndef_write"])
        self.client.force_login(self.owner)

    def send(self,url,payload,device=False):
        headers={"HTTP_AUTHORIZATION":"Bearer "+self.token} if device else {}
        return self.client.post(url,json.dumps(payload),content_type="application/json",**headers)

    def begin(self,action,clean):
        return self.send("/api/device/makertag-operation/",{"tag_id":str(self.tag.pk),
            "device_id":str(self.device.pk),"action":action,"also_clean":clean})

    def device_step(self,pk,step,payload):
        return self.send(f"/api/device/v1/makertag-operation/{pk}/{step}/",payload,True)

    def test_clean_only_retains_registration(self):
        started=self.begin("clean",True)
        self.assertEqual(started.status_code,201,started.content)
        pk=started.json()["operation"]["id"]
        self.assertEqual(self.begin("clean",True).status_code,409)
        self.assertEqual(self.device_step(pk,"remove",{"uid":"04AABBCCDDEEFF"}).status_code,409)
        self.assertEqual(self.device_step(pk,"cleaned",{"uid":"04AABBCCDDEEFF","verified_empty":False}).status_code,409)
        result=self.device_step(pk,"cleaned",{"uid":"04AABBCCDDEEFF","verified_empty":True})
        self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(result.json()["operation"]["state"],"completed")
        self.assertTrue(MakerTag.objects.filter(pk=self.tag.pk).exists())

    def test_remove_only_and_clean_first(self):
        started=self.begin("remove",False)
        self.assertEqual(started.status_code,201,started.content)
        pk=started.json()["operation"]["id"]
        self.assertEqual(self.device_step(pk,"remove",{"uid":"04AABBCCDDEEFF"}).status_code,200)
        self.assertTrue(InventoryItem.objects.filter(pk=self.item.pk).exists())
        self.assertFalse(MakerTag.objects.filter(pk=self.tag.pk).exists())

    def test_combined_requires_verified_clean(self):
        started=self.begin("remove",True)
        self.assertEqual(started.status_code,201,started.content)
        pk=started.json()["operation"]["id"]
        self.assertEqual(self.device_step(pk,"remove",{"uid":"04AABBCCDDEEFF"}).status_code,409)
        result=self.device_step(pk,"cleaned",{"uid":"04AABBCCDDEEFF","verified_empty":True})
        self.assertEqual(result.json()["operation"]["state"],"cleaned")
        self.assertTrue(MakerTag.objects.filter(pk=self.tag.pk).exists())
        # After a terminal reboot, its pending endpoint must re-advertise
        # the durable cleaned operation instead of scheduling a second wipe.
        recovery=self.client.get("/api/device/v1/makertag-operation/pending/",
            HTTP_AUTHORIZATION="Bearer "+self.token)
        self.assertEqual(recovery.json()["operation"]["id"],pk)
        self.assertEqual(recovery.json()["operation"]["state"],"cleaned")
        self.assertEqual(self.device_step(pk,"remove",{"uid":"04AABBCCDDEEFF"}).status_code,200)
        self.assertFalse(MakerTag.objects.filter(pk=self.tag.pk).exists())

    def test_terminal_issued_request_and_same_uid(self):
        response=self.send("/api/device/v1/makertag-operation/begin/",
            {"uid":"04AABBCCDDEEFF","action":"clean","also_clean":True},True)
        self.assertEqual(response.status_code,201,response.content)
        op=response.json()["operation"]["id"]
        self.assertEqual(self.device_step(op,"cleaned",
            {"uid":"04AABBCCDDEE00","verified_empty":True}).status_code,409)
        self.assertEqual(self.device_step(op,"cleaned",
            {"uid":"04AABBCCDDEEFF","verified_empty":True}).status_code,200)

    def test_cancel_expiry_and_changed_identity(self):
        op=self.begin("clean",True).json()["operation"]["id"]
        self.assertEqual(self.client.post(
            f"/api/device/makertag-operation/{op}/cancel/").status_code,200)
        self.assertEqual(self.device_step(op,"cleaned",
            {"uid":"04AABBCCDDEEFF","verified_empty":True}).status_code,410)
        op=self.begin("clean",True).json()["operation"]["id"]
        Operation.objects.filter(pk=op).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.device_step(op,"cleaned",
            {"uid":"04AABBCCDDEEFF","verified_empty":True}).status_code,410)
        op=self.begin("clean",True).json()["operation"]["id"]
        self.tag.code="04AABBCCDDEEAA";self.tag.save(update_fields=["code"])
        state=self.client.get(f"/api/device/v1/makertag-operation/{op}/status/",
            HTTP_AUTHORIZATION="Bearer "+self.token)
        self.assertEqual(state.json()["operation"]["state"],"invalid")
        self.assertEqual(self.device_step(op,"cleaned",
            {"uid":"04AABBCCDDEEFF","verified_empty":True}).status_code,409)

    def test_owner_isolation_and_missing_capability(self):
        self.device.capabilities=[]
        self.device.save(update_fields=["capabilities"])
        self.assertEqual(self.begin("clean",True).status_code,403)
        self.device.capabilities=["ntag215_ndef_write"]
        self.device.save(update_fields=["capabilities"])
        op=self.begin("clean",True).json()["operation"]["id"]
        outsider=get_user_model().objects.create_user(username="other-clean",password="test")
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(
            f"/api/device/makertag-operation/{op}/").status_code,404)
        self.assertEqual(self.client.post(
            f"/api/device/makertag-operation/{op}/cancel/").status_code,404)
        self.client.force_login(self.owner)

    def test_cleaned_state_survives_failed_server_removal(self):
        op=self.begin("remove",True).json()["operation"]["id"]
        self.assertEqual(self.device_step(op,"cleaned",
            {"uid":"04AABBCCDDEEFF","verified_empty":True}).status_code,200)
        perm=Permission.objects.get(content_type__app_label="core",codename="delete_makertag")
        self.owner.user_permissions.remove(perm)
        self.assertEqual(self.device_step(op,"remove",{"uid":"04AABBCCDDEEFF"}).status_code,403)
        self.assertTrue(MakerTag.objects.filter(pk=self.tag.pk).exists())
        self.owner.user_permissions.add(perm)
        self.assertEqual(self.device_step(op,"remove",{"uid":"04AABBCCDDEEFF"}).status_code,200)
