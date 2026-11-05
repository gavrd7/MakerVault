"""Contract tests for experimental printer file APIs. No hardware is commanded."""
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from core.bambu_storage import BambuStorageError, _fingerprint_or_fail, _parse_listing, list_bambu_storage
from core.flashforge_gcode import FlashForgeFileError, supports_simple_print, list_files as list_flashforge_files
from core.creality_gcode import CrealityGcodeError, _http_root, _safe_printer_file, _parse_file_list, list_files as list_creality_files, start_single_spool

from core.gcode_analysis import inspect_asset
from core.printer_gcode_submission import (
    GcodeSubmissionError, _valid_path, availability,
    list_printer_gcodes, _octoprint_upload_receipt, _verify_moonraker_upload,
    _verify_creality_upload, _require_action_ready, _mapped_cfs_entries,
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
        self.assertTrue(creality["can_upload"])  # owner printer-control permissions are sufficient
        self.assertFalse(creality["can_start"])   # CFS state unknown

    def test_native_submission_uses_control_permissions_without_experimental_switches(self):
        ff = connection("flashforge")
        ff.printer = SimpleNamespace(model="Adventurer 5M Pro", catalog_model=None)
        self.assertTrue(availability(ff)["supported"])
        self.assertTrue(availability(ff)["can_upload"])
        ff.config["gcode_submission_enabled"] = True
        self.assertTrue(availability(ff)["can_upload"])
        self.assertTrue(availability(ff)["can_start"])
        ff.printer.model = "AD5X"
        self.assertFalse(availability(ff)["supported"])
        cc = connection("creality_local")
        cc.printer = SimpleNamespace(model="K2", catalog_model=None)
        cc.controls_enabled = False
        cc.config["gcode_submission_enabled"] = False
        self.assertTrue(availability(cc)["can_upload"])
        self.assertFalse(availability(cc)["can_start"])

    def test_moonraker_family_octoprint_and_prusalink_are_experimental(self):
        for adapter in ("moonraker", "octoprint", "qidi", "elegoo", "sovol", "voron", "snapmaker"):
            caps = availability(connection(adapter))
            self.assertTrue(caps["supported"], adapter)
            self.assertTrue(caps["can_start"], adapter)
            self.assertTrue(caps["can_upload"], adapter)
        prusa = connection("prusa")
        self.assertTrue(availability(prusa)["supported"])
        self.assertTrue(availability(prusa)["can_start"])
        prusa.config["gcode_submission_enabled"] = True
        self.assertTrue(availability(prusa)["can_start"])

    def test_stale_or_busy_printer_cannot_start(self):
        self.assertFalse(availability(connection("moonraker", state="printing"))["can_start"])
        self.assertFalse(availability(connection("octoprint", status="disconnected"))["can_start"])

    @patch("core.creality_gcode.list_files")
    @patch("core.printer_gcode_submission._get_json")
    @patch("core.printer_gcode_submission.PrinterConnection.objects.filter")
    def test_creality_browse_prefers_same_printer_moonraker(self, filtered, get_json, native_browse):
        native = connection("creality_local")
        native.printer_id = "my-printer"
        moon = connection("moonraker")
        filtered.return_value.order_by.return_value = [moon]
        get_json.return_value = [{"path": "ghost.gcode", "size": 123}]
        result = list_printer_gcodes(native)
        self.assertEqual(result[0]["path"], "ghost.gcode")
        self.assertEqual(filtered.call_args.kwargs["printer_id"], "my-printer")
        native_browse.assert_not_called()

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


class NativeGcodeAdapterTests(SimpleTestCase):
    def test_flashforge_multimaterial_models_never_gain_start(self):
        for name in ("AD5X", "Creator 5 Pro", "Adventurer 4"):
            printer = SimpleNamespace(model=name, catalog_model=None)
            self.assertFalse(supports_simple_print(printer))
        self.assertTrue(supports_simple_print(
            SimpleNamespace(model="FlashForge Adventurer 5M", catalog_model=None)
        ))

    @patch("core.flashforge_gcode.requests.post")
    def test_flashforge_read_only_recent_file_list(self, post):
        printer = connection("flashforge")
        printer.config = {"serial": "TESTSERIAL", "check_code": "test-code"}
        response = Mock(status_code=200)
        response.json.return_value = {"code": 0, "gcodeList": ["part.gcode", "../escape.gcode", "notes.txt"]}
        post.return_value = response
        rows = list_flashforge_files(printer)
        self.assertEqual([file["path"] for file in rows], ["part.gcode"])
        self.assertTrue(post.call_args.args[0].endswith("/gcodeList"))
        self.assertFalse(post.call_args.kwargs["allow_redirects"])

    def test_stock_creality_file_list_response_and_safety(self):
        payload = {"params": {"gcodeFileList": [
            {"fileName": "/mnt/UDISK/printer_data/gcodes/part.gcode", "size": 1200},
            {"fileName": "../../escape.gcode"},
        ]}}
        rows = _parse_file_list(payload)
        self.assertEqual([f["path"] for f in rows], ["part.gcode"])
        self.assertIsNone(_safe_printer_file("../escape.gcode"))
        self.assertIsNone(_safe_printer_file("/etc/escape.gcode"))

    def test_creality_native_start_requires_separate_opt_in_and_no_cfs(self):
        cc = connection("creality_local")
        cc.printer = SimpleNamespace(model="K1", catalog_model=None)
        cc.config["gcode_submission_enabled"] = True
        self.assertFalse(availability(cc)["can_start"])
        cc.config["creality_single_spool_start_enabled"] = True
        cc.last_snapshot["source_metadata"] = {"cfs_connected": False}
        self.assertTrue(availability(cc)["can_start"])
        cc.last_snapshot["source_metadata"] = {"cfs_connected": True}
        self.assertFalse(availability(cc)["can_start"])

    @patch("core.printer_gcode_submission.PrinterConnection.objects.filter")
    def test_k2_cfs_is_shared_with_moonraker_and_blocks_start_only(self, filtered):
        moon = connection("moonraker")
        moon.printer = SimpleNamespace(model="K2", manufacturer="Creality", catalog_model=None)
        moon.printer_id = "printer-one"
        native = connection("creality_local")
        native.last_snapshot["source_metadata"] = {"cfs_connected": True}
        native.last_snapshot["materials"] = [{
            "system": "creality_cfs", "unit_index": 0, "slot_index": 1,
            "material": "PLA", "product_name": "Hyper PLA", "color_hex": "#ffffff",
        }]
        filtered.return_value.order_by.return_value = [native]
        caps = availability(moon)
        self.assertTrue(caps["can_upload"])
        self.assertFalse(caps["can_start"])
        self.assertTrue(caps["can_start_sliced_mapping"])
        with self.assertRaises(GcodeSubmissionError):
            _require_action_ready(moon, "print")
        _require_action_ready(moon, "print", use_sliced_cfs=True)
        self.assertTrue(caps["cfs"]["connected"])
        self.assertEqual(caps["cfs"]["slots"][0]["label"], "1B")
        native.last_snapshot["source_metadata"] = {"cfs_connected": False}
        self.assertTrue(availability(moon)["can_start"])
        native.last_seen_at = timezone.now() - timezone.timedelta(minutes=5)
        self.assertFalse(availability(moon)["can_start"])
        self.assertFalse(availability(moon)["can_start_sliced_mapping"])
        with self.assertRaises(GcodeSubmissionError):
            _require_action_ready(moon, "print", use_sliced_cfs=True)

    @patch("core.printer_gcode_submission.PrinterConnection.objects.filter")
    def test_mapped_cfs_validates_physical_slots_and_materials(self, filtered):
        moon = connection("moonraker")
        moon.printer = SimpleNamespace(model="K2", manufacturer="Creality", catalog_model=None)
        moon.printer_id = "one-printer"
        native = connection("creality_local")
        native.last_snapshot["source_metadata"] = {"cfs_connected": True}
        native.last_snapshot["materials"] = [{
            "system": "creality_cfs", "unit_index": 0, "slot_index": 2,
            "material": "PLA", "color_hex": "#ffffff",
        }]
        filtered.return_value.order_by.return_value = [native]
        req = [{"tool_index": 0, "material": "PLA", "color_hex": "#000000"}]
        chosen = [{"tool_index": 0, "slot_label": "1C"}]
        mapped = _mapped_cfs_entries(moon, req, chosen)
        self.assertEqual(mapped, [{
            "id": "T1A", "type": "PLA", "color": "#ffffff", "boxId": 1, "materialId": 2,
        }])
        req[0]["material"] = "PETG"
        with self.assertRaisesRegex(GcodeSubmissionError, "Material mismatch"):
            _mapped_cfs_entries(moon, req, chosen)
        req[0]["material"] = "PLA"
        with self.assertRaises(GcodeSubmissionError):
            _mapped_cfs_entries(moon, req, [{"tool_index": 0, "slot_label": "2A"}])
        native.last_seen_at = timezone.now() - timezone.timedelta(minutes=5)
        with self.assertRaises(GcodeSubmissionError):
            _mapped_cfs_entries(moon, req, chosen)

    @patch("core.creality_gcode.websockets.connect")
    def test_mapped_creality_command_sequence_once(self, connect):
        import asyncio
        import json
        from core.creality_gcode import _start_cfs_mapped, start_cfs_mapped
        ws = AsyncMock()
        connect.return_value.__aenter__.return_value = ws
        items = [{"id": "T1A", "type": "PLA", "color": "#ffffff", "boxId": 1, "materialId": 2}]
        asyncio.run(_start_cfs_mapped("ws://k2.local:9999", "ghost.gcode", items))
        self.assertEqual(ws.send.await_count, 2)
        first = json.loads(ws.send.await_args_list[0].args[0])
        second = json.loads(ws.send.await_args_list[1].args[0])
        self.assertEqual(first["params"]["colorMatch"]["list"], items)
        self.assertEqual(second["params"]["multiColorPrint"]["gcode"], "/mnt/UDISK/printer_data/gcodes/ghost.gcode")
        with patch("core.creality_gcode.asyncio.run") as runner:
            with self.assertRaises(CrealityGcodeError):
                start_cfs_mapped(connection("creality_local"), "../danger.gcode", items)
            runner.assert_not_called()

    @patch("core.printer_gcode_submission.PrinterConnection.objects.filter")
    @patch("core.printer_gcode_submission._verify_moonraker_upload")
    def test_native_creality_upload_uses_same_printer_moonraker_verification(self, verify, filtered):
        native = connection("creality_local")
        native.printer_id = "one-printer"
        moon = connection("moonraker")
        filtered.return_value.order_by.return_value = [moon]
        verify.return_value = {"path": "mv_ghost.gcode", "size_bytes": 1200}
        result = _verify_creality_upload(native, "mv_ghost.gcode", 1200)
        self.assertEqual(result["size_bytes"], 1200)
        verify.assert_called_once_with(moon, "mv_ghost.gcode", 1200)
        self.assertEqual(filtered.call_args.kwargs["printer_id"], "one-printer")
        moon.status = "disconnected"
        with self.assertRaises(GcodeSubmissionError):
            _verify_creality_upload(native, "mv_ghost.gcode", 1200)

    @patch("core.creality_gcode.asyncio.run")
    def test_creality_start_rejects_path_traversal_without_websocket(self, worker):
        cc = connection("creality_local")
        with self.assertRaises(CrealityGcodeError):
            start_single_spool(cc, "../escape.gcode")
        worker.assert_not_called()


    @patch("core.printer_gcode_submission.list_printer_gcodes")
    def test_moonraker_upload_requires_file_and_matching_bytes(self, browse):
        printer = connection("moonraker")
        browse.return_value = [{"path": "mv_test.gcode", "size_bytes": 2048}]
        self.assertEqual(_verify_moonraker_upload(printer, "mv_test.gcode", 2048)["size_bytes"], 2048)
        with self.assertRaises(GcodeSubmissionError):
            _verify_moonraker_upload(printer, "mv_test.gcode", 2047)
        browse.return_value = []
        with self.assertRaises(GcodeSubmissionError):
            _verify_moonraker_upload(printer, "mv_test.gcode", 2048)

    @patch("core.creality_gcode.asyncio.run")
    def test_creality_browser_preserves_real_error(self, run):
        from core.creality_gcode import list_files
        printer = connection("creality_local")
        run.side_effect = CrealityGcodeError("Unrecognized printer file list")
        with self.assertRaisesRegex(CrealityGcodeError, "Unrecognized printer"):
            list_files(printer)


    def test_inspection_does_not_consume_or_reopen_closed_fieldfile(self):
        """Inspection and subsequent transfer must each obtain their own storage handle."""
        content = b"; printer: K2\\nG90\\nG1 X20 Y20 F3000\\n"
        storage = SimpleNamespace(open=Mock(side_effect=lambda name, mode: BytesIO(content)))
        # Mimic Django FieldFile after its original underlying handle has been closed.
        file_field = SimpleNamespace(name="ghost.gcode", storage=storage,
                                     open=Mock(side_effect=ValueError("The file cannot be reopened.")))
        asset = SimpleNamespace(file=file_field, metadata={"original_name": "ghost.gcode"}, name="ghost")
        report = inspect_asset(asset)
        self.assertIn("analysis", report)
        with asset.file.storage.open(asset.file.name, "rb") as transfer_handle:
            self.assertEqual(transfer_handle.read(), content)
        self.assertEqual(storage.open.call_count, 2)
        file_field.open.assert_not_called()

    @patch("core.creality_gcode.requests.post")
    def test_stock_creality_upload_uses_native_multipart_file(self, post):
        from io import BytesIO
        from core.creality_gcode import upload_only
        printer = connection("creality_local")
        printer.endpoint_url = "ws://k2.local:9999"
        fake = BytesIO(b"G90\nG1 X20\n")
        asset = SimpleNamespace(file=SimpleNamespace(storage=SimpleNamespace(open=lambda name, mode: fake), name="ghost.gcode", size=11))
        response = Mock(status_code=200)
        post.return_value = response
        upload_only(printer, asset, "ghost.gcode")
        self.assertIn("/upload/ghost.gcode", post.call_args.args[0])
        self.assertIn("file", post.call_args.kwargs["files"])
        self.assertNotIn("data", post.call_args.kwargs)
        self.assertFalse(post.call_args.kwargs["allow_redirects"])

    def test_creality_upload_target_is_same_host_no_credentials(self):
        printer = connection("creality_local")
        printer.endpoint_url = "ws://k2.local:9999"
        self.assertEqual(_http_root(printer), "http://k2.local:80")
        printer.endpoint_url = "ws://user:secret@k2.local:9999"
        with self.assertRaises(Exception):
            _http_root(printer)
