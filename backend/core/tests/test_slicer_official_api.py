"""Official preset browser imports remain owner-scoped and unverified."""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase

from core.models import FileAsset, SlicerProfile


class OfficialProfileApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="official-owner", password="unused")
        self.other = get_user_model().objects.create_user(username="official-other", password="unused")
        self.user.user_permissions.add(Permission.objects.get(codename="add_fileasset"))
        self.url = "/api/printing/slicer/official-profiles/"
        self.payload = {
            "kind": "printer", "vendor": "Creality",
            "name": "Creality K2 0.4 nozzle",
            "sub_path": "machine/Creality K2 0.4 nozzle.json",
        }
        self.native = json.dumps({
            "type": "machine", "name": self.payload["name"],
            "inherits": "fdm_creality_common",
            "printable_area": ["0x0", "260x0", "260x260", "0x260"],
        }).encode()

    def post(self, payload=None):
        return self.client.post(
            self.url, data=json.dumps(payload or self.payload),
            content_type="application/json",
        )

    def test_search_is_authenticated_and_has_pinned_source(self):
        self.assertEqual(self.client.get(self.url, {"q": "K2"}).status_code, 302)
        self.client.force_login(self.user)
        with patch("core.slicer_api.search_official_profiles", return_value={
            "engine": "orcaslicer", "engine_version": "2.4.2",
            "profiles": [{"name": self.payload["name"], "sub_path": self.payload["sub_path"]}],
        }) as fetch:
            response = self.client.get(self.url, {"q": "K2", "kind": "printer"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["engine_version"], "2.4.2")
        self.assertEqual(fetch.call_args.args, ("K2", "printer", "Creality"))

    def test_any_pinned_orca_vendor_is_available_without_download(self):
        self.client.force_login(self.user)
        with patch("core.slicer_api.search_official_profiles") as search:
            response = self.client.get(self.url, {"catalogues": "1", "engine": "orcaslicer"})
        self.assertEqual(response.status_code, 200)
        vendors = {item["id"] for item in response.json()["vendors"]}
        self.assertTrue({"Creality", "Prusa", "Voron", "Anycubic", "Custom"} <= vendors)
        search.assert_not_called()

    def test_selected_manufacturer_is_forwarded_to_backend_search(self):
        self.client.force_login(self.user)
        with patch("core.slicer_api.search_official_profiles", return_value={
            "engine": "orcaslicer", "vendor": "Prusa", "profiles": [],
        }) as search:
            response = self.client.get(self.url, {
                "engine": "orcaslicer", "vendor": "Prusa",
                "kind": "printer", "q": "MK4",
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(search.call_args.args, ("MK4", "printer", "Prusa"))

    def test_official_import_is_candidate_only_and_owned(self):
        self.client.force_login(self.user)
        with patch("core.slicer_api.fetch_official_profile", return_value=self.native):
            result = self.post()
        self.assertEqual(result.status_code, 201, result.content)
        profile = SlicerProfile.objects.get(pk=result.json()["profile"]["id"])
        self.assertEqual(profile.owner, self.user)
        self.assertEqual(profile.engine, "orcaslicer")
        self.assertEqual(profile.engine_version, "2.4.2")
        self.assertEqual(profile.status, "candidate")
        self.assertEqual(profile.verification_evidence, {})
        self.assertEqual(profile.file_asset.category, "source")
        self.assertEqual(profile.file_asset.owner, self.user)
        self.assertIn(b"fdm_creality_common", profile.file_asset.file.read())
        self.assertFalse(result.json()["execution_available"])
        self.addCleanup(lambda asset=profile.file_asset: asset.file.delete(save=False))
        with patch("core.slicer_api.fetch_official_profile", return_value=self.native):
            duplicate = self.post()
        self.assertEqual(duplicate.status_code, 409)

    def test_unprivileged_user_cannot_import(self):
        self.client.force_login(self.other)
        with patch("core.slicer_api.fetch_official_profile") as external:
            result = self.post()
        self.assertEqual(result.status_code, 403)
        external.assert_not_called()
        self.assertFalse(SlicerProfile.objects.exists())

    def test_arbitrary_selection_fields_are_rejected_before_fetch(self):
        self.client.force_login(self.user)
        with patch("core.slicer_api.fetch_official_profile") as external:
            result = self.post({**self.payload, "url": "http://localhost/admin"})
        self.assertEqual(result.status_code, 400)
        external.assert_not_called()
