"""Private slicer masks are lossless, mesh-bound, owner-scoped and immutable."""
import json
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from django.test import TestCase

from core.models import FileAsset
from core.slicer_paint_assets import (
    expand_painted_item, expand_painted_settings, load_paint,
    settings_use_paint_field, store_paint,
)


class PrivateSlicerPaintAssetTests(TestCase):
    url="/api/printing/slicer/paint-assets/"

    def setUp(self):
        User=get_user_model()
        self.owner=User.objects.create_user(username="private-paint-owner")
        self.stranger=User.objects.create_user(username="private-paint-stranger")
        self.owner.user_permissions.add(Permission.objects.get(codename="add_fileasset"))
        self.client.force_login(self.owner)
        self.mesh=FileAsset.objects.create(
            owner=self.owner, category="mesh", name="benchy.stl",
            file=ContentFile(b"solid benchy\nendsolid benchy\n",name="benchy.stl"),
            metadata={"extension": ".stl", "slicer_temporary": True},
        )
        self.other_mesh=FileAsset.objects.create(
            owner=self.owner, category="mesh", name="cube.stl",
            file=ContentFile(b"solid cube\nendsolid cube\n",name="cube.stl"),
            metadata={"extension": ".stl"},
        )
        # Multiple independent semantic features in one immutable mask.
        self.paint={"variable_layer_profile":{
            "version":1,"bands":[{"from_mm":5,"to_mm":15,"layer_mm":.12}],
        }}

    @patch("core.slicer_api.ensure_storage_capacity")
    def test_upload_restore_reuse_and_mesh_binding(self, quota):
        data={"mesh_asset_id":str(self.mesh.id),"paint":self.paint}
        def upload():
            return self.client.post(self.url,data=json.dumps(data),
                                    content_type="application/json")
        first=upload()
        self.assertEqual(first.status_code,201,first.content)
        self.assertEqual(upload().json()["asset_id"],first.json()["asset_id"])
        ref=first.json()["asset_id"]
        self.assertEqual(load_paint(self.owner, ref,self.mesh.pk),self.paint)
        self.assertEqual(self.client.get(
            self.url+ref+"/",{"mesh_asset_id":str(self.mesh.pk)}).json()["paint"],self.paint)
        self.assertEqual(self.client.get(
            self.url+ref+"/",{"mesh_asset_id":str(self.other_mesh.pk)}).status_code,404)
        compact={"instance_id":str(uuid.uuid4()),"asset_id":str(self.mesh.pk),
                 "paint_asset_id":ref}
        expanded=expand_painted_item(self.owner, compact)
        self.assertEqual(expanded["variable_layer_profile"],self.paint["variable_layer_profile"])
        self.assertEqual(expand_painted_settings(
            self.owner, {"plate_objects":[compact]})["plate_objects"][0]["variable_layer_profile"],
            self.paint["variable_layer_profile"])
        self.assertTrue(settings_use_paint_field(
            self.owner,{"plate_objects":[compact]},"variable_layer_profile"))
        self.assertFalse(settings_use_paint_field(
            self.owner,{"plate_objects":[compact]},"support_paint"))
        self.assertEqual(FileAsset.objects.filter(metadata__slicer_paint=True).count(),1)

    @patch("core.slicer_api.ensure_storage_capacity")
    def test_draft_settings_store_only_asset_reference_not_mask(self, quota):
        from core.slicer_api import _draft_plate_settings
        ref=store_paint(self.owner,self.mesh.pk,self.paint)
        item={"instance_id":str(uuid.uuid4()),"asset_id":str(self.mesh.pk),
              "x_mm":0,"y_mm":0,"rotation_deg":0,"scale_percent":100,
              "color":"#ABCDEF","paint_asset_id":str(ref.pk)}
        saved=_draft_plate_settings(self.owner,self.mesh,{
            "plate_label":"Test plate","plate_objects":[item]})
        self.assertEqual(saved["plate_objects"][0]["paint_asset_id"],str(ref.pk))
        self.assertNotIn("variable_layer_profile",saved["plate_objects"][0])
        self.assertLess(len(json.dumps(saved)),2048)
        with self.assertRaisesRegex(ValueError,"cannot also contain inline"):
            _draft_plate_settings(self.owner,self.mesh,{
                "plate_objects":[{**item,"variable_layer_profile":
                                 self.paint["variable_layer_profile"]}]})

    @patch("core.slicer_api.ensure_storage_capacity")
    def test_versions_and_cross_owner_references(self, quota):
        payload={"mesh_asset_id":str(self.mesh.pk),"paint":self.paint}
        response=self.client.post(self.url,json.dumps(payload),
                                  content_type="application/json")
        self.assertEqual(response.status_code,201)
        ref=response.json()["asset_id"]
        payload["paint"]["variable_layer_profile"]["bands"][0]["layer_mm"]=.16
        revision=self.client.post(self.url,json.dumps(payload),
                                  content_type="application/json")
        self.assertEqual(revision.status_code,201)
        self.assertNotEqual(revision.json()["asset_id"],ref)
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(
            self.url+ref+"/",{"mesh_asset_id":str(self.mesh.pk)}).status_code,404)
        self.assertEqual(self.client.post(
            self.url,json.dumps(payload),
            content_type="application/json").status_code,403)
        self.client.force_login(self.owner)
        with self.assertRaisesRegex(ValueError,"cannot also contain inline"):
            expand_painted_item(self.owner,{
                "asset_id":str(self.mesh.pk),"paint_asset_id":ref,
                "variable_layer_profile":self.paint["variable_layer_profile"]})

    @patch("core.slicer_api.ensure_storage_capacity")
    def test_no_arbitrary_asset_reference(self, quota):
        unowned={"mesh_asset_id":str(uuid.uuid4()),"paint":self.paint}
        response=self.client.post(self.url,json.dumps(unowned),
                                  content_type="application/json")
        self.assertEqual(response.status_code,400)
        malformed={"mesh_asset_id":str(self.mesh.pk),"paint":{"javascript":"evil"}}
        response=self.client.post(self.url,json.dumps(malformed),
                                  content_type="application/json")
        self.assertEqual(response.status_code,400)
