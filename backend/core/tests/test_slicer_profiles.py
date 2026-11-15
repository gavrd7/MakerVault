"""Native profiles are retained for review, not used as executable input."""
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import SimpleTestCase, TestCase

from core.models import FileAsset, SlicerProfile
from core.slicer_profiles import SlicerProfileError, inspect_native_profile


class FakeFile:
    def __init__(self, value):
        self.value = value
        self.name = "files/profile.ini"

    @property
    def storage(self):
        return self

    def open(self, name="rb", mode=None):
        return BytesIO(self.value)


class NativeProfileInspectionTests(SimpleTestCase):
    def asset(self, filename, data):
        return SimpleNamespace(
            name=filename, metadata={"original_name": filename},
            file=FakeFile(data),
        )

    def test_native_prusa_ini_is_bounded_and_hashed(self):
        report = inspect_native_profile(
            self.asset("machine.ini", b"layer_height = 0.2\nnozzle_diameter = 0.4\n"),
            "prusaslicer",
        )
        self.assertEqual(report["bytes"], 41)
        self.assertEqual(len(report["sha256"]), 64)
        self.assertEqual(report["extension"], ".ini")

    def test_orca_keeps_json_native_format(self):
        report = inspect_native_profile(
            self.asset("filament.json", b'{"filament_type":["PLA"],"name":"PLA"}'), "orcaslicer"
        )
        self.assertEqual(report["extension"], ".json")
        for data in (b"[]", b"{", b"\x00", b'{"post_process_scripts":"curl example.com"}'):
            with self.subTest(data=data), self.assertRaises(SlicerProfileError):
                inspect_native_profile(self.asset("filament.json", data), "orcaslicer")

    def test_any_manufacturer_native_candidate_is_accepted_in_its_own_engine_format(self):
        # No hardcoded printer allowlist; registration does not verify execution.
        for engine in ("orcaslicer", "crealityprint", "bambustudio", "snapmakerorca"):
            for machine in ("Voron 2.4", "Prusa MK4", "Custom CoreXY"):
                with self.subTest(engine=engine, machine=machine):
                    import json
                    native = json.dumps({
                        "type": "machine", "name": machine,
                        "nozzle_diameter": ["0.4"],
                    }).encode()
                    report = inspect_native_profile(self.asset("machine.json", native), engine)
                    self.assertEqual(report["engine"], engine)
                    self.assertEqual(report["extension"], ".json")
        for machine in ("Voron 2.4", "Prusa MK4", "Custom CoreXY"):
            with self.subTest(engine="prusaslicer", machine=machine):
                native = ("printer_model = " + machine + "\\nnozzle_diameter = 0.4\\n").encode()
                report = inspect_native_profile(self.asset("machine.ini", native), "prusaslicer")
                self.assertEqual(report["extension"], ".ini")

    def test_rejects_prusa_profile_post_processing(self):
        for body in (
            b"post_process_scripts = /tmp/script\n",
            b"post_process = /bin/sh\n",
            b"x = 1\n" + b"x" * (1024 * 1024),
            b"random\n",
        ):
            with self.subTest(body=body[:40]), self.assertRaises(SlicerProfileError):
                inspect_native_profile(self.asset("machine.ini", body), "prusaslicer")

    def test_inherited_orca_profile_is_preserved_but_flagged_incomplete(self):
        report = inspect_native_profile(
            self.asset("child.json", b'{"name":"Child","inherits":"Vendor machine base"}'),
            "orcaslicer",
        )
        self.assertTrue(report["requires_parent_bundle"])
        self.assertEqual(report["inherits"], "Vendor machine base")

    def test_fails_closed_for_profile_format_mismatch(self):
        with self.assertRaises(SlicerProfileError):
            inspect_native_profile(self.asset("machine.json", b'{"name":"profile"}'), "prusaslicer")


class SlicerProfileApiTests(TestCase):
    def setUp(self):
        model = get_user_model()
        self.owner = model.objects.create_user(username="profile-owner", password="test")
        self.other = model.objects.create_user(username="profile-other", password="test")
        self.owner.user_permissions.add(Permission.objects.get(codename="add_fileasset"))
        self.file = FileAsset.objects.create(
            owner=self.owner, name="Printer profile", category="source",
            metadata={"original_name": "printer.ini", "extension": ".ini"},
        )
        self.url = "/api/printing/slicer/profiles/"
        self.data = {
            "file_asset_id": str(self.file.id), "engine": "prusaslicer",
            "engine_version": "2.9.7", "kind": "printer",
            "name": "Generic FDM", "provenance": "Manual export",
        }

    def post(self, body=None):
        import json
        return self.client.post(self.url, json.dumps(self.data if body is None else body), content_type="application/json")

    @patch("core.slicer_api.inspect_native_profile", return_value={"sha256": "b" * 64, "bytes": 120})
    def test_import_is_unverified_and_private(self, inspect):
        self.client.force_login(self.owner)
        r = self.post()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["profile"]["status"], "candidate")
        self.assertFalse(r.json()["execution_available"])
        self.assertEqual(SlicerProfile.objects.count(), 1)
        self.assertEqual(self.post().status_code, 409)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).json()["profiles"], [])
        self.assertEqual(self.post().status_code, 403)

    def test_build_plate_read_only_endpoint_is_owner_scoped(self):
        from unittest.mock import patch
        profile = SlicerProfile.objects.create(
            owner=self.owner, engine="orcaslicer", engine_version="2.4.2",
            kind="printer", name="Generic bed", file_asset=self.file,
            content_sha256="c" * 64,
        )
        url = f"/api/printing/slicer/profiles/{profile.pk}/plate/"
        self.client.force_login(self.owner)
        expected = {
            "status": "available", "polygon_mm": [[0, 0], [200, 0], [200, 200], [0, 200]],
            "size_mm": [200, 200, 200], "fit_check": "not_performed",
        }
        with patch("core.slicer_api.inspect_orca_plate", return_value=expected):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["plate"]["size_mm"], [200, 200, 200])
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)

    @patch("core.slicer_api.inspect_native_profile", return_value={"sha256": "b" * 64, "bytes": 120})
    def test_client_cannot_set_verified_status_or_foreign_asset(self, inspect):
        self.client.force_login(self.owner)
        self.assertEqual(self.post({**self.data, "status": "verified"}).status_code, 400)
        self.assertEqual(self.post({**self.data, "file_asset_id": str(FileAsset.objects.create(owner=self.other, name="Other", category="source").id)}).status_code, 400)
        self.assertEqual(SlicerProfile.objects.count(), 0)
