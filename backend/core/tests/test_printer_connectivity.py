from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.models import PrintJob, Printer, PrinterConnection
from core.tasks import live_printer_connections_tick
from core.live_print_jobs import sync_print_job_from_snapshot
from core.printer_connectivity import (
    PrinterConnectionError,
    adapter_catalogue,
    normalise_creality_endpoint,
    normalise_creality_snapshot,
    poll_connection,
    poll_moonraker,
    poll_octoprint,
)


class PrinterConnectivityAdapterTests(TestCase):
    def response(self, payload, status=200):
        result = Mock(status_code=status)
        result.json.return_value = payload
        return result

    @patch("core.printer_connectivity.requests.get")
    def test_moonraker_normalises_live_snapshot(self, get_mock):
        def side_effect(url, **kwargs):
            if url.endswith("/server/info"):
                return self.response({
                    "result": {
                        "klippy_state": "ready",
                        "moonraker_version": "0.9.3",
                        "warnings": ["Test warning"],
                    }
                })
            if "/printer/objects/query?" in url:
                return self.response({
                    "result": {
                        "status": {
                            "print_stats": {
                                "state": "printing",
                                "filename": "Benchy.gcode",
                                "print_duration": 300,
                                "info": {"current_layer": 42, "total_layer": 168},
                            },
                            "virtual_sdcard": {"progress": 0.25},
                            "display_status": {"progress": 0.25},
                            "extruder": {"temperature": 214.2, "target": 220},
                            "heater_bed": {"temperature": 59.8, "target": 60},
                        }
                    }
                })
            raise AssertionError(url)

        get_mock.side_effect = side_effect
        snapshot = poll_moonraker("http://moonraker.local:7125", {"api_key": "secret"})

        self.assertTrue(snapshot["online"])
        self.assertEqual(snapshot["state"], "printing")
        self.assertEqual(snapshot["job"]["file_name"], "Benchy.gcode")
        self.assertEqual(snapshot["job"]["progress"], 25.0)
        self.assertEqual(snapshot["job"]["elapsed_seconds"], 300)
        self.assertEqual(snapshot["job"]["remaining_seconds"], 900)
        self.assertEqual(snapshot["temperatures"]["tool0"]["actual_c"], 214.2)
        self.assertEqual(snapshot["temperatures"]["bed"]["target_c"], 60.0)
        self.assertEqual(snapshot["job"]["current_layer"], 42)
        self.assertEqual(snapshot["job"]["total_layers"], 168)
        self.assertEqual(snapshot["warnings"], ["Test warning"])
        self.assertEqual(snapshot["source_metadata"]["klippy_state"], "ready")
        self.assertTrue(all(call.kwargs["headers"]["X-Api-Key"] == "secret" for call in get_mock.call_args_list))

    def test_creality_endpoint_accepts_existing_host_field(self):
        self.assertEqual(
            normalise_creality_endpoint("192.168.1.34"),
            "ws://192.168.1.34:9999",
        )
        self.assertEqual(
            normalise_creality_endpoint("http://k2.local"),
            "ws://k2.local:9999",
        )
        self.assertEqual(
            normalise_creality_endpoint("ws://k2.local:19999"),
            "ws://k2.local:19999",
        )

    def test_creality_snapshot_normalises_k2_live_telemetry(self):
        snapshot = normalise_creality_snapshot({
            "connect": 1,
            "hostname": "K2-TEST",
            "model": "F012",
            "modelVersion": "printer sw ver:1.1.test;",
            "state": 1,
            "deviceState": 0,
            "printFileName": "/usr/data/printer_data/gcodes/Benchy.gcode",
            "printProgress": 37.5,
            "printJobTime": 600,
            "printLeftTime": 900,
            "layer": 42,
            "TotalLayer": 168,
            "nozzleTemp": "214.2",
            "targetNozzleTemp": 220,
            "bedTemp0": "59.8",
            "targetBedTemp0": 60,
            "boxTemp": 36,
            "targetBoxTemp": 40,
            "cfsConnect": 1,
            "webrtcSupport": 1,
            "video": 1,
            "curFeedratePct": 100,
            "curFlowratePct": 98,
            "modelFanPct": 40,
            "caseFanPct": 30,
            "auxiliaryFanPct": 50,
            "usedMaterialLength": 1234.5,
            "materialStatus": 0,
            "boxsInfo": {
                "materialBoxs": [{
                    "id": 1,
                    "type": 0,
                    "temp": 31,
                    "humidity": 34,
                    "materials": [{
                        "id": 2,
                        "vendor": "Creality",
                        "type": "PETG",
                        "name": "CR-PETG",
                        "rfid": "06001",
                        "color": "#0fa7c0c",
                        "minTemp": 220,
                        "maxTemp": 270,
                        "percent": 63,
                        "state": 2,
                        "selected": 1,
                    }],
                }],
            },
            "err": {"errcode": 0, "key": 0},
        })

        self.assertTrue(snapshot["online"])
        self.assertEqual(snapshot["state"], "printing")
        self.assertEqual(snapshot["job"]["file_name"], "Benchy.gcode")
        self.assertEqual(snapshot["job"]["progress"], 37.5)
        self.assertEqual(snapshot["job"]["elapsed_seconds"], 600)
        self.assertEqual(snapshot["job"]["remaining_seconds"], 900)
        self.assertEqual(snapshot["job"]["current_layer"], 42)
        self.assertEqual(snapshot["job"]["total_layers"], 168)
        self.assertEqual(snapshot["temperatures"]["tool0"]["actual_c"], 214.2)
        self.assertEqual(snapshot["temperatures"]["bed"]["target_c"], 60.0)
        self.assertEqual(snapshot["temperatures"]["chamber"]["actual_c"], 36.0)
        self.assertTrue(snapshot["source_metadata"]["cfs_connected"])
        self.assertTrue(snapshot["source_metadata"]["webrtc_support"])
        self.assertEqual(snapshot["source_metadata"]["cfs_loaded_slots"], 1)
        self.assertEqual(snapshot["materials"][0]["system"], "creality_cfs")
        self.assertEqual(snapshot["materials"][0]["slot_index"], 2)
        self.assertEqual(snapshot["materials"][0]["material"], "PETG")
        self.assertEqual(snapshot["materials"][0]["color_hex"], "#fa7c0c")
        self.assertEqual(snapshot["materials"][0]["remaining_percent"], 63.0)
        self.assertTrue(snapshot["materials"][0]["selected"])
        self.assertTrue(snapshot["materials"][0]["rfid_detected"])
        self.assertEqual(snapshot["materials"][0]["box_temperature_c"], 31.0)
        self.assertEqual(snapshot["materials"][0]["box_humidity_percent"], 34.0)
        self.assertEqual(snapshot["source_metadata"]["protocol"], "Creality LAN WebSocket :9999")

    def test_creality_snapshot_handles_pause_completion_stop_and_error(self):
        base = {
            "connect": 1,
            "printFileName": "part.gcode",
            "printProgress": 25,
            "nozzleTemp": 30,
            "err": {"errcode": 0},
        }
        self.assertEqual(
            normalise_creality_snapshot({**base, "state": 5})["state"],
            "paused",
        )
        self.assertEqual(
            normalise_creality_snapshot({**base, "state": 1, "printProgress": 100})["state"],
            "complete",
        )
        self.assertEqual(
            normalise_creality_snapshot({**base, "state": 4})["state"],
            "cancelled",
        )
        errored = normalise_creality_snapshot({
            **base,
            "state": 1,
            "err": {"errcode": 500, "key": 121},
        })
        self.assertEqual(errored["state"], "error")
        self.assertEqual(errored["source_metadata"]["activity_state"], "printing")
        self.assertEqual(errored["warnings"], ["Creality error 500 (key 121)"])

    @patch("core.printer_connectivity.requests.get")
    def test_octoprint_normalises_live_snapshot(self, get_mock):
        def side_effect(url, **kwargs):
            if url.endswith("/api/version"):
                return self.response({"api": "0.1", "server": "1.11.0", "text": "OctoPrint 1.11.0"})
            if url.endswith("/api/job"):
                return self.response({
                    "state": "Printing",
                    "job": {"file": {"display": "Gear.3mf"}},
                    "progress": {
                        "completion": 0.625,
                        "printTime": 600,
                        "printTimeLeft": 360,
                    },
                })
            if url.endswith("/api/printer"):
                return self.response({
                    "state": {"text": "Printing"},
                    "temperature": {
                        "tool0": {"actual": 205.5, "target": 210},
                        "bed": {"actual": 60.1, "target": 60},
                    },
                })
            raise AssertionError(url)

        get_mock.side_effect = side_effect
        snapshot = poll_octoprint("http://octoprint.local", {"api_key": "octo-key"})

        self.assertTrue(snapshot["online"])
        self.assertEqual(snapshot["state"], "printing")
        self.assertEqual(snapshot["job"]["file_name"], "Gear.3mf")
        self.assertEqual(snapshot["job"]["progress"], 62.5)
        self.assertEqual(snapshot["job"]["remaining_seconds"], 360)
        self.assertEqual(snapshot["temperatures"]["tool0"]["target_c"], 210.0)
        self.assertEqual(snapshot["source_metadata"]["server"], "1.11.0")

    def test_adapter_catalogue_marks_unvalidated_manufacturer_adapters_experimental(self):
        rows = {row["key"]: row for row in adapter_catalogue()}
        self.assertTrue(rows["moonraker"]["supported"])
        self.assertTrue(rows["octoprint"]["supported"])
        self.assertTrue(rows["creality_local"]["supported"])
        self.assertTrue(rows["creality_local"]["experimental"])
        self.assertTrue(rows["creality_local"]["local_first"])
        self.assertFalse(rows["bambu_local"]["supported"])
        self.assertTrue(rows["bambu_local"]["experimental"])
        self.assertTrue(rows["voron"]["experimental"])


class LivePrintJobMappingTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="live-job-owner",
            email="live-job@example.com",
            password="test-password",
        )
        self.printer = Printer.objects.create(
            owner=self.user,
            name="Live printer",
            model="Test",
        )
        self.moonraker = PrinterConnection.objects.create(
            printer=self.printer,
            adapter="moonraker",
            endpoint_url="http://printer.local:7125",
            status="connected",
        )

    def snapshot(self, state="printing", filename="part.gcode", progress=25, elapsed=300, remaining=900):
        return {
            "adapter": "moonraker",
            "online": True,
            "state": state,
            "state_label": state.title(),
            "job": {
                "file_name": filename,
                "progress": progress,
                "elapsed_seconds": elapsed,
                "remaining_seconds": remaining,
            },
            "temperatures": {},
            "warnings": [],
            "materials": [],
        }

    def test_printing_snapshot_creates_one_monitored_job(self):
        result = sync_print_job_from_snapshot(self.moonraker, self.snapshot())

        self.assertEqual(result["action"], "created")
        job = PrintJob.objects.get()
        self.assertEqual(job.status, "printing")
        self.assertEqual(job.printer_id, self.printer.id)
        self.assertEqual(job.estimated_minutes, 20)
        meta = job.settings["live_monitor"]
        self.assertEqual(meta["filename"], "part.gcode")
        self.assertEqual(meta["last_progress"], 25)
        self.assertEqual(meta["source"], "live_printer")
        self.assertEqual(meta["sources"][0]["adapter"], "moonraker")

    def test_second_adapter_converges_on_same_active_job(self):
        first = sync_print_job_from_snapshot(self.moonraker, self.snapshot())
        octoprint = PrinterConnection.objects.create(
            printer=self.printer,
            adapter="octoprint",
            endpoint_url="http://printer.local",
            status="connected",
        )

        second = sync_print_job_from_snapshot(
            octoprint,
            self.snapshot(progress=40, elapsed=480, remaining=720),
        )

        self.assertEqual(first["action"], "created")
        self.assertEqual(second["action"], "updated")
        self.assertEqual(PrintJob.objects.count(), 1)
        job = PrintJob.objects.get()
        self.assertEqual(len(job.settings["live_monitor"]["sources"]), 2)
        self.assertEqual(job.settings["live_monitor"]["last_progress"], 40)

    def test_provider_activity_state_prevents_stale_creality_error_from_failing_job(self):
        sync_print_job_from_snapshot(self.moonraker, self.snapshot())
        result = sync_print_job_from_snapshot(
            self.moonraker,
            {
                **self.snapshot(progress=50, elapsed=600, remaining=600),
                "state": "error",
                "source_metadata": {"activity_state": "printing"},
                "warnings": ["Creality error 500 (key 121)"],
            },
        )

        self.assertEqual(result["action"], "updated")
        job = PrintJob.objects.get()
        self.assertEqual(job.status, "printing")

    def test_terminal_snapshot_completes_active_job(self):
        sync_print_job_from_snapshot(self.moonraker, self.snapshot())
        result = sync_print_job_from_snapshot(
            self.moonraker,
            self.snapshot(state="complete", progress=100, elapsed=1200, remaining=0),
        )

        self.assertEqual(result["action"], "completed")
        job = PrintJob.objects.get()
        self.assertEqual(job.status, "success")
        self.assertEqual(job.actual_minutes, 20)
        self.assertEqual(job.settings["live_monitor"]["last_state"], "complete")

    def test_missing_filename_does_not_create_automatic_job(self):
        result = sync_print_job_from_snapshot(
            self.moonraker,
            self.snapshot(filename=""),
        )

        self.assertEqual(result["action"], "none")
        self.assertEqual(result["reason"], "missing-filename")
        self.assertFalse(PrintJob.objects.exists())

    def test_idle_snapshot_does_not_imply_success(self):
        sync_print_job_from_snapshot(self.moonraker, self.snapshot())
        result = sync_print_job_from_snapshot(
            self.moonraker,
            self.snapshot(state="idle", progress=None, elapsed=None, remaining=None),
        )

        self.assertEqual(result["action"], "none")
        job = PrintJob.objects.get()
        self.assertEqual(job.status, "printing")




class PrinterConnectivityApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser(
            username="printer-live-admin",
            email="printer-live@example.com",
            password="test-password",
        )
        self.other = User.objects.create_user(
            username="printer-live-other",
            email="other@example.com",
            password="test-password",
        )
        self.client.force_login(self.user)
        self.printer = Printer.objects.create(
            owner=self.user,
            name="Workshop Voron",
            model="Voron 2.4",
        )

    def test_create_live_connection_redacts_api_key_and_exposes_capabilities(self):
        response = self.client.post(
            f"/api/printing/printers/{self.printer.id}/connections/",
            data={
                "adapter": "moonraker",
                "endpoint_url": "http://192.168.1.44:7125/",
                "poll_interval_seconds": 20,
                "api_key": "moon-secret",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        item = response.json()["item"]
        self.assertEqual(item["adapter"], "moonraker")
        self.assertEqual(item["endpoint_url"], "http://192.168.1.44:7125")
        self.assertEqual(item["status"], "disconnected")
        self.assertTrue(item["supported"])
        self.assertTrue(item["local_first"])
        self.assertTrue(item["capabilities"]["job"])
        self.assertTrue(item["capabilities"]["pause"])
        self.assertTrue(item["config"]["api_key_configured"])
        self.assertNotIn("api_key", item["config"])

        connection = PrinterConnection.objects.get(printer=self.printer, adapter="moonraker")
        self.assertEqual(connection.config["api_key"], "moon-secret")

    def test_creality_connection_reuses_plain_printer_host_format(self):
        self.printer.printer_manufacturer = None
        self.printer.connection_host = "192.168.1.34"
        self.printer.save(update_fields=["connection_host", "updated_at"])

        response = self.client.post(
            f"/api/printing/printers/{self.printer.id}/connections/",
            data={
                "adapter": "creality_local",
                "poll_interval_seconds": 15,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        item = response.json()["item"]
        self.assertEqual(item["adapter"], "creality_local")
        self.assertEqual(item["endpoint_url"], "ws://192.168.1.34:9999")
        self.assertEqual(item["status"], "disconnected")
        self.assertTrue(item["supported"])
        self.assertTrue(item["experimental"])
        self.assertTrue(item["capabilities"]["materials"])

    def test_one_physical_printer_can_have_multiple_live_sources_without_duplication(self):
        for adapter, endpoint in [
            ("moonraker", "http://printer.local:7125"),
            ("octoprint", "http://printer.local"),
        ]:
            response = self.client.post(
                f"/api/printing/printers/{self.printer.id}/connections/",
                data={"adapter": adapter, "endpoint_url": endpoint},
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 201, response.content)

        overview = self.client.get("/api/printing/")
        self.assertEqual(overview.status_code, 200, overview.content)
        self.assertEqual(len(overview.json()["printers"]), 1)
        self.assertEqual(len(overview.json()["printers"][0]["live_connections"]), 2)

    def test_stale_connected_source_is_not_promoted_as_live_status(self):
        connection = PrinterConnection.objects.create(
            printer=self.printer,
            adapter="moonraker",
            endpoint_url="http://printer.local:7125",
            poll_interval_seconds=10,
            status="connected",
            last_checked_at=timezone.now() - timedelta(minutes=5),
            last_seen_at=timezone.now() - timedelta(minutes=5),
            last_snapshot={"state": "printing", "state_label": "Printing"},
        )

        response = self.client.get("/api/printing/")
        self.assertEqual(response.status_code, 200, response.content)
        printer = response.json()["printers"][0]
        self.assertIsNone(printer["live_status"])
        self.assertEqual(len(printer["live_connections"]), 1)
        self.assertTrue(printer["live_connections"][0]["stale"])
        self.assertEqual(printer["live_connections"][0]["status_label"], "Stale")

    def test_dashboard_exposes_compact_owner_scoped_live_printer_status(self):
        PrinterConnection.objects.create(
            printer=self.printer,
            adapter="creality_local",
            endpoint_url="ws://192.168.1.34:9999",
            poll_interval_seconds=30,
            status="connected",
            last_checked_at=timezone.now(),
            last_seen_at=timezone.now(),
            last_snapshot={
                "state": "printing",
                "state_label": "Printing",
                "job": {
                    "file_name": "benchy.gcode",
                    "progress": 42.5,
                    "remaining_seconds": 900,
                },
                "temperatures": {
                    "tool0": {"actual_c": 220, "target_c": 220},
                    "bed": {"actual_c": 60, "target_c": 60},
                },
                "warnings": [],
            },
        )
        foreign = Printer.objects.create(owner=self.other, name="Hidden printer", model="Other")
        PrinterConnection.objects.create(
            printer=foreign,
            adapter="moonraker",
            endpoint_url="http://other.local:7125",
            status="connected",
            last_checked_at=timezone.now(),
            last_seen_at=timezone.now(),
            last_snapshot={"state": "idle", "state_label": "Idle"},
        )

        response = self.client.get("/api/dashboard/")
        self.assertEqual(response.status_code, 200, response.content)
        live = response.json()["live_printers"]
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0]["id"], str(self.printer.id))
        self.assertEqual(live[0]["adapter"], "creality_local")
        self.assertEqual(live[0]["state"], "printing")
        self.assertEqual(live[0]["job"]["file_name"], "benchy.gcode")
        self.assertEqual(live[0]["job"]["progress"], 42.5)
        self.assertEqual(live[0]["temperatures"]["tool0"]["actual_c"], 220)

    def test_connection_endpoints_are_owner_scoped(self):
        foreign = Printer.objects.create(owner=self.other, name="Other printer", model="Other")
        connection = PrinterConnection.objects.create(
            printer=foreign,
            adapter="moonraker",
            endpoint_url="http://other.local:7125",
            status="disconnected",
        )
        response = self.client.get(f"/api/printing/printers/{foreign.id}/connections/")
        self.assertEqual(response.status_code, 404)
        delete = self.client.delete(
            f"/api/printing/printers/{foreign.id}/connections/{connection.id}/"
        )
        self.assertEqual(delete.status_code, 404)

    @patch("core.api_views.poll_connection")
    def test_refresh_returns_normalised_snapshot(self, poll_mock):
        connection = PrinterConnection.objects.create(
            printer=self.printer,
            adapter="moonraker",
            endpoint_url="http://printer.local:7125",
            status="disconnected",
        )
        snapshot = {
            "adapter": "moonraker",
            "online": True,
            "state": "idle",
            "state_label": "Idle",
            "job": {"file_name": "", "progress": None},
            "temperatures": {},
            "warnings": [],
            "materials": [],
            "captured_at": "2026-10-01T08:00:00+00:00",
        }

        def refresh(item):
            item.status = "connected"
            item.capabilities = {"job": True}
            item.last_snapshot = snapshot
            item.save()
            return snapshot

        poll_mock.side_effect = refresh
        response = self.client.post(
            f"/api/printing/printers/{self.printer.id}/connections/{connection.id}/refresh/"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["snapshot"]["state"], "idle")
        self.assertEqual(response.json()["item"]["status"], "connected")

    def test_unimplemented_adapter_fails_closed(self):
        connection = PrinterConnection.objects.create(
            printer=self.printer,
            adapter="bambu_local",
            endpoint_url="http://bambu.local",
            status="experimental",
        )
        with self.assertRaises(PrinterConnectionError):
            poll_connection(connection)


    @patch("core.tasks.live_printer_connection_poll_task.delay")
    def test_scheduler_queues_only_due_supported_connections(self, delay_mock):
        due = PrinterConnection.objects.create(
            printer=self.printer,
            adapter="moonraker",
            endpoint_url="http://printer.local:7125",
            poll_interval_seconds=30,
            status="connected",
            last_checked_at=timezone.now() - timedelta(seconds=45),
        )
        PrinterConnection.objects.create(
            printer=self.printer,
            adapter="octoprint",
            endpoint_url="http://printer.local",
            poll_interval_seconds=10,
            status="connecting",
            last_checked_at=timezone.now() - timedelta(seconds=45),
        )
        PrinterConnection.objects.create(
            printer=self.printer,
            adapter="bambu_local",
            endpoint_url="http://bambu.local",
            poll_interval_seconds=10,
            status="experimental",
        )

        result = live_printer_connections_tick()

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["queued"], ["moonraker"])
        delay_mock.assert_called_once_with(due.id)
        due.refresh_from_db()
        self.assertEqual(due.status, "connecting")
        self.assertIsNotNone(due.last_checked_at)
