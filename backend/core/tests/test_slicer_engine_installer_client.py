"""Installer URLs remain fixed-origin across the four-container migration."""
import os
from unittest.mock import patch

from django.test import SimpleTestCase
from core.slicer_engine_installer_client import _connection, EngineInstallerUnavailable


class InstallerEndpointTests(SimpleTestCase):
    TOKEN = "a" * 48

    def test_combined_slicer_installer_endpoint_is_approved(self):
        with patch.dict(os.environ, {
            "MAKERVAULT_SLICER_INSTALLER_URL": "http://slicer-worker:8091",
            "MAKERVAULT_SLICER_INSTALLER_TOKEN": self.TOKEN,
        }, clear=True):
            self.assertEqual(_connection(), ("http://slicer-worker:8091", self.TOKEN))

    def test_old_installer_endpoint_remains_approved_for_rollback(self):
        with patch.dict(os.environ, {
            "MAKERVAULT_SLICER_INSTALLER_URL": "http://slicer-engine-installer:8091",
            "MAKERVAULT_SLICER_INSTALLER_TOKEN": self.TOKEN,
        }, clear=True):
            self.assertEqual(_connection(), ("http://slicer-engine-installer:8091", self.TOKEN))

    def test_unapproved_destinations_or_credentials_are_rejected(self):
        for url, token in (
            ("http://example.com:8091", self.TOKEN),
            ("http://127.0.0.1:8091", self.TOKEN),
            ("http://makervault-slicer:8091", self.TOKEN),
            ("http://slicer-worker:8092", self.TOKEN),
            ("https://slicer-worker:8091", self.TOKEN),
            ("http://slicer-worker:8091/status", self.TOKEN),
            ("http://slicer-worker:8091?x=1", self.TOKEN),
            ("http://user@slicer-worker:8091", self.TOKEN),
            ("http://slicer-worker:8091", "short"),
        ):
            with self.subTest(url=url, token=token), patch.dict(os.environ, {
                "MAKERVAULT_SLICER_INSTALLER_URL": url,
                "MAKERVAULT_SLICER_INSTALLER_TOKEN": token,
            }, clear=True):
                with self.assertRaises(EngineInstallerUnavailable):
                    _connection()
