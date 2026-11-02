"""Safety and API regression tests for the read-only Creality catalogue mirror."""
import json
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase

from core.creality_material_database import MaterialDatabaseError
from core.models import Printer, PrinterConnection, PrinterMaterialDatabaseSnapshot


class CrealityMaterialDatabaseTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="printer-material-owner", password="test")
        self.other = get_user_model().objects.create_user(username="printer-material-other")
        self.owner.user_permissions.add(Permission.objects.get(
            content_type__app_label="core", codename="change_printer"
        ))
        self.printer = Printer.objects.create(owner=self.owner, name="Local CFS", model="K2")
        self.connection = PrinterConnection.objects.create(
            printer=self.printer, adapter="creality_local",
            enabled=True, endpoint_url="ws://192.0.2.44:9999",
        )
        self.client.force_login(self.owner)
        self.url = (
            f"/api/printing/printers/{self.printer.pk}/connections/"
            f"{self.connection.pk}/material-database/"
        )

    def test_read_only_pull_is_explicit_and_never_writes_printer_inventory(self):
        with patch("core.api_views.pull_creality_material_database") as pull:
            pull.return_value = {"top_level_items": 2, "bytes": 100, "synced_at": "2026-11-02T00:00:00Z"}
            self.assertEqual(self.client.get(self.url).status_code, 200)
            pull.assert_not_called()
            self.assertEqual(self.client.post(
                self.url, data=json.dumps({"action": "pull"}),
                content_type="application/json",
            ).status_code, 200)
            pull.assert_called_once()

    def test_configure_requires_permission_and_does_not_leak_credential(self):
        result = self.client.post(self.url, data=json.dumps({
            "action": "configure", "username": "root", "password": "top-secret",
            "fingerprint": "SHA256:example", "scheduled": True,
        }), content_type="application/json")
        self.assertEqual(result.status_code, 200)
        self.assertNotIn("top-secret", result.content.decode())
        self.connection.refresh_from_db()
        self.assertTrue(self.connection.config["material_database_scheduled"])
        self.assertEqual(self.connection.config["material_ssh_password"], "top-secret")
        response = self.client.get(
            f"/api/printing/printers/{self.printer.pk}/connections/"
        )
        self.assertNotIn("top-secret", response.content.decode())
        self.owner.user_permissions.clear()
        self.assertEqual(self.client.post(
            self.url, data=json.dumps({"action": "pull"}),
            content_type="application/json",
        ).status_code, 403)



    def test_discovery_requires_change_permission(self):
        self.owner.user_permissions.clear()
        with patch("core.creality_material_database.discover_creality_host_key") as discover:
            response = self.client.post(self.url, data=json.dumps({"action": "discover-key"}),
                                        content_type="application/json")
        self.assertEqual(response.status_code, 403)
        discover.assert_not_called()

    def test_discovery_returns_key_without_saving_it(self):
        with patch("core.creality_material_database.discover_creality_host_key") as discover:
            discover.return_value = {"algorithm": "ssh-ed25519", "fingerprint": "SHA256:example"}
            response = self.client.post(self.url, data=json.dumps({"action": "discover-key"}),
                                        content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["host_key"]["fingerprint"], "SHA256:example")
        self.connection.refresh_from_db()
        self.assertNotIn("material_ssh_fingerprint", self.connection.config or {})

    def test_ed25519_negotiation_disables_rsa(self):
        from core.creality_material_database import _ed25519_only_options
        blocked = _ed25519_only_options()["keys"]
        self.assertIn("ssh-rsa", blocked)
        self.assertIn("rsa-sha2-256", blocked)
        self.assertIn("rsa-sha2-512", blocked)
        self.assertNotIn("ssh-ed25519", blocked)

    def test_owner_isolation(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_failure_does_not_erase_cached_copy(self):
        from django.utils import timezone
        PrinterMaterialDatabaseSnapshot.objects.create(
            connection=self.connection, payload={"stored": ["PLA"]},
            synced_at=timezone.now(), byte_size=24,
        )
        with patch("core.api_views.pull_creality_material_database", side_effect=MaterialDatabaseError("offline")):
            response = self.client.post(
                self.url, data=json.dumps({"action": "pull"}), content_type="application/json"
            )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(self.connection.material_database_copy.payload, {"stored": ["PLA"]})


class ScpReaderTests(TestCase):
    """Exercise SCP source-mode framing without touching a printer."""

    def _channel(self, response):
        from unittest.mock import MagicMock
        channel = MagicMock()
        chunks = [response[i:i + 1] for i in range(len(response))]
        channel.recv.side_effect = lambda n: chunks.pop(0) if chunks else b""
        client = MagicMock()
        client.get_transport.return_value.open_session.return_value = channel
        return client, channel

    def test_scp_pull_is_read_only_and_bounded(self):
        from core.creality_material_database import _scp_read_database
        payload = b'{"materials":[{"id":"PLA"}]}'
        frame = b"C0644 " + str(len(payload)).encode() + b" material_database.json\n" + payload + b"\x00"
        client, channel = self._channel(frame)
        result = _scp_read_database(client, "/mnt/UDISK/creality/userdata/box/material_database.json")
        self.assertEqual(result, payload)
        channel.exec_command.assert_called_once_with(
            "scp -f /mnt/UDISK/creality/userdata/box/material_database.json"
        )
        self.assertEqual(channel.sendall.call_count, 3)
        self.assertEqual([args.args[0] for args in channel.sendall.call_args_list], [b"\x00"] * 3)
        channel.close.assert_called_once()

    def test_scp_rejects_truncated_file(self):
        from core.creality_material_database import _scp_read_database
        client, channel = self._channel(b"C0644 10 material_database.json\nabc")
        with self.assertRaisesRegex(MaterialDatabaseError, "ended before"):
            _scp_read_database(client, "/fixed/material_database.json")
        channel.close.assert_called_once()

    def test_scp_rejects_oversize_before_acknowledging_file(self):
        from core.creality_material_database import _scp_read_database, MAX_DATABASE_BYTES
        header = b"C0644 " + str(MAX_DATABASE_BYTES + 1).encode() + b" material_database.json\n"
        client, channel = self._channel(header)
        with self.assertRaisesRegex(MaterialDatabaseError, "5 MB"):
            _scp_read_database(client, "/fixed/material_database.json")
        channel.sendall.assert_called_once_with(b"\x00")
        channel.close.assert_called_once()

    def test_scp_rejects_unexpected_filename(self):
        from core.creality_material_database import _scp_read_database
        client, _ = self._channel(b"C0644 3 other.json\nabc\x00")
        with self.assertRaisesRegex(MaterialDatabaseError, "unexpected filename"):
            _scp_read_database(client, "/fixed/material_database.json")

    def test_scp_rejects_remote_file_error_without_exposing_text(self):
        from core.creality_material_database import _scp_read_database
        client, _ = self._channel(b"\x01secret-detail\n")
        with self.assertRaises(MaterialDatabaseError) as raised:
            _scp_read_database(client, "/fixed/material_database.json")
        self.assertNotIn("secret-detail", str(raised.exception))

    def test_ssh_authentication_error_is_specific(self):
        import paramiko
        from unittest.mock import MagicMock
        from core.creality_material_database import pull_creality_material_database
        connection = MagicMock()
        connection.adapter = "creality_local"
        connection.enabled = True
        connection.config = {"material_ssh_user": "root", "material_ssh_password": "private",
                             "material_ssh_fingerprint": "SHA256:example"}
        connection.endpoint_url = "ws://192.0.2.44:9999"
        connection.printer.model = "K2"
        with patch("core.creality_material_database.paramiko.SSHClient") as factory:
            factory.return_value.connect.side_effect = paramiko.AuthenticationException("private")
            with self.assertRaisesRegex(MaterialDatabaseError, "authentication failed") as raised:
                pull_creality_material_database(connection)
            self.assertNotIn("private", str(raised.exception))
            factory.return_value.close.assert_called_once()
