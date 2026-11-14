"""Contract tests for experimental printer file APIs. No hardware is commanded."""
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock, AsyncMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from core.bambu_storage import BambuStorageError, _fingerprint_or_fail, _parse_listing, list_bambu_storage
from core.flashforge_gcode import FlashForgeFileError, supports_simple_print, list_files as list_flashforge_files
from core.creality_gcode import CrealityGcodeError, _http_root, _safe_printer_file, _parse_file_list, list_files as list_creality_files, start_single_spool

from core.gcode_analysis import inspect_asset
from core.printer_gcode_submission import (
    GcodeSubmissionError, _valid_path, availability,
    list_printer_gcodes, _octoprint_upload_receipt, _verify_moonraker_upload,
    _verify_creality_upload, _require_action_ready, _mapped_cfs_entries, _printer_transfer_name,
    inspect_printer_file,
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
    @patch("core.printer_gcode_submission._same_printer_moonraker")
    @patch("core.printer_gcode_submission.list_printer_gcodes")
    @patch("core.printer_gcode_submission.requests.get")
    def test_read_only_printer_file_inspection_finds_used_filament(self, get, listed, source):
        moon = connection("moonraker")
        native = connection("creality_local")
        source.return_value = moon
        content = (b"; filament_type = PLA; PLA; PLA; PLA\n"
                   b"; filament_colour = #000000; #e83d89; #ffffff; #668798\n"
                   b"T2\nG92 E0\nG1 X10 Y10 E0.2\n")
        listed.return_value = [{"path": "ghost.gcode", "size_bytes": len(content)}]
        response = MagicMock(status_code=200)
        response.iter_content.return_value = [content]
        response.__enter__.return_value = response
        get.return_value = response
        result = inspect_printer_file(native, "ghost.gcode")
        self.assertTrue(result["filaments"]["usage_confident"])
        self.assertEqual(result["filaments"]["used_tool_indices"], [2])
        self.assertEqual(result["filaments"]["used_requirements"][0]["color_hex"], "#ffffff")
        self.assertIn("/server/files/gcodes/ghost.gcode", get.call_args.args[0])
        self.assertFalse(get.call_args.kwargs["allow_redirects"])
        with self.assertRaises(GcodeSubmissionError):
            inspect_printer_file(native, "../bad.gcode")
        source.return_value = None
        with self.assertRaises(GcodeSubmissionError):
            inspect_printer_file(native, "ghost.gcode")

    def test_adapter_neutral_start_verification_requires_matching_active_file(self):
        from core.printer_gcode_submission import _matches_active_print, START_VERIFY_ADAPTERS
        snapshot = {
            "online": True, "state": "printing",
            "job": {"file_name": "folder/part.gcode"},
        }
        for adapter in ("moonraker", "octoprint", "prusa", "flashforge",
                        "snapmaker", "elegoo", "qidi", "sovol", "voron"):
            with self.subTest(adapter=adapter):
                self.assertIn(adapter, START_VERIFY_ADAPTERS)
                printer = connection(adapter)
                self.assertTrue(_matches_active_print(printer, snapshot, "folder/part.gcode"))
                self.assertFalse(_matches_active_print(printer, snapshot, "other/part.gcode"))
                self.assertFalse(_matches_active_print(printer, {**snapshot, "state": "idle"}, "folder/part.gcode"))
                self.assertFalse(_matches_active_print(printer, {**snapshot, "online": False}, "folder/part.gcode"))
                self.assertFalse(_matches_active_print(printer, {**snapshot, "job": {"file_name": ""}}, "folder/part.gcode"))
        native = connection("creality_local")
        self.assertFalse(_matches_active_print(native, snapshot, "folder/part.gcode"))
        self.assertTrue(_matches_active_print(native, {
            **snapshot, "source_metadata": {"raw_state": 1},
        }, "folder/part.gcode"))

    @patch("core.printer_gcode_submission.PrinterGcodeSubmission.objects.filter")
    def test_generic_acknowledged_receipt_upgrades_only_with_matching_job(self, filtered):
        from core.printer_gcode_submission import (
            reconcile_print_start_receipts, _pending_start_message,
        )
        printer = connection("moonraker")
        row = SimpleNamespace(
            pk="receipt-1", status="started", remote_path="folder/part.gcode",
            message=_pending_start_message("folder/part.gcode", acknowledged=True),
        )
        candidates = MagicMock()
        candidates.order_by.return_value.__getitem__.return_value = [row]
        updated = Mock()
        updated.update.return_value = 1
        filtered.side_effect = [candidates, updated]
        snapshot = {
            "online": True, "state": "printing", "job": {"file_name": "folder/part.gcode"},
            "captured_at": timezone.now().isoformat(),
        }
        self.assertEqual(reconcile_print_start_receipts(printer, snapshot), 1)
        self.assertEqual(updated.update.call_args.kwargs["status"], "started")
        self.assertIn("verified", updated.update.call_args.kwargs["message"])

    @patch("core.printer_gcode_submission.PrinterGcodeSubmission.objects.filter")
    def test_generic_unacknowledged_receipt_requires_exact_job(self, filtered):
        from core.printer_gcode_submission import (
            reconcile_print_start_receipts, _pending_start_message,
        )
        printer = connection("flashforge")
        row = SimpleNamespace(
            pk="receipt-2", status="unknown", remote_path="part.gcode",
            message=_pending_start_message("part.gcode", acknowledged=False),
        )
        candidates = MagicMock()
        candidates.order_by.return_value.__getitem__.return_value = [row]
        filtered.return_value = candidates
        data = {"online": True, "state": "printing", "job": {"file_name": "other.gcode"},
                "captured_at": timezone.now().isoformat()}
        self.assertEqual(reconcile_print_start_receipts(printer, data), 0)
        self.assertEqual(filtered.call_count, 1)
        self.assertEqual(reconcile_print_start_receipts(printer, {**data, "state": "idle"}), 0)
        self.assertEqual(filtered.call_count, 1)

    @patch("core.printer_connectivity.poll_connection")
    def test_generic_immediate_verification_only_polls(self, poll):
        from core.printer_gcode_submission import _verify_print_start_now
        printer = connection("octoprint")
        _verify_print_start_now(printer)
        poll.assert_called_once_with(printer)
        poll.side_effect = RuntimeError("offline")
        _verify_print_start_now(printer)
        self.assertEqual(poll.call_count, 2)

    def test_k1_native_print_uses_standard_flow_with_fresh_idle_no_cfs_status(self):
        from core.printer_gcode_submission import availability, _require_action_ready
        k1 = connection("creality_local")
        k1.printer = SimpleNamespace(model="K1", catalog_model=None)
        k1.last_snapshot["source_metadata"] = {"cfs_connected": False}
        state = availability(k1)
        self.assertTrue(state["k1_native_model"])
        self.assertTrue(state["can_browse"])
        self.assertTrue(state["can_upload"])
        self.assertTrue(state["can_start"])
        _require_action_ready(k1, "print")
        # A legacy opt-in value has no bearing on print-start permissions.
        k1.config["k1_native_start_test_enabled"] = False
        self.assertTrue(availability(k1)["can_start"])
        k1.last_snapshot["state"] = "printing"
        self.assertFalse(availability(k1)["can_start"])

    def test_k1_start_blockers_explain_stale_or_busy_telemetry(self):
        from datetime import timedelta
        from core.printer_gcode_submission import availability
        k1 = connection("creality_local")
        k1.printer = SimpleNamespace(model="K1", catalog_model=None)
        k1.last_seen_at = timezone.now() - timedelta(minutes=3)
        state = availability(k1)
        self.assertFalse(state["can_start"])
        self.assertTrue(any("older than 60 seconds" in reason for reason in state["k1_start_blockers"]))
        k1.last_seen_at = timezone.now()
        k1.last_snapshot = {
            "online": True, "state": "printing",
            "source_metadata": {"cfs_connected": False},
        }
        state = availability(k1)
        self.assertFalse(state["can_start"])
        self.assertTrue(any("not confirmed idle" in reason for reason in state["k1_start_blockers"]))
        k1.last_snapshot["state"] = "idle"
        self.assertTrue(availability(k1)["can_start"])
        self.assertEqual(availability(k1)["k1_start_blockers"], [])

    def test_k2_is_not_treated_as_k1(self):
        from core.printer_gcode_submission import availability
        k2 = connection("creality_local")
        k2.printer = SimpleNamespace(model="K2", catalog_model=None)
        self.assertFalse(availability(k2)["k1_native_model"])
        k2.last_snapshot["source_metadata"] = {"cfs_connected": False}
        self.assertTrue(availability(k2)["can_start"])

    def test_native_idle_release_needs_positive_idle_state_and_no_active_job(self):
        from core.printer_gcode_submission import _native_creality_clearly_idle
        idle = {
            "online": True, "state": "idle", "job": {"file_name": "", "progress": 0},
            "source_metadata": {
                "raw_state": 0, "device_state": 0, "power_loss_recovery": False,
            },
        }
        self.assertTrue(_native_creality_clearly_idle(idle))
        for snap in (
            {**idle, "online": False},
            {**idle, "state": "processing"},
            {**idle, "source_metadata": {"raw_state": 1, "device_state": 0}},
            {**idle, "source_metadata": {"raw_state": 0, "power_loss_recovery": True}},
            {**idle, "job": {"file_name": "3DBenchy.gcode"}},
            {**idle, "job": {"file_name": "", "progress": 2}},
        ):
            self.assertFalse(_native_creality_clearly_idle(snap))

    @patch("core.printer_connectivity.poll_connection")
    def test_native_idle_release_requires_two_new_observations(self, poll):
        from core.printer_gcode_submission import _native_idle_after_unknown
        from datetime import timedelta
        printer = connection("creality_local")
        start = timezone.now()
        def idle(when):
            return {
                "online": True, "state": "idle",
                "job": {"file_name": "", "progress": 0},
                "source_metadata": {"raw_state": 0, "device_state": 0},
                "captured_at": when.isoformat(),
            }
        poll.side_effect = [
            idle(start + timedelta(seconds=1)),
            idle(start + timedelta(seconds=2)),
        ]
        self.assertTrue(_native_idle_after_unknown(printer, start))
        self.assertEqual(poll.call_count, 2)
        poll.side_effect = [
            idle(start + timedelta(seconds=1)),
            {**idle(start + timedelta(seconds=2)), "state": "printing"},
        ]
        self.assertFalse(_native_idle_after_unknown(printer, start))
        poll.side_effect = [idle(start - timedelta(seconds=1))]
        self.assertFalse(_native_idle_after_unknown(printer, start))
        poll.side_effect = [idle(start + timedelta(seconds=1)), idle(start + timedelta(seconds=1))]
        self.assertFalse(_native_idle_after_unknown(printer, start))
        poll.reset_mock()
        self.assertFalse(_native_idle_after_unknown(connection("octoprint"), start))
        poll.assert_not_called()

    def test_creality_start_confirmation_requires_same_file_and_active_raw_state(self):
        from core.printer_gcode_submission import _creality_started_file
        snapshot = {
            "online": True, "state": "printing",
            "job": {"file_name": "3DBenchy.gcode", "progress": 1},
            "source_metadata": {"raw_state": 1},
        }
        self.assertTrue(_creality_started_file(snapshot, "3DBenchy.gcode"))
        self.assertFalse(_creality_started_file(snapshot, "ghost.gcode"))
        self.assertFalse(_creality_started_file({**snapshot, "state": "idle"}, "3DBenchy.gcode"))
        self.assertFalse(_creality_started_file({**snapshot, "state": "processing"}, "3DBenchy.gcode"))
        self.assertFalse(_creality_started_file({**snapshot, "online": False}, "3DBenchy.gcode"))
        self.assertFalse(_creality_started_file({
            **snapshot, "source_metadata": {"raw_state": 0},
        }, "3DBenchy.gcode"))
        self.assertFalse(_creality_started_file({
            **snapshot, "job": {"file_name": ""},
        }, "3DBenchy.gcode"))

    @patch("core.printer_gcode_submission.PrinterGcodeSubmission.objects.filter")
    def test_native_start_receipt_reconciles_only_exact_active_print(self, filter_rows):
        from core.printer_gcode_submission import (
            reconcile_creality_start_receipts, _creality_start_receipt_message,
        )
        printer = connection("creality_local")
        printer.id = "connection-1"
        row = SimpleNamespace(
            pk="receipt-1", remote_path="3DBenchy.gcode",
            message=_creality_start_receipt_message("3DBenchy.gcode"),
        )
        candidates = MagicMock()
        candidates.order_by.return_value.__getitem__.return_value = [row]
        update_queryset = Mock()
        update_queryset.update.return_value = 1
        filter_rows.side_effect = [candidates, update_queryset]
        snapshot = {
            "online": True, "captured_at": timezone.now().isoformat(),
            "state": "printing", "job": {"file_name": "3DBenchy.gcode"},
            "source_metadata": {"raw_state": 1},
        }
        self.assertEqual(reconcile_creality_start_receipts(printer, snapshot), 1)
        self.assertEqual(filter_rows.call_count, 2)
        self.assertEqual(filter_rows.call_args.kwargs["pk"], "receipt-1")
        self.assertEqual(filter_rows.call_args.kwargs["status"], "unknown")
        self.assertEqual(update_queryset.update.call_args.kwargs["status"], "started")

    @patch("core.printer_gcode_submission.PrinterGcodeSubmission.objects.filter")
    def test_native_start_does_not_upgrade_unrelated_or_old_telemetry(self, filtered):
        from core.printer_gcode_submission import reconcile_creality_start_receipts
        printer = connection("creality_local")
        snapshot = {
            "online": True, "state": "printing", "job": {"file_name": "other.gcode"},
            "source_metadata": {"raw_state": 1},
            "captured_at": timezone.now().isoformat(),
        }
        filtered.return_value.order_by.return_value.__getitem__.return_value = [
            SimpleNamespace(pk="r1", remote_path="3DBenchy.gcode")
        ]
        self.assertEqual(reconcile_creality_start_receipts(printer, snapshot), 0)
        self.assertEqual(filtered.call_count, 1)
        self.assertEqual(reconcile_creality_start_receipts(printer, {**snapshot, "captured_at": ""}), 0)
        self.assertEqual(filtered.call_count, 1)

    @patch("core.printer_gcode_submission._creality_started_file")
    @patch("core.printer_connectivity.poll_connection")
    def test_native_confirmation_poll_is_read_only_and_not_a_retry(self, poll, matches):
        from core.printer_gcode_submission import _verify_creality_start_now
        printer = connection("creality_local")
        matches.return_value = True
        self.assertTrue(_verify_creality_start_now(printer, "3DBenchy.gcode"))
        poll.assert_called_once_with(printer)
        matches.assert_called_once_with(poll.return_value, "3DBenchy.gcode")
        poll.side_effect = RuntimeError("printer temporarily unavailable")
        self.assertFalse(_verify_creality_start_now(printer, "3DBenchy.gcode"))

    def test_printer_transfer_name_preserves_original_before_suffix(self):
        import uuid
        token = uuid.UUID("c1609a3c-d200-4b12-aabb-112233445566")
        self.assertEqual(_printer_transfer_name("ghost.gcode", token),
                         "ghost-mv-c1609a3cd200.gcode")
        self.assertEqual(_printer_transfer_name("my part.gcode", token),
                         "my_part-mv-c1609a3cd200.gcode")
        self.assertEqual(_printer_transfer_name("ghost.gcode", token),
                         _printer_transfer_name("ghost.gcode", token))

    @patch("core.printer_gcode_submission.PrinterConnection.objects.filter")
    def test_native_k2_can_use_same_printer_moonraker_original_mapping(self, filtered):
        native = connection("creality_local")
        native.printer = SimpleNamespace(model="K2", catalog_model=None)
        native.printer_id = "printer-one"
        native.last_snapshot["source_metadata"] = {"cfs_connected": True}
        native.last_snapshot["materials"] = [{
            "system": "creality_cfs", "unit_index": 0, "slot_index": 2,
            "material": "PLA", "color_hex": "#ffffff"
        }]
        moon = connection("moonraker")
        moon.controls_enabled = True
        filtered.return_value.order_by.return_value = [moon]
        caps = availability(native)
        self.assertTrue(caps["can_start_mapped_cfs"])
        self.assertTrue(caps["can_start_sliced_mapping"])
        self.assertFalse(caps["can_start"])
        _require_action_ready(native, "print", use_sliced_cfs=True)
        moon.controls_enabled = False
        self.assertFalse(availability(native)["can_start_sliced_mapping"])

    @patch("core.printer_gcode_submission.PrinterConnection.objects.filter")
    def test_original_mapping_option_persists_when_printer_is_busy(self, filtered):
        native = connection("creality_local")
        native.printer = SimpleNamespace(model="K2", catalog_model=None)
        native.printer_id = "printer-one"
        native.last_snapshot["source_metadata"] = {"cfs_connected": True}
        native.last_snapshot["materials"] = [{
            "system": "creality_cfs", "unit_index": 0, "slot_index": 2,
            "material": "PLA", "color_hex": "#ffffff",
        }]
        moon = connection("moonraker")
        moon.controls_enabled = True
        filtered.return_value.order_by.return_value = [moon]
        filtered.return_value.exists.return_value = True
        native.last_snapshot["state"] = "printing"
        caps = availability(native)
        self.assertTrue(caps["supports_original_mapping"])
        self.assertFalse(caps["can_start_sliced_mapping"])
        with self.assertRaises(GcodeSubmissionError):
            _require_action_ready(native, "print", use_sliced_cfs=True)

    def test_creality_k1_native_start_uses_stock_k1_file_root(self):
        import asyncio
        import json
        from core.creality_gcode import _stock_data_root, _start_single_spool
        k1 = connection("creality_local")
        k1.printer = SimpleNamespace(model="K1", catalog_model=None)
        k2 = connection("creality_local")
        k2.printer = SimpleNamespace(model="K2", catalog_model=None)
        self.assertEqual(_stock_data_root(k1), "/usr/data")
        self.assertEqual(_stock_data_root(k2), "/mnt/UDISK")
        k1.printer.model = "K1 Max"
        self.assertEqual(_stock_data_root(k1), "/usr/data")
        k1.printer.model = "Unrecognised Creality"
        with self.assertRaises(CrealityGcodeError):
            _stock_data_root(k1)
        k1.printer.model = "K1"
        with patch("core.creality_gcode.websockets.connect") as connect:
            ws = AsyncMock()
            connect.return_value.__aenter__.return_value = ws
            asyncio.run(_start_single_spool(
                "ws://printer.local:9999", "ghost.gcode", _stock_data_root(k1),
            ))
            sent = json.loads(ws.send.await_args.args[0])
            self.assertEqual(sent["params"]["opGcodeFile"],
                             "printprt:/usr/data/printer_data/gcodes/ghost.gcode")

    def test_k1_gcode_files_current_firmware_reply(self):
        packet = {"params": {"retGcodeFileInfo2": [
            {"name": "Benchy.gcode", "path": "/usr/data/printer_data/gcodes/Benchy.gcode",
             "file_size": 42132, "material": "PLA"},
            {"path": "/usr/data/printer_data/gcodes/folder/Part.gcode", "file_size": 2048},
            {"path": "/usr/data/printer_data/gcodes/../bad.gcode"},
            {"path": "/etc/passwd"},
        ]}}
        rows = _parse_file_list(packet)
        self.assertEqual([row["path"] for row in rows], ["Benchy.gcode", "folder/Part.gcode"])
        self.assertEqual(rows[0]["size_bytes"], 42132)
        self.assertEqual(rows[1]["size_bytes"], 2048)

    def test_k1_archived_retgcodefileinfo2_shape_and_path_authority(self):
        # Reduced fixture from the K1 1.3.5.22 web-server.log; no private
        # identifiers or full diagnostic payloads are stored in the repository.
        packet = {"retGcodeFileInfo2": [
            {"custom_types": 1, "type": 8, "name": "sample_PLA_6m42s.gcode",
             "path": "/usr/data/printer_data/gcodes/sample_PLA_6m42s.gcode",
             "file_size": 166268, "create_time": 1791677919,
             "material": "PLA", "software": "OrcaSlicer"},
            {"name": "benign.gcode", "path": "/etc/unsafe.gcode",
             "file_size": 512},
            {"name": "unknown.gcode", "path": "../escape.gcode",
             "file_size": 100},
            {"name": "invalid-size.gcode",
             "path": "/usr/data/printer_data/gcodes/invalid-size.gcode",
             "file_size": -2},
        ]}
        rows = _parse_file_list(packet)
        self.assertEqual([item["path"] for item in rows],
                         ["sample_PLA_6m42s.gcode", "invalid-size.gcode"])
        self.assertEqual([item["size_bytes"] for item in rows], [166268, None])

    @patch("core.creality_gcode.websockets.connect")
    def test_k1_file_browser_uses_plain_websocket_and_ignores_telemetry(self, connect):
        import asyncio
        import json
        from core.creality_gcode import _list_files
        session = AsyncMock()
        session.recv.side_effect = [
            json.dumps({"nozzleTemp": "21.4", "bedTemp0": "20.2"}),
            json.dumps({"ModeCode": "heart_beat"}),
            json.dumps({"params": {"retGcodeFileInfo2": [{
                "name": "existing.gcode",
                "path": "/usr/data/printer_data/gcodes/existing.gcode",
                "file_size": 4096,
            }]}}),
        ]
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=session)
        context.__aexit__ = AsyncMock(return_value=None)
        connect.return_value = context
        rows = asyncio.run(_list_files("ws://k1.local:9999", stock_k1=True))
        self.assertEqual(rows[0]["path"], "existing.gcode")
        self.assertEqual(rows[0]["size_bytes"], 4096)
        self.assertNotIn("subprotocols", connect.call_args.kwargs)
        self.assertEqual(json.loads(session.send.await_args_list[0].args[0]),
                         {"method": "get", "params": {"reqGcodeFile": 1}})
        self.assertEqual(session.send.await_args_list[1].args[0], "ok")

    @patch("core.creality_gcode.websockets.connect")
    def test_k2_file_browser_preserves_existing_subprotocol(self, connect):
        import asyncio
        import json
        from core.creality_gcode import _list_files
        session = AsyncMock()
        session.recv.return_value = json.dumps({"retGcodeFileInfo2": []})
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=session)
        context.__aexit__ = AsyncMock(return_value=None)
        connect.return_value = context
        self.assertEqual(asyncio.run(_list_files("ws://k2.local:9999")), [])
        self.assertEqual(connect.call_args.kwargs["subprotocols"], ["wsslicer"])

    def test_k1_legacy_packed_file_list_reply(self):
        packet = {"retGcodeFileInfo": {
            "totalNum": 3,
            "fileInfo": (
                "/usr/data/printer_data/gcodes:Benchy.gcode:2048:0.2:123:900:/tmp/thumb;"
                "/usr/data/printer_data/gcodes:folder/Part.gcode:1024:0.2:123:200:/tmp/thumb;"
                "/etc:evil.gcode:1:0.2:123:200:/tmp/thumb;"
            ),
        }}
        rows = _parse_file_list(packet)
        self.assertEqual([row["path"] for row in rows], ["Benchy.gcode", "folder/Part.gcode"])
        self.assertEqual([row["size_bytes"] for row in rows], [2048, 1024])
        self.assertEqual(_parse_file_list({"params": {"retGcodeFileInfo2": []}}), [])

    def test_k1_file_list_does_not_accept_foreign_absolute_paths(self):
        for path in ("/etc/thing.gcode", "/home/root/thing.gcode",
                     "/usr/data/printer_data/gcodes/../evil.gcode",
                     "../evil.gcode"):
            self.assertIsNone(_safe_printer_file(path), path)
        self.assertEqual(_safe_printer_file("/usr/data/printer_data/gcodes/benchy.gcode"), "benchy.gcode")

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
        self.assertTrue(creality["can_start"])    # Mock connection has no K2 model or CFS evidence

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

    @patch("core.creality_gcode.list_files")
    @patch("core.printer_gcode_submission._get_json")
    @patch("core.printer_gcode_submission.PrinterConnection.objects.filter")
    def test_creality_browse_falls_back_to_native_if_moonraker_listing_fails(self, filtered, get_json, native):
        printer = connection("creality_local")
        printer.printer_id = "same-printer"
        moon = connection("moonraker")
        filtered.return_value.order_by.return_value = [moon]
        get_json.side_effect = GcodeSubmissionError("Moonraker temporarily unavailable.", 502)
        native.return_value = [{"path": "k1_file.gcode", "size_bytes": 123}]
        rows = list_printer_gcodes(printer)
        self.assertEqual(rows[0]["path"], "k1_file.gcode")
        native.assert_called_once_with(printer)
        self.assertEqual(filtered.call_args.kwargs["printer_id"], "same-printer")

    @patch("core.creality_gcode.list_files")
    @patch("core.printer_gcode_submission._get_json")
    @patch("core.printer_gcode_submission.PrinterConnection.objects.filter")
    def test_empty_moonraker_listing_is_not_treated_as_failure(self, filtered, get_json, native):
        printer = connection("creality_local")
        printer.printer_id = "same-printer"
        filtered.return_value.order_by.return_value = [connection("moonraker")]
        get_json.return_value = []
        self.assertEqual(list_printer_gcodes(printer), [])
        native.assert_not_called()

    @patch("core.creality_gcode.list_files")
    @patch("core.printer_gcode_submission._get_json")
    @patch("core.printer_gcode_submission.PrinterConnection.objects.filter")
    def test_both_creality_listing_methods_fail_with_clear_error(self, filtered, get_json, native):
        printer = connection("creality_local")
        printer.printer_id = "same-printer"
        filtered.return_value.order_by.return_value = [connection("moonraker")]
        get_json.side_effect = GcodeSubmissionError("Moonraker timeout", 502)
        native.side_effect = CrealityGcodeError("Creality WS listing timeout")
        with self.assertRaisesRegex(GcodeSubmissionError, "No configured printer file-listing"):
            list_printer_gcodes(printer)
        native.assert_called_once_with(printer)

    def test_every_browsable_adapter_has_explicit_listing_handler(self):
        from core.printer_gcode_submission import BROWSE_ADAPTERS, _listing_handler
        for adapter in BROWSE_ADAPTERS:
            with self.subTest(adapter=adapter):
                self.assertTrue(callable(_listing_handler(adapter)))

    @patch("core.printer_gcode_submission._get_json")
    def test_unknown_adapter_does_not_guess_moonraker_endpoint(self, get_json):
        with self.assertRaisesRegex(GcodeSubmissionError, "no supported file listing protocol"):
            list_printer_gcodes(connection("anycubic"))
        get_json.assert_not_called()

    @patch("core.printer_gcode_submission._get_json")
    def test_moonraker_compatible_manufacturer_adapters_share_file_api(self, get_json):
        get_json.return_value = [{"path": "folder/part.gcode", "size": 1024}]
        for adapter in ("moonraker", "elegoo", "qidi", "sovol", "snapmaker", "voron"):
            with self.subTest(adapter=adapter):
                rows = list_printer_gcodes(connection(adapter))
                self.assertEqual(rows[0]["path"], "folder/part.gcode")
                self.assertEqual(rows[0]["size_bytes"], 1024)
                self.assertEqual(get_json.call_args.args[1], "/server/files/list")

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

    def test_creality_native_start_requires_idle_no_cfs_not_legacy_opt_in(self):
        cc = connection("creality_local")
        cc.printer = SimpleNamespace(model="K1", catalog_model=None)
        # Native file starts use the normal explicit confirmation flow.
        # Old experimental configuration flags neither enable nor block it.
        cc.config["gcode_submission_enabled"] = False
        cc.config["creality_single_spool_start_enabled"] = False
        cc.last_snapshot["source_metadata"] = {"cfs_connected": False}
        self.assertTrue(availability(cc)["can_start"])
        _require_action_ready(cc, "print")
        cc.config["creality_single_spool_start_enabled"] = True
        self.assertTrue(availability(cc)["can_start"])
        cc.last_snapshot["source_metadata"] = {"cfs_connected": True}
        self.assertFalse(availability(cc)["can_start"])
        cc.last_snapshot["source_metadata"] = {"cfs_connected": False}
        cc.last_snapshot["state"] = "printing"
        self.assertFalse(availability(cc)["can_start"])

    def test_k2_detection_and_post_print_terminal_states(self):
        from core.printer_gcode_submission import _is_k2, _ready_for_start
        moon = connection("moonraker")
        moon.printer = SimpleNamespace(model="K2", catalog_model=None)
        self.assertTrue(_is_k2(moon))
        moon.printer.model = "Creality K2 Combo"
        self.assertTrue(_is_k2(moon))
        moon.printer.model = "K1 Max"
        self.assertFalse(_is_k2(moon))
        for state in ("idle", "complete", "cancelled"):
            self.assertTrue(_ready_for_start({"state": state}))
        for state in ("printing", "paused", "processing", "error", "unknown"):
            self.assertFalse(_ready_for_start({"state": state}))

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
    def test_one_used_slicer_tool_maps_without_assigning_three_unused_profiles(self, filtered):
        moon = connection("moonraker")
        moon.printer = SimpleNamespace(model="K2", manufacturer="Creality", catalog_model=None)
        moon.printer_id = "printer-one"
        native = connection("creality_local")
        native.last_snapshot["source_metadata"] = {"cfs_connected": True}
        native.last_snapshot["materials"] = [{
            "system": "creality_cfs", "unit_index": 0, "slot_index": 0,
            "material": "PLA", "color_hex": "#000000",
        }]
        filtered.return_value.order_by.return_value = [native]
        mapping = _mapped_cfs_entries(moon, [
            {"tool_index": 2, "material": "PLA", "color_hex": "#ffffff"}
        ], [{"tool_index": 2, "slot_label": "1A"}])
        self.assertEqual(mapping, [{
            "id": "T1C", "type": "PLA", "color": "#000000",
            "boxId": 1, "materialId": 0,
        }])
        with self.assertRaises(GcodeSubmissionError):
            _mapped_cfs_entries(moon, [
                {"tool_index": 2, "material": "PETG"}
            ], [{"tool_index": 2, "slot_label": "1A"}])

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
        with patch("core.creality_gcode.list_files", return_value=[
            {"path": "mv_ghost.gcode", "size_bytes": 1200}
        ]) as native_list:
            self.assertEqual(
                _verify_creality_upload(native, "mv_ghost.gcode", 1200)["size_bytes"], 1200
            )
            native_list.assert_called_once_with(native)

    @patch("time.sleep")
    @patch("core.printer_gcode_submission.PrinterConnection.objects.filter")
    @patch("core.creality_gcode.list_files")
    def test_native_creality_upload_needs_exact_file_and_size(self, browse, filtered, pause):
        native = connection("creality_local")
        native.printer_id = "one-printer"
        filtered.return_value.order_by.return_value = []
        for rows in (
            [], [{"path": "mv_ghost.gcode", "size_bytes": None}],
            [{"path": "mv_ghost.gcode", "size_bytes": 1199}],
            [{"path": "other.gcode", "size_bytes": 1200}],
            [{"path": "mv_ghost.gcode", "size_bytes": 1200},
             {"path": "mv_ghost.gcode", "size_bytes": 1200}],
        ):
            with self.subTest(rows=rows):
                browse.return_value = rows
                with self.assertRaises(GcodeSubmissionError):
                    _verify_creality_upload(native, "mv_ghost.gcode", 1200)
        browse.side_effect = CrealityGcodeError("Unrecognised reply")
        with self.assertRaises(GcodeSubmissionError):
            _verify_creality_upload(native, "mv_ghost.gcode", 1200)

    @patch("time.sleep")
    @patch("core.printer_gcode_submission.PrinterConnection.objects.filter")
    @patch("core.creality_gcode.list_files")
    def test_native_creality_eventual_consistency_uses_read_only_probes(self, browse, filtered, pause):
        native = connection("creality_local")
        native.printer_id = "one-printer"
        filtered.return_value.order_by.return_value = []
        browse.side_effect = [
            [],
            [{"path": "mv_ghost.gcode", "size_bytes": None}],
            [{"path": "mv_ghost.gcode", "size_bytes": 1200}],
        ]
        result = _verify_creality_upload(native, "mv_ghost.gcode", 1200)
        self.assertEqual(result["size_bytes"], 1200)
        self.assertEqual(browse.call_count, 3)
        self.assertEqual(pause.call_count, 2)

    @patch("time.sleep")
    @patch("core.printer_gcode_submission.PrinterConnection.objects.filter")
    @patch("core.creality_gcode.list_files")
    def test_native_creality_unverified_upload_reports_safe_reason(self, browse, filtered, pause):
        native = connection("creality_local")
        native.printer_id = "one-printer"
        filtered.return_value.order_by.return_value = []
        browse.return_value = [{"path": "mv_ghost.gcode", "size_bytes": None}]
        with self.assertRaisesRegex(GcodeSubmissionError, "size-not-reported") as caught:
            _verify_creality_upload(native, "mv_ghost.gcode", 1200)
        self.assertNotIn("mv_ghost.gcode", str(caught.exception))
        self.assertEqual(browse.call_count, 3)

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

    def test_stock_k1_single_spool_uses_plain_opgcodefile(self):
        from core.creality_gcode import _single_spool_command
        command = _single_spool_command("Daring_Wolt_PLA_6m42s.gcode", "/usr/data")
        self.assertEqual(command, {
            "method": "set",
            "params": {
                "opGcodeFile": "printprt:/usr/data/printer_data/gcodes/Daring_Wolt_PLA_6m42s.gcode",
            },
        })
        self.assertNotIn("enableSelfTest", command["params"])
        with self.assertRaises(CrealityGcodeError):
            _single_spool_command("../bad.gcode", "/usr/data")
        with self.assertRaises(CrealityGcodeError):
            _single_spool_command("good.gcode", "/invalid-native-root")

    @patch("core.creality_gcode.websockets.connect")
    def test_stock_k1_start_sends_once_and_tolerates_remote_close(self, connect):
        import asyncio
        import json
        from core.creality_gcode import _start_single_spool
        session = AsyncMock()
        session.recv.side_effect = EOFError("printer closed after accepting start")
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=session)
        context.__aexit__ = AsyncMock(return_value=None)
        connect.return_value = context
        asyncio.run(_start_single_spool("ws://k1.local:9999", "3DBenchy.gcode", "/usr/data"))
        session.send.assert_awaited_once()
        payload = json.loads(session.send.await_args.args[0])
        self.assertEqual(payload["params"], {
            "opGcodeFile": "printprt:/usr/data/printer_data/gcodes/3DBenchy.gcode",
        })
        session.recv.assert_awaited_once()

    @patch("core.creality_gcode.websockets.connect")
    def test_stock_k1_start_never_retries_after_read_timeout(self, connect):
        import asyncio
        from core.creality_gcode import _start_single_spool
        session = AsyncMock()
        session.recv.side_effect = asyncio.TimeoutError
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=session)
        context.__aexit__ = AsyncMock(return_value=None)
        connect.return_value = context
        asyncio.run(_start_single_spool("ws://k1.local:9999", "3DBenchy.gcode", "/usr/data"))
        session.send.assert_awaited_once()

    @patch("core.creality_gcode.websockets.connect")
    def test_stock_k1_start_uses_no_k2_subprotocol(self, connect):
        import asyncio
        from core.creality_gcode import _start_single_spool
        session = AsyncMock()
        session.recv.side_effect = EOFError("K1 closes after dispatch")
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=session)
        context.__aexit__ = AsyncMock(return_value=None)
        connect.return_value = context
        asyncio.run(_start_single_spool("ws://k1.local:9999", "ghost.gcode", "/usr/data"))
        self.assertNotIn("subprotocols", connect.call_args.kwargs)
        session.send.assert_awaited_once()

    @patch("core.creality_gcode.websockets.connect")
    def test_stock_k1_acknowledges_heartbeat_without_restarting_print(self, connect):
        import asyncio
        import json
        from core.creality_gcode import _start_single_spool
        session = AsyncMock()
        session.recv.side_effect = [
            json.dumps({"ModeCode": "heart_beat"}),
            EOFError("printer closed"),
        ]
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=session)
        context.__aexit__ = AsyncMock(return_value=None)
        connect.return_value = context
        asyncio.run(_start_single_spool("ws://k1.local:9999", "ghost.gcode", "/usr/data"))
        self.assertEqual(session.send.await_count, 2)
        sent = [call.args[0] for call in session.send.await_args_list]
        self.assertEqual(json.loads(sent[0])["params"], {
            "opGcodeFile": "printprt:/usr/data/printer_data/gcodes/ghost.gcode",
        })
        self.assertEqual(sent[1], "ok")

    @patch("core.creality_gcode.websockets.connect")
    def test_stock_k1_does_not_retry_start_on_unexpected_response(self, connect):
        import asyncio
        from core.creality_gcode import _start_single_spool
        session = AsyncMock()
        session.recv.return_value = '{"result":"unknown"}'
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=session)
        context.__aexit__ = AsyncMock(return_value=None)
        connect.return_value = context
        asyncio.run(_start_single_spool("ws://k1.local:9999", "ghost.gcode", "/usr/data"))
        session.send.assert_awaited_once()

    def test_creality_upload_target_is_same_host_no_credentials(self):
        printer = connection("creality_local")
        printer.endpoint_url = "ws://k2.local:9999"
        self.assertEqual(_http_root(printer), "http://k2.local:80")
        printer.endpoint_url = "ws://user:secret@k2.local:9999"
        with self.assertRaises(Exception):
            _http_root(printer)
