import os
from pathlib import Path
import tempfile
import plistlib
from unittest.mock import patch

from cryptography import x509
from django.contrib.auth import get_user_model
from django.test import TestCase

from core.https_certificates import certificate_status, generate_local_certificate, paths


class LocalHttpsCertificateTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.keys = Path(self.directory.name) / "keys"
        self.tls = self.keys / "tls"
        self.tls.mkdir(parents=True)
        self.env = patch.dict(
            os.environ,
            {
                "MAKERVAULT_TLS_ROOT": str(self.tls),
                "MAKERVAULT_TLS_CERT_FILE": str(self.tls / "cert.pem"),
                "MAKERVAULT_TLS_KEY_FILE": str(self.tls / "key.pem"),
                "MAKERVAULT_HTTPS_ENABLED": "auto",
                "MAKERVAULT_HTTPS_PORT": "8443",
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_generate_local_ca_and_server_certificate(self):
        result = generate_local_certificate(["192.168.1.50", "makervault.local"])
        self.assertIn("192.168.1.50", result["hosts"])
        self.assertTrue(paths()["ca_cert"].is_file())
        self.assertTrue(paths()["ca_key"].is_file())
        self.assertTrue(paths()["server_cert"].is_file())
        self.assertTrue(paths()["server_key"].is_file())
        server = x509.load_pem_x509_certificate(paths()["server_cert"].read_bytes())
        sans = server.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        self.assertIn("192.168.1.50", [str(value) for value in sans.get_values_for_type(x509.IPAddress)])
        self.assertIn("makervault.local", sans.get_values_for_type(x509.DNSName))

    def test_reissue_reuses_existing_ca(self):
        generate_local_certificate(["192.168.1.50"])
        first_ca = paths()["ca_cert"].read_bytes()
        first_server = paths()["server_cert"].read_bytes()
        generate_local_certificate(["192.168.1.126"])
        self.assertEqual(paths()["ca_cert"].read_bytes(), first_ca)
        self.assertNotEqual(paths()["server_cert"].read_bytes(), first_server)

    def test_status_reports_native_url(self):
        generate_local_certificate(["192.168.1.50"])
        status = certificate_status("192.168.1.50:8765")
        self.assertTrue(status["local_ca_available"])
        self.assertTrue(status["server_certificate_available"])
        self.assertEqual(status["native_url"], "https://192.168.1.50:8443")
        self.assertTrue(status["current_host_private"])


class HttpsCertificateApiTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.keys = Path(self.directory.name) / "keys"
        self.tls = self.keys / "tls"
        self.tls.mkdir(parents=True)
        self.env = patch.dict(
            os.environ,
            {
                "MAKERVAULT_TLS_ROOT": str(self.tls),
                "MAKERVAULT_TLS_CERT_FILE": str(self.tls / "cert.pem"),
                "MAKERVAULT_TLS_KEY_FILE": str(self.tls / "key.pem"),
                "MAKERVAULT_HTTPS_ENABLED": "auto",
                "MAKERVAULT_HTTPS_PORT": "8443",
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        User = get_user_model()
        self.admin = User.objects.create_superuser("tls-admin", "tls@example.com", "Strong-test-password-123!")
        self.user = User.objects.create_user("tls-user", "user@example.com", "Strong-test-password-123!")

    def test_superuser_can_generate_and_download_public_ca(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            "/api/settings/https/generate-local/",
            data='{"hosts":["192.168.1.50"]}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["generated"])
        download = self.client.get("/api/settings/https/download-ca/")
        self.assertEqual(download.status_code, 200)
        self.assertIn("attachment", download["Content-Disposition"])

    def test_non_superuser_cannot_manage_certificates(self):
        self.client.force_login(self.user)
        for url in (
            "/api/settings/https/",
            "/api/settings/https/download-ca/",
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403)
        response = self.client.post(
            "/api/settings/https/generate-local/",
            data='{"hosts":["192.168.1.50"]}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_ios_profile_contains_current_public_ca_only(self):
        generate_local_certificate(["192.168.1.50"])
        self.client.force_login(self.admin)
        result = self.client.get("/api/settings/https/download-ios-profile/")
        self.assertEqual(result.status_code, 200)
        self.assertIn("mobileconfig", result["Content-Disposition"])
        self.assertEqual(result["Content-Type"], "application/x-apple-aspen-config")
        profile = plistlib.loads(result.content)
        self.assertEqual(profile["PayloadType"], "Configuration")
        payload = profile["PayloadContent"][0]
        self.assertEqual(payload["PayloadType"], "com.apple.security.root")
        ca = x509.load_pem_x509_certificate(paths()["ca_cert"].read_bytes())
        from cryptography.hazmat.primitives import serialization
        self.assertEqual(payload["PayloadContent"], ca.public_bytes(serialization.Encoding.DER))
        self.assertNotIn(paths()["ca_key"].read_bytes(), result.content)

    def test_ios_profile_requires_superuser_and_existing_ca(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/api/settings/https/download-ios-profile/").status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/api/settings/https/download-ios-profile/").status_code, 404)
