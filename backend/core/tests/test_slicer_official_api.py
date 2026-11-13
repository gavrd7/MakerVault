"""Official preset browser imports remain owner-scoped and unverified."""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase

from core.models import FileAsset, Printer, SlicerProfile


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

    def test_all_supported_official_catalogues_report_read_only_import_capabilities(self):
        self.client.force_login(self.user)
        creality = self.client.get(self.url, {"catalogues": "1", "engine": "crealityprint"})
        self.assertEqual(creality.status_code, 200)
        self.assertTrue(creality.json()["official_search_available"])
        self.assertEqual(creality.json()["native_profile_format"], "creality-json")
        self.assertTrue({"Prusa", "Voron", "Anycubic", "Custom", "Creality"} <=
                        {vendor["id"] for vendor in creality.json()["vendors"]})
        for engine, fmt, vendor in (
            ("prusaslicer", "prusa-ini", "PrusaResearch"),
            ("bambustudio", "bambu-json", "BBL"),
            ("snapmakerorca", "snapmaker-orca-json", "Snapmaker"),
        ):
            with self.subTest(engine=engine):
                result = self.client.get(self.url, {"catalogues": "1", "engine": engine})
                self.assertEqual(result.status_code, 200)
                self.assertIn(vendor, {item["id"] for item in result.json()["vendors"]})
                self.assertTrue(result.json()["official_search_available"])
                self.assertTrue(result.json()["manual_import_available"])
                self.assertFalse(result.json()["verified_for_execution"])
                self.assertEqual(result.json()["native_profile_format"], fmt)

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

    def test_printer_filter_resolves_own_model_and_rejects_foreign_printers(self):
        self.client.force_login(self.user)
        own = Printer.objects.create(owner=self.user, name="K1", model="Creality K1")
        foreign = Printer.objects.create(owner=self.other, name="K2", model="Creality K2")
        with patch("core.slicer_api.search_official_profiles", return_value={
            "engine": "orcaslicer", "profiles": [],
        }) as search:
            filtered = self.client.get(self.url, {
                "engine": "orcaslicer", "vendor": "Creality",
                "kind": "process", "q": "0.20mm", "printer_id": str(own.pk),
            })
            self.assertEqual(filtered.status_code, 200, filtered.content)
            self.assertEqual(filtered.json()["printer_model_filter"], "Creality K1")
            search.assert_called_once_with(
                "0.20mm", "process", "Creality", printer_model="Creality K1"
            )
            search.reset_mock()
            denied = self.client.get(self.url, {
                "kind": "process", "q": "0.20mm", "printer_id": str(foreign.pk),
            })
            self.assertEqual(denied.status_code, 404)
            search.assert_not_called()

    def test_official_model_dropdown_and_validated_model_override(self):
        self.client.force_login(self.user)
        model_list = ["Creality K1", "Creality K1 Max", "Creality K2"]
        with patch("core.slicer_api.orca_catalogue_models", return_value=model_list) as catalogue:
            result = self.client.get(self.url, {
                "engine": "orcaslicer", "vendor": "Creality", "models": "1",
            })
            self.assertEqual(result.status_code, 200, result.content)
            self.assertEqual(result.json()["models"], model_list)
            catalogue.assert_called_with("Creality")
            with patch("core.slicer_api.search_official_profiles", return_value={
                "engine": "orcaslicer", "profiles": [],
            }) as search:
                filtered = self.client.get(self.url, {
                    "engine": "orcaslicer", "vendor": "Creality",
                    "kind": "process", "q": "K1 standard", "model": "Creality K1",
                })
                self.assertEqual(filtered.status_code, 200, filtered.content)
                search.assert_called_once_with(
                    "K1 standard", "process", "Creality",
                    printer_model="Creality K1"
                )
                search.reset_mock()
                invalid = self.client.get(self.url, {
                    "engine": "orcaslicer", "vendor": "Creality",
                    "kind": "process", "q": "K1", "model": "Invented model",
                })
                self.assertEqual(invalid.status_code, 400)
                search.assert_not_called()

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

    def test_cross_manufacturer_crealityprint_import_stays_native_and_unverified(self):
        self.client.force_login(self.user)
        raw = json.dumps({
            "type": "machine", "name": "Prusa MK4 0.4 nozzle",
            "nozzle_diameter": ["0.4"],
            "printable_area": ["0x0", "250x0", "250x210", "0x210"],
        }).encode()
        selection = {
            "engine": "crealityprint", "kind": "printer", "vendor": "Prusa",
            "name": "Prusa MK4 0.4 nozzle",
            "sub_path": "machine/Prusa MK4 0.4 nozzle.json",
        }
        with patch("core.slicer_api.official_profile_chain", return_value=[
            ("Prusa MK4 0.4 nozzle", selection["sub_path"], raw)
        ]) as chain:
            response = self.post(selection)
        self.assertEqual(response.status_code, 201, response.content)
        chain.assert_called_once_with(
            "crealityprint", "printer", selection["name"], selection["sub_path"], "Prusa"
        )
        profile = SlicerProfile.objects.get(pk=response.json()["profile"]["id"])
        self.assertEqual(profile.engine, "crealityprint")
        self.assertEqual(profile.engine_version, "7.3.0")
        self.assertEqual(profile.status, "candidate")
        self.assertIn("CrealityOfficial/CrealityPrint@v7.3.0/Prusa/", profile.provenance)
        self.assertFalse(response.json()["execution_available"])
        self.addCleanup(lambda asset=profile.file_asset: asset.file.delete(save=False))

    def test_orca_25_catalogue_search_and_manufacturer_brand_filter(self):
        self.client.force_login(self.user)
        result = self.client.get(self.url, {
            "engine": "orcaslicer", "version": "2.5.0", "catalogues": "1",
        })
        self.assertEqual(result.status_code, 200)
        self.assertIn("2.5.0", result.json()["versions"])
        self.assertIn("OrcaFilamentLibrary", {row["id"] for row in result.json()["vendors"]})
        with patch("core.slicer_api.official_filament_brands", return_value=["eSUN", "SUNLU"]):
            brands = self.client.get(self.url, {
                "engine": "orcaslicer", "version": "2.5.0",
                "vendor": "OrcaFilamentLibrary", "brands": "1",
            })
        self.assertEqual(brands.status_code, 200)
        self.assertEqual(brands.json()["brands"], ["eSUN", "SUNLU"])
        with patch("core.slicer_api.search_official_profiles", return_value={
            "engine": "orcaslicer", "engine_version": "2.5.0", "profiles": [],
        }) as search:
            found = self.client.get(self.url, {
                "engine": "orcaslicer", "version": "2.5.0",
                "kind": "filament", "vendor": "OrcaFilamentLibrary",
                "brand": "eSUN", "q": "PLA",
            })
        self.assertEqual(found.status_code, 200)
        search.assert_called_once_with(
            "PLA", "filament", "OrcaFilamentLibrary",
            printer_model=None, version="2.5.0", brand="eSUN",
        )
        invalid = self.client.get(self.url, {
            "engine": "orcaslicer", "version": "2.6.0", "catalogues": "1",
        })
        self.assertEqual(invalid.status_code, 400)

    def test_orca_25_native_import_does_not_relabel_existing_24_profile(self):
        self.client.force_login(self.user)
        raw = b'{"name":"eSUN PLA+ @base","type":"filament"}'
        selection = {
            "engine":"orcaslicer", "engine_version":"2.5.0",
            "vendor":"OrcaFilamentLibrary", "kind":"filament",
            "name":"eSUN PLA+ @base", "sub_path":"filament/eSUN/eSUN PLA+ @base.json",
        }
        with patch("core.slicer_api.official_profile_chain",
                   return_value=[(selection["name"], selection["sub_path"], raw)]) as chain:
            response = self.post(selection)
        self.assertEqual(response.status_code, 201, response.content)
        chain.assert_called_once_with(
            "orcaslicer", "filament", selection["name"], selection["sub_path"],
            "OrcaFilamentLibrary", version="2.5.0",
        )
        profile = SlicerProfile.objects.get(pk=response.json()["profile"]["id"])
        self.assertEqual(profile.engine_version,"2.5.0")
        self.assertEqual(profile.status,"candidate")
        self.assertIn("@v2.5.0/OrcaFilamentLibrary/filament/eSUN/", profile.provenance)
        self.addCleanup(lambda asset=profile.file_asset: asset.file.delete(save=False))

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
