"""Contract tests for experimental printer file APIs. No hardware is commanded."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from core.bambu_storage import BambuStorageError, _fingerprint_or_fail, _parse_listing, list_bambu_storage

from core.printer_gcode_submission import (
    GcodeSubmissionError, _valid_path, availability,
    list_printer_gcodes, _octoprint_upload_receipt,
)


def connection(adapter, *, enabled=True, status="connected", state="idle"):
    return SimpleNamespace(
        adapter=adapter,
        endpoint_url="http://printer.local:7125" if adapter != "prusa" else "http://prusa.local",
        config={"api_key": "test-api-key"},
        enabled=enabled, controls_enabled=True, status=status,
        last_seen_at=timezone.now(),
        last_snapshot={"online": True, "state": state},
    )


class GcodePrinterContractTests(SimpleTestCase):
    def test_file_paths_cannot_escape_printer_storage(self):
        for invalid in ("../escape.gcode", "/etc/escape.gcode", "folder//file.gcode",
                        "folder/./file.gcode", "folder\\bad.gcode", "danger.txt", ""):
            self.assertFalse(_valid_path(invalid), invalid)
        self.assertTrue(_valid_path("folder/part.gcode"))

    def test_unsupported_proprietary_adapters_never_advertise_submission(self):
        for adapter in ("bambu_local", "anycubic", "flashforge", "simplyprint"):
            self.assertFalse(availability(connection(adapter))["supported"])
            self.assertFalse(availability(connection(adapter))["can_start"])
        creality = availability(connection("creality_local"))
        self.assertTrue(creality["supported"])
        self.assertFalse(creality["can_upload"])  # explicit opt-in needed
        self.assertFalse(creality["can_start"])   # native start never enabled

    def test_native_flashforge_and_creality_requires_opt_in(self):
        ff = connection("flashforge")
        ff.printer = SimpleNamespace(model="Adventurer 5M Pro", catalog_model=None)
        self.assertTrue(availability(ff)["supported"])
        self.assertFalse(availability(ff)["can_upload"])
        ff.config["gcode_submission_enabled"] = True
        self.assertTrue(availability(ff)["can_upload"])
        self.assertTrue(availability(ff)["can_start"])
        ff.printer.model = "AD5X"
        self.assertFalse(availability(ff)["supported"])
        cc = connection("creality_local")
        cc.printer = SimpleNamespace(model="K2", catalog_model=None)
        cc.config["gcode_submission_enabled"] = True
        self.assertTrue(availability(cc)["can_upload"])
        self.assertFalse(availability(cc)["can_start"])

    def test_moonraker_family_octoprint_and_prusalink_are_experimental(self):
        for adapter in ("moonraker", "octoprint", "prusa", "qidi", "elegoo", "sovol", "voron", "snapmaker"):
            caps = availability(connection(adapter))
            self.assertTrue(caps["supported"], adapter)
            self.assertTrue(caps["can_start"], adapter)
            self.assertTrue(caps["can_upload"], adapter)

    def test_stale_or_busy_printer_cannot_start(self):
        self.assertFalse(availability(connection("moonraker", state="printing"))["can_start"])
        self.assertFalse(availability(connection("octoprint", status="disconnected"))["can_start"])

    @patch("core.printer_gcode_submission.requests.get")
    def test_octoprint_local_storage_listing(self, get):
        response = Mock(status_code=200)
        response.json.return_value = {"files": [
            {"name": "part.gcode", "path": "part.gcode", "type": "machinecode", "size": 1250},
            {"name": "info.txt", "path": "info.txt", "type": "file"},
        ]}
        get.return_value = response
        rows = list_printer_gcodes(connection("octoprint"))
        self.assertEqual([item["path"] for item in rows], ["part.gcode"])
        self.assertIn("/api/files/local", get.call_args.args[0])
        self.assertFalse(get.call_args.kwargs["allow_redirects"])

    @patch("core.printer_gcode_submission.requests.get")
    def test_prusalink_native_file_listing(self, get):
        response = Mock(status_code=200)
        response.json.return_value = {"children": [
            {"name": "part.gcode", "type": "PRINT_FILE", "size": 1000},
            {"name": "config.txt", "type": "FILE", "size": 100},
        ]}
        get.return_value = response
        rows = list_printer_gcodes(connection("prusa"))
        self.assertEqual([item["path"] for item in rows], ["part.gcode"])
        self.assertIn("/api/v1/files/local/", get.call_args.args[0])
        self.assertFalse(get.call_args.kwargs["allow_redirects"])

    def test_octoprint_upload_requires_created_receipt(self):
        response = Mock(status_code=201)
        response.json.return_value = {"files": {"local": {"path": "part.gcode"}}}
        self.assertEqual(_octoprint_upload_receipt(response)["files"]["local"]["path"], "part.gcode")
        response.status_code = 409
        with self.assertRaises(GcodeSubmissionError):
            _octoprint_upload_receipt(response)


class BambuReadOnlyStorageTests(SimpleTestCase):
    def test_missing_pin_never_attempts_network_or_credentials(self):
        printer = connection("bambu_local")
        printer.config = {"access_code": "test-secret"}
        with patch("core.bambu_storage.socket.create_connection") as connect:
            with self.assertRaises(BambuStorageError):
                list_bambu_storage(printer)
            connect.assert_not_called()

    def test_invalid_pin_fails_closed(self):
        with self.assertRaises(BambuStorageError):
            _fingerprint_or_fail("TOFU")
        with self.assertRaises(BambuStorageError):
            _fingerprint_or_fail("a" * 63)
        self.assertEqual(_fingerprint_or_fail("AB:" * 31 + "AB"), "ab" * 32)

    def test_directory_parser_does_not_return_traversal_paths(self):
        self.assertIsNone(_parse_listing("-rw-r--r-- 1 root root 20 Jan 1 12:00 ../file.gcode"))
        self.assertIsNone(_parse_listing("-rw-r--r-- 1 root root 20 Jan 1 12:00 folder/part.gcode"))
        result = _parse_listing("-rw-r--r-- 1 root root 20 Jan 1 12:00 model.gcode.3mf")
        self.assertEqual(result["name"], "model.gcode.3mf")
        self.assertEqual(result["size_bytes"], 20)

    def test_bambu_browse_does_not_enable_upload_or_start(self):
        printer = connection("bambu_local")
        printer.config["bambu_ftps_cert_sha256"] = "a" * 64
        state = availability(printer)
        self.assertTrue(state["can_browse"])
        self.assertFalse(state["supported"])
        self.assertFalse(state["can_upload"])
        self.assertFalse(state["can_start"])
