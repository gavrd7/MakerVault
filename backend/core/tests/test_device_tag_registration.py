"""Security and lifecycle tests for connected RFID terminal registration."""
import json
from unittest.mock import patch
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.utils import timezone

from core.device_api_keys import generate_token
from core.models import ConnectedDevice, DeviceTagRegistration, InventoryItem, MakerTag, UserApiKey


@override_settings(DEBUG=True)
class ConnectedTagRegistrationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="tag-reg-owner", password="password")
        self.other = User.objects.create_user(username="tag-reg-other", password="password")
        for codename in ("add_makertag", "view_makertag", "view_inventoryitem"):
            perm = Permission.objects.get(content_type__app_label="core", codename=codename)
            self.owner.user_permissions.add(perm)
        self.item = InventoryItem.objects.create(
            owner=self.owner, inventory_id="OTH-1491", item_type="other",
            custom_name="Connected registration item", quantity=1,
        )
        token = generate_token()
        self.key = UserApiKey.objects.create(
            owner=self.owner, name="Handheld", identifier=token.identifier,
            secret_digest=token.digest, scopes=["tags:read", "tags:write", "devices:status"],
        )
        self.token = token.plaintext
        self.device = ConnectedDevice.objects.create(
            owner=self.owner, device_uid="test-rfid-terminal-149",
            name="Test terminal", device_type="rfid_terminal", api_key=self.key,
        )
        self.client.force_login(self.owner)

    def start(self, **overrides):
        payload = {"device_id": str(self.device.pk), "target_type": "inventory", "target_id": str(self.item.pk)}
        payload.update(overrides)
        return self.client.post(
            "/api/device/tag-registration/", data=json.dumps(payload), content_type="application/json"
        )

    def complete(self, session_id, *, uid="04AABBCCDDEEFF", token=None):
        return self.client.post(
            f"/api/device/v1/tag-registration/{session_id}/complete/",
            data=json.dumps({"kind": "nfc", "uid": uid}), content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + (token or self.token),
        )

    def test_create_poll_complete_and_retry(self):
        created = self.start()
        self.assertEqual(created.status_code, 201, created.content)
        rid = created.json()["id"]
        self.assertEqual(self.start().status_code, 409)
        pending = self.client.get("/api/device/v1/tag-registration/pending/", HTTP_AUTHORIZATION="Bearer " + self.token)
        self.assertEqual(pending.status_code, 200)
        self.assertEqual(pending.json()["registration"]["id"], rid)
        finished = self.complete(rid)
        self.assertEqual(finished.status_code, 201, finished.content)
        self.assertEqual(finished.json()["state"], "completed")
        self.assertEqual(self.complete(rid).status_code, 200)
        self.assertEqual(self.complete(rid, uid="04AABBCCDDEE00").status_code, 409)
        self.assertEqual(MakerTag.objects.filter(owner=self.owner, code="04AABBCCDDEEFF").count(), 1)
        tag = MakerTag.objects.get(owner=self.owner, code="04AABBCCDDEEFF")
        from core.maker_tags import serialise_tag
        details = serialise_tag(tag)
        self.assertEqual(details["maker_tag_id"], "MV-" + tag.short_id)
        self.assertEqual(details["code"], "04AABBCCDDEEFF")
        self.assertEqual(details["kind"], "nfc")
        self.assertEqual(MakerTag.objects.filter(owner=self.owner, code=tag.code).count(), 1)
        self.assertEqual(self.client.get(f"/api/device/tag-registration/{rid}/").json()["state"], "completed")

    def test_pending_ndef_write_blocks_new_registration_before_assignment(self):
        from core.models import DeviceNdefWrite
        change = Permission.objects.get(content_type__app_label="core", codename="change_makertag")
        self.owner.user_permissions.add(change)
        self.device.capabilities = ["ntag215_ndef_write"]
        self.device.save(update_fields=["capabilities"])
        origin = "http://192.168.1.125:8000"
        data = {"origin": origin, "override": ""}
        with self.settings(DEBUG=True):
            def start_nfc():
                payload = {"device_id": str(self.device.pk), "target_type": "inventory",
                           "target_id": str(self.item.pk), **data}
                return self.client.post("/api/device/tag-registration/",
                                        data=json.dumps(payload), content_type="application/json",
                                        HTTP_ORIGIN=origin)
            started = start_nfc()
            self.assertEqual(started.status_code, 201, started.content)
            finished = self.complete(started.json()["id"])
            self.assertEqual(finished.status_code, 201, finished.content)
            self.assertTrue(finished.json()["ndef_write_id"])
            self.assertEqual(DeviceNdefWrite.objects.filter(state="pending").count(), 1)
            blocked = start_nfc()
            self.assertEqual(blocked.status_code, 409, blocked.content)
            self.assertIn("pending NFC write", blocked.json()["error"])
            self.assertEqual(DeviceTagRegistration.objects.count(), 1)

    def test_repeat_assignment_same_target_is_idempotent(self):
        initial_id = self.start().json()["id"]
        self.assertEqual(self.complete(initial_id).status_code, 201)
        tag = MakerTag.objects.get(owner=self.owner, code="04AABBCCDDEEFF")
        previous_count = tag.events.count() if hasattr(tag, "events") else None
        second_id = self.start().json()["id"]
        response = self.complete(second_id)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["state"], "completed")
        self.assertEqual(response.json()["tag"]["id"], str(tag.pk))
        self.assertEqual(MakerTag.objects.filter(owner=self.owner, code=tag.code).count(), 1)
        if previous_count is not None:
            tag.refresh_from_db()
            self.assertEqual(tag.events.count(), previous_count)

    def test_single_session_queues_server_authorized_ndef_write(self):
        from core.models import DeviceNdefWrite
        change = Permission.objects.get(content_type__app_label="core", codename="change_makertag")
        self.owner.user_permissions.add(change)
        self.device.capabilities = ["ntag215_ndef_write"]
        self.device.save(update_fields=["capabilities"])
        origin = "http://192.168.1.125:8000"
        data = {"device_id": str(self.device.pk), "target_type": "inventory",
                "target_id": str(self.item.pk), "origin": origin, "override": ""}
        started = self.client.post("/api/device/tag-registration/",
                                   data=json.dumps(data), content_type="application/json",
                                   HTTP_ORIGIN=origin)
        self.assertEqual(started.status_code, 201, started.content)
        rid = started.json()["id"]
        assigned = self.complete(rid)
        self.assertEqual(assigned.status_code, 201, assigned.content)
        self.assertEqual(assigned.json()["state"], "completed")
        self.assertTrue(assigned.json()["ndef_write_id"])
        request = DeviceNdefWrite.objects.get(pk=assigned.json()["ndef_write_id"])
        self.assertEqual(request.expected_uid, "04AABBCCDDEEFF")
        self.assertEqual(request.url, f"{origin}/t/MV-{request.tag.short_id}/")
        self.assertEqual(assigned.json()["ndef_write"]["state"], "pending")
        self.assertEqual(self.client.get(f"/api/device/tag-registration/{rid}/").json()["ndef_write"]["id"], str(request.pk))
        done = self.client.post(f"/api/device/v1/ndef-write/{request.pk}/complete/",
                                data=json.dumps({"uid": request.expected_uid, "verified_url": request.url}),
                                content_type="application/json", HTTP_AUTHORIZATION="Bearer " + self.token)
        self.assertEqual(done.status_code, 200, done.content)
        self.assertEqual(self.client.get(f"/api/device/tag-registration/{rid}/").json()["ndef_write"]["state"], "completed")

    def test_combined_session_rejects_spoofed_browser_origin(self):
        data = {"device_id": str(self.device.pk), "target_type": "inventory",
                "target_id": str(self.item.pk), "origin": "https://vault.example.com", "override": ""}
        result = self.client.post("/api/device/tag-registration/",
                                  data=json.dumps(data), content_type="application/json",
                                  HTTP_ORIGIN="https://different.example.com")
        self.assertEqual(result.status_code, 400)
        self.assertFalse(DeviceTagRegistration.objects.exists())

    def test_reassignment_preflight_uses_one_physical_confirmation(self):
        change = Permission.objects.get(content_type__app_label="core", codename="change_makertag")
        self.owner.user_permissions.add(change)
        tag = MakerTag.objects.create(
            owner=self.owner, kind="nfc", code="04AABBCCDDEEFF",
            target_type="inventory", target_id=self.item.pk,
        )
        other_item = InventoryItem.objects.create(
            owner=self.owner, inventory_id="OTH-1492", item_type="other",
            custom_name="Other target", quantity=1,
        )
        start = self.start(target_id=str(other_item.pk))
        self.assertEqual(start.status_code, 201, start.content)
        rid = start.json()["id"]
        probe = self.client.post(
            f"/api/device/v1/tag-registration/{rid}/probe/",
            data=json.dumps({"kind": "nfc", "uid": tag.code}),
            content_type="application/json", HTTP_AUTHORIZATION="Bearer " + self.token,
        )
        self.assertEqual(probe.status_code, 200, probe.content)
        token = probe.json()["reassign_token"]
        self.assertTrue(probe.json()["reassign_required"])
        confirm = self.client.post(
            f"/api/device/v1/tag-registration/{rid}/complete/",
            data=json.dumps({"kind": "nfc", "uid": tag.code, "reassign_token": token}),
            content_type="application/json", HTTP_AUTHORIZATION="Bearer " + self.token,
        )
        self.assertEqual(confirm.status_code, 201, confirm.content)
        tag.refresh_from_db()
        self.assertEqual(tag.target_id, other_item.pk)
        self.assertEqual(confirm.json()["state"], "completed")

    def test_preflight_does_not_change_existing_assignment(self):
        tag = MakerTag.objects.create(
            owner=self.owner, kind="nfc", code="04AABBCCDDEEFF",
            target_type="inventory", target_id=self.item.pk,
        )
        rid = self.start().json()["id"]
        response = self.client.post(
            f"/api/device/v1/tag-registration/{rid}/probe/",
            data=json.dumps({"kind": "nfc", "uid": tag.code}),
            content_type="application/json", HTTP_AUTHORIZATION="Bearer " + self.token,
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["already_assigned"])
        self.assertFalse(response.json()["reassign_required"])
        self.assertEqual(DeviceTagRegistration.objects.get(pk=rid).state, "pending")

    def test_cancel_and_expiry(self):
        rid = self.start().json()["id"]
        self.assertEqual(self.client.post(f"/api/device/tag-registration/{rid}/cancel/").status_code, 200)
        self.assertEqual(self.complete(rid).status_code, 410)
        second = self.start().json()["id"]
        DeviceTagRegistration.objects.filter(pk=second).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.complete(second).status_code, 410)
        self.assertEqual(self.client.get(f"/api/device/tag-registration/{second}/").json()["state"], "expired")

    def test_other_owner_cannot_read_or_cancel(self):
        rid = self.start().json()["id"]
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(f"/api/device/tag-registration/{rid}/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/device/tag-registration/{rid}/cancel/").status_code, 404)
        self.assertEqual(self.start().status_code, 400)

    def test_unpaired_key_and_insufficient_scope(self):
        rid = self.start().json()["id"]
        rogue = generate_token()
        UserApiKey.objects.create(
            owner=self.owner, name="Not paired", identifier=rogue.identifier,
            secret_digest=rogue.digest, scopes=["tags:write"],
        )
        self.assertEqual(self.complete(rid, token=rogue.plaintext).status_code, 403)
        self.key.scopes = ["tags:read"]
        self.key.save(update_fields=["scopes"])
        self.assertEqual(self.complete(rid).status_code, 403)
        self.assertEqual(self.start().status_code, 403)

    def test_registered_tag_collision_is_not_reassigned(self):
        existing = MakerTag.objects.create(
            owner=self.owner, kind="nfc", code="04AABBCCDDEEFF",
            target_type="inventory", target_id=self.item.pk,
        )
        rid = self.start().json()["id"]
        self.assertEqual(self.complete(rid).status_code, 200)
        self.assertEqual(DeviceTagRegistration.objects.get(pk=rid).state, "completed")
        existing.refresh_from_db()
        self.assertEqual(existing.target_id, self.item.pk)

    def test_nfc_and_rfid_kinds_share_one_physical_uid(self):
        # A UID registered through the legacy RFID option must not be
        # registered again as an NFC tag through the connected terminal.
        existing = MakerTag.objects.create(
            owner=self.owner, kind="rfid", code="04AABBCCDDEEFF",
            target_type="inventory", target_id=self.item.pk,
        )
        rid = self.start().json()["id"]
        response = self.complete(rid)
        self.assertEqual(response.status_code, 200)
        existing.refresh_from_db()
        self.assertEqual(existing.kind, "rfid")
        self.assertEqual(MakerTag.objects.filter(code=existing.code).count(), 1)

    def test_cross_kind_retry_is_idempotent(self):
        rid = self.start().json()["id"]
        self.assertEqual(self.complete(rid).status_code, 201)
        response = self.client.post(
            f"/api/device/v1/tag-registration/{rid}/complete/",
            data=json.dumps({"kind": "rfid", "uid": "04AABBCCDDEEFF"}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + self.token,
        )
        self.assertEqual(response.status_code, 200)

    def test_wrong_paired_terminal_cannot_poll_or_complete(self):
        rid = self.start().json()["id"]
        second_token = generate_token()
        other_key = UserApiKey.objects.create(
            owner=self.owner, name="Second terminal", identifier=second_token.identifier,
            secret_digest=second_token.digest, scopes=["tags:write"],
        )
        ConnectedDevice.objects.create(
            owner=self.owner, device_uid="second-rfid-terminal-149", name="Second terminal",
            device_type="rfid_terminal", api_key=other_key,
        )
        pending = self.client.get(
            "/api/device/v1/tag-registration/pending/",
            HTTP_AUTHORIZATION="Bearer " + second_token.plaintext,
        )
        self.assertEqual(pending.status_code, 200)
        self.assertIsNone(pending.json()["registration"])
        self.assertEqual(self.complete(rid, token=second_token.plaintext).status_code, 404)
        self.assertEqual(DeviceTagRegistration.objects.get(pk=rid).state, "pending")

    def test_revocation_blocks_pending_and_completion(self):
        rid = self.start().json()["id"]
        self.device.revoked_at = timezone.now()
        self.device.save(update_fields=["revoked_at"])
        response = self.client.get(
            "/api/device/v1/tag-registration/pending/",
            HTTP_AUTHORIZATION="Bearer " + self.token,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.complete(rid).status_code, 403)

    def test_browser_mutation_requires_csrf(self):
        from django.test import Client
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        response = csrf_client.post(
            "/api/device/tag-registration/",
            data=json.dumps({"device_id": str(self.device.pk), "target_type": "inventory",
                             "target_id": str(self.item.pk)}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(DeviceTagRegistration.objects.exists())

    @override_settings(DEBUG=False)
    def test_device_credentials_rejected_over_plain_http_in_production(self):
        response = self.client.get(
            "/api/device/v1/tag-registration/pending/",
            HTTP_AUTHORIZATION="Bearer " + self.token,
        )
        self.assertEqual(response.status_code, 403)

    def test_terminal_lookup_does_not_create_or_change_tag(self):
        known = MakerTag.objects.create(
            owner=self.owner, kind="nfc", code="04AABBCCDDEEFF",
            target_type="inventory", target_id=self.item.pk,
        )
        created = self.client.post(
            "/api/device/tag-lookup/",
            data=json.dumps({"device_id": str(self.device.pk)}),
            content_type="application/json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        lookup_id = created.json()["id"]
        pending = self.client.get(
            "/api/device/v1/tag-lookup/pending/",
            HTTP_AUTHORIZATION="Bearer " + self.token,
        )
        self.assertEqual(pending.status_code, 200)
        self.assertEqual(pending.json()["lookup"]["id"], lookup_id)
        complete = self.client.post(
            f"/api/device/v1/tag-lookup/{lookup_id}/complete/",
            data=json.dumps({"kind": "rfid", "uid": "04AABBCCDDEEFF"}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + self.token,
        )
        self.assertEqual(complete.status_code, 201, complete.content)
        self.assertTrue(complete.json()["found"])
        self.assertEqual(complete.json()["tag"]["id"], str(known.pk))
        self.assertEqual(MakerTag.objects.count(), 1)
        self.assertEqual(self.client.get(f"/api/device/tag-lookup/{lookup_id}/").json()["state"], "completed")

    def test_terminal_lookup_unknown_uid_and_cancel(self):
        created = self.client.post(
            "/api/device/tag-lookup/",
            data=json.dumps({"device_id": str(self.device.pk)}),
            content_type="application/json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        lookup_id = created.json()["id"]
        complete = self.client.post(
            f"/api/device/v1/tag-lookup/{lookup_id}/complete/",
            data=json.dumps({"kind": "nfc", "uid": "04AABBCCDDEEFF"}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + self.token,
        )
        self.assertEqual(complete.status_code, 201)
        self.assertFalse(complete.json()["found"])
        self.assertEqual(MakerTag.objects.count(), 0)
        other = self.client.post(
            "/api/device/tag-lookup/",
            data=json.dumps({"device_id": str(self.device.pk)}),
            content_type="application/json",
        )
        self.assertEqual(other.status_code, 201)
        second_id = other.json()["id"]
        self.assertEqual(self.client.post(f"/api/device/tag-lookup/{second_id}/cancel/").status_code, 200)
        rejected = self.client.post(
            f"/api/device/v1/tag-lookup/{second_id}/complete/",
            data=json.dumps({"kind": "nfc", "uid": "04AABBCCDDEEFF"}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + self.token,
        )
        self.assertEqual(rejected.status_code, 410)


    def test_short_id_collision_retries_without_changing_physical_uids(self):
        with patch("core.models.secrets.token_hex", side_effect=[
            "0123abcd", "0123abcd", "9876fedc"
        ]):
            first = MakerTag.objects.create(
                owner=self.owner, kind="nfc", code="0477A1A2772681",
                target_type="inventory", target_id=self.item.pk,
            )
            second = MakerTag.objects.create(
                owner=self.owner, kind="nfc", code="04AABBCCDDEEFF",
                target_type="inventory", target_id=self.item.pk,
            )
        self.assertEqual(first.short_id, "0123ABCD")
        self.assertEqual(second.short_id, "9876FEDC")
        self.assertEqual(first.code, "0477A1A2772681")
        self.assertEqual(second.code, "04AABBCCDDEEFF")

    def test_reassignment_requires_second_confirmation_and_preserves_identity(self):
        from core.models import MakerTagEvent
        second = InventoryItem.objects.create(
            owner=self.owner, inventory_id="OTH-1492", item_type="other",
            custom_name="Replacement item", quantity=1,
        )
        existing = MakerTag.objects.create(
            owner=self.owner, kind="nfc", code="04AABBCCDDEEFF",
            target_type="inventory", target_id=self.item.pk,
        )
        rid = self.start(target_id=str(second.pk)).json()["id"]
        denied = self.complete(rid)
        self.assertEqual(denied.status_code, 403)
        self.owner.user_permissions.add(Permission.objects.get(
            content_type__app_label="core", codename="change_makertag"
        ))
        preview = self.complete(rid)
        self.assertEqual(preview.status_code, 409, preview.content)
        self.assertTrue(preview.json()["reassign_required"])
        existing.refresh_from_db()
        self.assertEqual(existing.target_id, self.item.pk)
        self.assertEqual(MakerTagEvent.objects.filter(tag=existing, event_type="reassigned").count(), 0)
        token = preview.json()["reassign_token"]
        confirmed = self.client.post(
            f"/api/device/v1/tag-registration/{rid}/complete/",
            data=json.dumps({"kind": "nfc", "uid": existing.code, "reassign_token": token}),
            content_type="application/json", HTTP_AUTHORIZATION="Bearer " + self.token,
        )
        self.assertEqual(confirmed.status_code, 201, confirmed.content)
        existing.refresh_from_db()
        self.assertEqual(existing.target_id, second.pk)
        self.assertEqual(existing.short_id, MakerTag.objects.get(pk=existing.pk).short_id)
        self.assertEqual(MakerTag.objects.count(), 1)
        event = MakerTagEvent.objects.get(tag=existing, event_type="reassigned")
        self.assertEqual(event.details["previous"]["target_id"], str(self.item.pk))
        self.assertIn("Connected registration item", event.details["previous_label"])
        self.assertIn("Replacement item", event.details["new_label"])
        from core.maker_tags import serialise_tag
        history = serialise_tag(existing, include_events=True)["events"]
        move = next(entry for entry in history if entry["event_type"] == "reassigned")
        self.assertIn("OTH-1491", move["summary"])
        self.assertIn("OTH-1492", move["summary"])
        self.assertEqual(self.complete(rid).status_code, 200)

    def test_reassignment_confirmation_cannot_be_replayed_for_another_tag(self):
        second = InventoryItem.objects.create(
            owner=self.owner, inventory_id="OTH-1493", item_type="other",
            custom_name="Other target", quantity=1,
        )
        MakerTag.objects.create(owner=self.owner, kind="nfc", code="04AABBCCDDEEFF",
                                target_type="inventory", target_id=self.item.pk)
        MakerTag.objects.create(owner=self.owner, kind="nfc", code="04112233445566",
                                target_type="inventory", target_id=self.item.pk)
        self.owner.user_permissions.add(Permission.objects.get(
            content_type__app_label="core", codename="change_makertag"
        ))
        rid = self.start(target_id=str(second.pk)).json()["id"]
        token = self.complete(rid).json()["reassign_token"]
        wrong = self.client.post(
            f"/api/device/v1/tag-registration/{rid}/complete/",
            data=json.dumps({"kind": "nfc", "uid": "04112233445566", "reassign_token": token}),
            content_type="application/json", HTTP_AUTHORIZATION="Bearer " + self.token,
        )
        self.assertEqual(wrong.status_code, 409)
        self.assertEqual(MakerTag.objects.filter(target_id=second.pk).count(), 0)

    def test_reassigning_same_target_is_a_noop(self):
        MakerTag.objects.create(owner=self.owner, kind="nfc", code="04AABBCCDDEEFF",
                                target_type="inventory", target_id=self.item.pk)
        rid = self.start().json()["id"]
        response = self.complete(rid)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "completed")
        self.assertNotIn("reassign_token", response.json())

    def test_browser_can_resume_and_cancel_an_abandoned_registration(self):
        rid = self.start().json()["id"]
        pending = self.client.get(
            "/api/device/tag-registration/pending/?device_id=" + str(self.device.pk)
        )
        self.assertEqual(pending.status_code, 200, pending.content)
        self.assertEqual(pending.json()["registration"]["id"], rid)
        self.assertEqual(self.start().status_code, 409)
        cancelled = self.client.post(f"/api/device/tag-registration/{rid}/cancel/")
        self.assertEqual(cancelled.status_code, 200)
        empty = self.client.get(
            "/api/device/tag-registration/pending/?device_id=" + str(self.device.pk)
        )
        self.assertIsNone(empty.json()["registration"])
        self.assertEqual(self.start().status_code, 201)

    def test_handheld_back_cancels_only_its_own_request(self):
        rid = self.start().json()["id"]
        denied = self.client.post(
            f"/api/device/v1/tag-registration/{rid}/cancel/"
        )
        self.assertEqual(denied.status_code, 401)
        result = self.client.post(
            f"/api/device/v1/tag-registration/{rid}/cancel/",
            HTTP_AUTHORIZATION="Bearer " + self.token,
        )
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.json()["state"], "cancelled")
        self.assertEqual(self.complete(rid).status_code, 410)
        self.assertEqual(MakerTag.objects.count(), 0)

    def test_terminal_status_reflects_browser_cancellation(self):
        rid = self.start().json()["id"]
        url = f"/api/device/v1/tag-registration/{rid}/status/"
        active = self.client.get(url, HTTP_AUTHORIZATION="Bearer " + self.token)
        self.assertEqual(active.status_code, 200, active.content)
        self.assertEqual(active.json()["state"], "pending")
        self.assertEqual(self.client.post(f"/api/device/tag-registration/{rid}/cancel/").status_code, 200)
        cancelled = self.client.get(url, HTTP_AUTHORIZATION="Bearer " + self.token)
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["state"], "cancelled")

    def test_unpaired_credentials_cannot_inspect_terminal_registration_status(self):
        rid = self.start().json()["id"]
        rogue = generate_token()
        UserApiKey.objects.create(
            owner=self.owner, name="Rogue", identifier=rogue.identifier,
            secret_digest=rogue.digest, scopes=["tags:write"],
        )
        status = self.client.get(
            f"/api/device/v1/tag-registration/{rid}/status/",
            HTTP_AUTHORIZATION="Bearer " + rogue.plaintext,
        )
        self.assertEqual(status.status_code, 403)
