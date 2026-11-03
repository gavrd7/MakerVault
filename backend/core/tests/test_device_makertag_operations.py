"""MakerTag clean/remove lifecycle regression checks."""
import json
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
        self.assertEqual(self.device_step(pk,"remove",{"uid":"04AABBCCDDEEFF"}).status_code,200)
        self.assertFalse(MakerTag.objects.filter(pk=self.tag.pk).exists())
