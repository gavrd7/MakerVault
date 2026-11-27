import base64
import hashlib
import uuid
from unittest.mock import Mock, patch
from django.test import SimpleTestCase
from core.slicer_worker_client import SlicerWorkerError, run_remote_job, worker_settings


class SlicerWorkerClientTests(SimpleTestCase):
    @patch("core.slicer_worker_client._session")
    @patch("core.slicer_worker_client.worker_settings",
           return_value=("http://slicer-worker:8088", "x" * 40))
    def test_engine_neutral_native_timeout_is_validated_and_transported(
            self, settings, session):
        import json
        response = Mock()
        output = b"; test\\nG1 X1 Y1 E1\\n"
        response.status_code = 200
        response.headers = {"Content-Length": "500"}
        response.iter_content.return_value = [json.dumps({
            "status": "completed", "gcode": base64.b64encode(output).decode(),
            "bytes": len(output), "sha256": hashlib.sha256(output).hexdigest(),
        }).encode()]
        session.return_value.post.return_value = response
        self.assertEqual(run_remote_job(
            uuid.uuid4(), "orcaslicer", "2.5.0", b"model", b"machine",
            b"filament", b"process", native_timeout_seconds=1800), output)
        sent = json.loads(session.return_value.post.call_args.kwargs["data"])
        self.assertEqual(sent["slice_timeout_seconds"], 1800)
        self.assertEqual(session.return_value.post.call_args.kwargs["timeout"], (3, 1860))
        for invalid in (0, 10801, True, "1800"):
            with self.subTest(invalid=invalid), self.assertRaises(SlicerWorkerError):
                run_remote_job(
                    uuid.uuid4(), "orcaslicer", "2.5.0", b"model", b"machine",
                    b"filament", b"process", native_timeout_seconds=invalid)

    @patch("core.slicer_worker_client._session")
    @patch("core.slicer_worker_client.worker_settings",
           return_value=("http://slicer-worker:8088", "x" * 40))
    def test_creality_placed_stl_authenticates_raw_not_compressed_bytes(
            self, settings, session):
        import json
        import zlib
        output = b"; test\\nG1 X1 Y1 E1\\n"
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Length": "500"}
        response.iter_content.return_value = [json.dumps({
            "status": "completed", "gcode": base64.b64encode(output).decode(),
            "bytes": len(output), "sha256": hashlib.sha256(output).hexdigest(),
        }).encode()]
        session.return_value.post.return_value = response
        raw = b"verified placed model"
        self.assertEqual(run_remote_job(
            uuid.uuid4(), "crealityprint", "7.3.1", raw, b"printer",
            b"filament", b"process", creality_placed_stl=True), output)
        sent = json.loads(session.return_value.post.call_args.kwargs["data"])
        self.assertTrue(sent["creality_placed_stl"])
        self.assertEqual(zlib.decompress(base64.b64decode(sent["model"])), raw)
        self.assertEqual(sent["creality_model_raw_sha256"], hashlib.sha256(raw).hexdigest())

    def test_unconfigured_and_invalid_urls_are_rejected(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(SlicerWorkerError):
                worker_settings()
        with patch.dict("os.environ", {
            "MAKERVAULT_SLICER_WORKER_URL": "http://evil.test/?start=true",
            "MAKERVAULT_SLICER_WORKER_TOKEN": "x" * 40,
        }):
            with self.assertRaises(SlicerWorkerError):
                worker_settings()

    @patch("core.slicer_worker_client._session")
    @patch("core.slicer_worker_client.worker_settings",
           return_value=("http://slicer-worker:8088", "x" * 40))
    def test_creality_placed_stl_request_is_explicit_and_engine_scoped(
            self, settings, session):
        import json
        gcode = b";Creality placed plate test\\nG1 X1 Y1 E1\\n"
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Length": "300"}
        response.iter_content.return_value = [json.dumps({
            "status": "completed", "gcode": base64.b64encode(gcode).decode(),
            "bytes": len(gcode), "sha256": hashlib.sha256(gcode).hexdigest(),
        }).encode()]
        session.return_value.post.return_value = response
        output = run_remote_job(
            uuid.uuid4(), "crealityprint", "7.3.1",
            b"composite", b"printer", b"filament", b"process",
            creality_placed_stl=True)
        self.assertEqual(output, gcode)
        sent = json.loads(session.return_value.post.call_args.kwargs["data"])
        self.assertIs(sent["creality_placed_stl"], True)
        import zlib
        self.assertEqual(zlib.decompress(base64.b64decode(sent["model"])), b"composite")
        self.assertEqual(sent["creality_model_raw_sha256"], hashlib.sha256(b"composite").hexdigest())
        for engine in ("orcaslicer", "bambustudio", "prusaslicer"):
            with self.subTest(engine=engine), self.assertRaises(SlicerWorkerError):
                run_remote_job(uuid.uuid4(), engine, "7.3.1",
                               b"composite", b"printer", b"filament",
                               b"process", creality_placed_stl=True)

    @patch("core.slicer_worker_client._session")
    @patch("core.slicer_worker_client.worker_settings",
           return_value=("http://slicer-worker:8088", "x" * 40))
    def test_creality_native_code_visible_without_raw_engine_output(self, settings, session):
        import json
        response = Mock()
        response.status_code = 422
        response.headers = {"Content-Length": "300"}
        response.iter_content.return_value = [json.dumps({
            "stage": "running slicer engine",
            "reason": "creality-cli-validation-error",
            "cli_exit_code": 205,
            "raw_output": "/private/secret/appimage-command --token=NEVER_DISPLAY",
        }).encode()]
        session.return_value.post.return_value = response
        with self.assertRaises(SlicerWorkerError) as caught:
            run_remote_job(uuid.uuid4(), "crealityprint", "7.3.1",
                           b"model", b"printer", b"filament", b"process")
        message = str(caught.exception)
        self.assertIn("exit 205 (CLI_VALIDATE_ERROR (-51))", message)
        self.assertIn("embedded project configuration", message)
        self.assertNotIn("NEVER_DISPLAY", message)
        self.assertNotIn("/private", message)

    @patch("core.slicer_worker_client._session")
    @patch("core.slicer_worker_client.worker_settings",
           return_value=("http://slicer-worker:8088", "x" * 40))
    def test_creality_unknown_numeric_code_is_reported_without_inventing_cause(self, settings, session):
        import json
        response = Mock()
        response.status_code = 422
        response.headers = {"Content-Length": "250"}
        response.iter_content.return_value = [json.dumps({
            "stage": "running slicer engine",
            "reason": "creality-cli-exited",
            "cli_exit_code": 201,
        }).encode()]
        session.return_value.post.return_value = response
        with self.assertRaises(SlicerWorkerError) as caught:
            run_remote_job(uuid.uuid4(), "crealityprint", "7.3.1",
                           b"model", b"printer", b"filament", b"process")
        self.assertIn("exit 201 (native CLI failure)", str(caught.exception))

    @patch("core.slicer_worker_client._session")
    @patch("core.slicer_worker_client.worker_settings",
           return_value=("http://slicer-worker:8088", "x" * 40))
    def test_creality_multistl_worker_request_uses_explicit_one_based_tools(
            self, settings, session):
        import json
        from unittest.mock import Mock
        gcode = b"; offline two-tool fixture\\nT0\\nT1\\n"
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Length": "300"}
        response.iter_content.return_value = [json.dumps({
            "status": "completed", "gcode": base64.b64encode(gcode).decode(),
            "bytes": len(gcode), "sha256": hashlib.sha256(gcode).hexdigest(),
        }).encode()]
        session.return_value.post.return_value = response
        result = run_remote_job(
            uuid.uuid4(), "crealityprint", "7.3.1",
            b"first", b"printer", b"filament-0", b"process",
            filament_profiles=[b"filament-0", b"filament-1"],
            creality_model_stls=[b"first", b"second"],
            creality_tool_ids=[2, 1])
        self.assertEqual(result, gcode)
        sent = json.loads(session.return_value.post.call_args.kwargs["data"])
        self.assertEqual(sent["creality_tool_ids"], [2, 1])
        self.assertEqual(
            [base64.b64decode(raw) for raw in sent["creality_model_stls"]],
            [b"first", b"second"])
        with self.assertRaises(SlicerWorkerError):
            run_remote_job(
                uuid.uuid4(), "crealityprint", "7.3.1",
                b"first", b"printer", b"filament-0", b"process",
                filament_profiles=[b"filament-0", b"filament-1"],
                creality_model_stls=[b"first", b"second"],
                creality_tool_ids=[0, 1])

    @patch("core.slicer_worker_client._session")
    @patch("core.slicer_worker_client.worker_settings", return_value=("http://slicer-worker:8088", "x" * 40))
    def test_strict_authenticated_transfer_and_checksum(self, settings, session):
        gcode = b"; mock slicer output\nG1 X1 Y2 E1\n"
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Length": "300"}
        response.iter_content.return_value = [__import__("json").dumps({
            "status": "completed", "gcode": base64.b64encode(gcode).decode(),
            "bytes": len(gcode), "sha256": hashlib.sha256(gcode).hexdigest(),
        }).encode()]
        sender = Mock()
        sender.post.return_value = response
        session.return_value = sender
        result = run_remote_job(uuid.uuid4(), "prusaslicer", "2.9.7", b"stl", b"machine", b"filament", b"process")
        self.assertEqual(result, gcode)
        kwargs = sender.post.call_args.kwargs
        self.assertFalse(kwargs["allow_redirects"])
        self.assertTrue(kwargs["headers"]["Authorization"].startswith("Bearer "))
        self.assertEqual(kwargs["timeout"], (3, 900))
        result = run_remote_job(uuid.uuid4(), "orcaslicer", "2.9.7", b"stl", b"machine", b"filament", b"process")
        self.assertEqual(result, gcode)

    @patch("core.slicer_worker_client._session")
    @patch("core.slicer_worker_client.worker_settings",
           return_value=("http://slicer-worker:8088", "x" * 40))
    def test_worker_profile_rejection_has_specific_allowlisted_category(self, settings, session):
        import json
        response = Mock()
        response.status_code = 422
        response.headers = {"Content-Length": "115"}
        response.iter_content.return_value = [json.dumps({
            "error": "Slicing input or output was rejected.",
            "stage": "running slicer engine", "reason": "unsafe-profile-settings",
        }).encode()]
        session.return_value.post.return_value = response
        with self.assertRaisesRegex(SlicerWorkerError, "unsafe-profile-settings"):
            run_remote_job(uuid.uuid4(), "orcaslicer", "2.4.2",
                           b"model", b"printer", b"filament", b"process")


    @patch("core.slicer_worker_client._session")
    @patch("core.slicer_worker_client.worker_settings",
           return_value=("http://slicer-worker:8088", "x" * 40))
    def test_native_palette_is_encoded_in_order_without_changing_legacy_request(self, settings, session):
        import json
        response = Mock()
        response.status_code = 200
        gcode = b"T0\\nM83\\nG1 X1 E1\\nT1\\nG1 X2 E1\\n"
        payload = json.dumps({
            "status": "completed", "gcode": base64.b64encode(gcode).decode(),
            "bytes": len(gcode), "sha256": hashlib.sha256(gcode).hexdigest(),
        }).encode()
        response.headers = {"Content-Length": str(len(payload))}
        response.iter_content.return_value = [payload]
        session.return_value.post.return_value = response
        result = run_remote_job(uuid.uuid4(), "orcaslicer", "2.4.2",
                                b"3mf", b"printer", b"filament-a", b"process",
                                model_format="3mf",
                                filament_profiles=[b"filament-a", b"filament-b"])
        self.assertEqual(result, gcode)
        sent = json.loads(session.return_value.post.call_args.kwargs["data"])
        self.assertEqual([base64.b64decode(x) for x in sent["filament_profiles"]],
                         [b"filament-a", b"filament-b"])
        self.assertEqual(base64.b64decode(sent["filament_profile"]), b"filament-a")

    def test_invalid_or_unsynchronised_native_palette_is_rejected(self):
        for profiles, engine, model_format in (
            ([b"one"], "orcaslicer", "3mf"),
            ([b"one", b"two"], "orcaslicer", "stl"),
            ([b"one", b"two"], "crealityprint", "3mf"),
            ([b"other", b"two"], "orcaslicer", "3mf"),
            ([b"one", "two"], "orcaslicer", "3mf"),
        ):
            with self.subTest(profiles=profiles, engine=engine, model_format=model_format):
                with self.assertRaises(SlicerWorkerError):
                    run_remote_job(uuid.uuid4(), engine, "2.4.2",
                                   b"model", b"printer", b"one", b"process",
                                   model_format=model_format, filament_profiles=profiles)


    @patch("core.slicer_worker_client._session")
    @patch("core.slicer_worker_client.worker_settings",
           return_value=("http://slicer-worker:8088", "x" * 40))
    def test_offline_prusa_mmu_client_uses_distinct_gated_contract(self, settings, session):
        import json
        gcode = b"; authenticated offline MMU fixture\\nT0\\nT1\\n"
        response = Mock(status_code=200,headers={"Content-Length":"300"})
        response.iter_content.return_value=[json.dumps({
            "status":"completed","gcode":base64.b64encode(gcode).decode(),
            "bytes":len(gcode),"sha256":hashlib.sha256(gcode).hexdigest(),
        }).encode()]
        session.return_value.post.return_value=response
        result=run_remote_job(
            uuid.uuid4(),"prusaslicer","2.9.7",b"project",b"printer",
            b"filament",b"process",model_format="3mf",
            prusa_offline_mmu={"tools":(1,2),"tower":(55,150,0,250,210)})
        self.assertEqual(result,gcode)
        sent=json.loads(session.return_value.post.call_args.kwargs["data"])
        self.assertEqual(sent["prusa_offline_mmu"],
                         {"tools":[1,2],"tower":[55,150,0,250,210]})
        self.assertNotIn("filament_profiles",sent)
        # Model count is independent of the number of native material tools.
        repeated = [1, 2, 3, 4, 5] * 3
        run_remote_job(uuid.uuid4(), "prusaslicer", "2.9.7", b"project",
                       b"printer", b"filament", b"process", model_format="3mf",
                       prusa_offline_mmu={"tools": repeated, "tower": [55,150,0,250,210]})
        sent = json.loads(session.return_value.post.call_args.kwargs["data"])
        self.assertEqual(sent["prusa_offline_mmu"]["tools"], repeated)
        independent = list(range(1, 9)) * 2
        run_remote_job(uuid.uuid4(), "prusaslicer", "2.9.7", b"project",
                       b"printer", b"filament", b"process", model_format="3mf",
                       prusa_offline_xl={"tools": independent})
        sent = json.loads(session.return_value.post.call_args.kwargs["data"])
        self.assertEqual(sent["prusa_offline_xl"]["tools"], independent)
        for change in (
            {"engine":"orcaslicer"},
            {"version":"2.9.6"},
            {"model_format":"stl"},
            {"prusa_offline_mmu":{"tools":[1,2],"tower":[float("nan"),150,0,250,210]}},
            {"prusa_offline_mmu":{"tools":[1,True],"tower":[55,150,0,250,210]}},
            {"prusa_offline_mmu":{"tools":[1,2],"tower":[55,150,0,250,210],"cmd":"unsafe"}},
        ):
            with self.subTest(change=change),self.assertRaises(SlicerWorkerError):
                arguments=dict(engine="prusaslicer",version="2.9.7",
                               model_format="3mf",prusa_offline_mmu={
                                   "tools":[1,2],"tower":[55,150,0,250,210]})
                arguments.update(change)
                run_remote_job(uuid.uuid4(),arguments.pop("engine"),
                               arguments.pop("version"),
                               b"project",b"printer",b"filament",b"process",**arguments)

    @patch("core.slicer_worker_client._session")
    @patch("core.slicer_worker_client.worker_settings",
           return_value=("http://slicer-worker:8088", "x" * 40))
    def test_prusa_painted_contracts_reach_worker(self, settings, session):
        import json
        gcode = b"; authenticated painted fixture\nT0\nT1\n"
        response = Mock(status_code=200, headers={"Content-Length": "300"})
        response.iter_content.return_value = [json.dumps({
            "status": "completed", "gcode": base64.b64encode(gcode).decode(),
            "bytes": len(gcode), "sha256": hashlib.sha256(gcode).hexdigest(),
        }).encode()]
        session.return_value.post.return_value = response
        contracts = (
            ("prusa_offline_colour", {"tools": [1, 2], "tower": [55,150,0,250,210]}),
            ("prusa_offline_xl_colour", {"tool": 4}),
        )
        for field, metadata in contracts:
            with self.subTest(field=field):
                self.assertEqual(run_remote_job(
                    uuid.uuid4(), "prusaslicer", "2.9.7", b"project",
                    b"printer", b"filament", b"process", model_format="3mf",
                    **{field: metadata}), gcode)
                sent = json.loads(session.return_value.post.call_args.kwargs["data"])
                self.assertEqual(sent[field], metadata)
        with self.assertRaises(SlicerWorkerError):
            run_remote_job(uuid.uuid4(), "prusaslicer", "2.9.7", b"project",
                           b"printer", b"filament", b"process", model_format="3mf",
                           prusa_offline_colour=contracts[0][1],
                           prusa_offline_xl_colour=contracts[1][1])

    def test_dangerous_engine_or_invalid_inputs_are_rejected_before_transport(self):
        with self.assertRaises(SlicerWorkerError):
            run_remote_job(uuid.uuid4(), "/bin/sh", "1", b"stl", b"p", b"f", b"process")
        with self.assertRaises(SlicerWorkerError):
            run_remote_job("not-uuid", "prusaslicer", "2.9.7", b"stl", b"p", b"f", b"process")

    @patch("core.slicer_worker_client._session")
    @patch("core.slicer_worker_client.worker_settings",
           return_value=("http://slicer-worker:8088", "x" * 40))
    def test_worker_rejection_exposes_only_allowlisted_stage_and_reason(self, settings, session):
        response = Mock()
        response.status_code = 422
        response.headers = {"Content-Length": "120"}
        response.iter_content.return_value = [__import__("json").dumps({
            "stage": "running slicer engine", "reason": "engine-exited",
            "error": "untrusted private data should never appear",
        }).encode()]
        session.return_value.post.return_value = response
        with self.assertRaises(SlicerWorkerError) as caught:
            run_remote_job(uuid.uuid4(), "orcaslicer", "2.4.2",
                           b"model", b"printer", b"filament", b"process")
        self.assertIn("without a recognised diagnostic", str(caught.exception))
        self.assertIn("engine-exited", str(caught.exception))
        self.assertNotIn("untrusted private data", str(caught.exception))

    @patch("core.slicer_worker_client._session")
    @patch("core.slicer_worker_client.worker_settings",
           return_value=("http://slicer-worker:8088", "x" * 40))
    def test_generic_worker_validation_error_keeps_safe_stage(self, settings, session):
        import json
        for stage in ("validating model and profile payloads",
                      "running slicer engine",
                      "validating generated G-code"):
            with self.subTest(stage=stage):
                response = Mock()
                response.status_code = 422
                payload = json.dumps({
                    "stage": stage, "reason": "validation-error",
                    "error": "PRIVATE_MACHINE_MACRO",
                }).encode()
                response.headers = {"Content-Length": str(len(payload))}
                response.iter_content.return_value = [payload]
                session.return_value.post.return_value = response
                with self.assertRaises(SlicerWorkerError) as caught:
                    run_remote_job(uuid.uuid4(), "crealityprint", "7.3.1",
                                   b"model", b"printer", b"filament", b"process")
                self.assertIn("Stage: " + stage, str(caught.exception))
                self.assertIn("[validation-error]", str(caught.exception))
                self.assertNotIn("PRIVATE_MACHINE_MACRO", str(caught.exception))

    @patch("core.slicer_worker_client._session")
    @patch("core.slicer_worker_client.worker_settings",
           return_value=("http://slicer-worker:8088", "x" * 40))
    def test_orca_exit_codes_are_translated_not_lost(self, settings, session):
        import json
        for reason, expected in (
            ("cli-validation-exit-238", "settings"),
            ("cli-validation-exit-239", "process preset"),
            ("native-project-settings-invalid", "out-of-range"),
            ("native-profile-load-failed", "native printer"),
        ):
            with self.subTest(reason=reason):
                response = Mock()
                response.status_code = 422
                payload = json.dumps({
                    "stage": "running slicer engine", "reason": reason,
                    "error": "secret/private/model/path",
                }).encode()
                response.headers = {"Content-Length": str(len(payload))}
                response.iter_content.return_value = [payload]
                session.return_value.post.return_value = response
                with self.assertRaises(SlicerWorkerError) as caught:
                    run_remote_job(uuid.uuid4(), "orcaslicer", "2.4.2",
                                   b"model", b"printer", b"filament", b"process")
                self.assertIn(expected, str(caught.exception))
                self.assertIn("[" + reason + "]", str(caught.exception))
                self.assertNotIn("secret/private", str(caught.exception))

    @patch("core.slicer_worker_client._session")
    @patch("core.slicer_worker_client.worker_settings",
           return_value=("http://slicer-worker:8088", "x" * 40))
    def test_native_validation_reports_safe_setting_identifiers(self, settings, session):
        import json
        response = Mock()
        response.status_code = 422
        payload = json.dumps({
            "stage": "running slicer engine",
            "reason": "native-project-settings-invalid",
            "setting_keys": ["retraction_distances_when_cut", "api_key",
                             "/private/file", "wall_loops"],
            "error": "private original settings and filenames",
        }).encode()
        response.headers = {"Content-Length": str(len(payload))}
        response.iter_content.return_value = [payload]
        session.return_value.post.return_value = response
        with self.assertRaises(SlicerWorkerError) as caught:
            run_remote_job(uuid.uuid4(), "orcaslicer", "2.5.0",
                           b"model", b"printer", b"filament", b"process")
        message = str(caught.exception)
        self.assertIn("retraction_distances_when_cut", message)
        self.assertIn("wall_loops", message)
        self.assertNotIn("api_key", message)
        self.assertNotIn("/private/file", message)
        self.assertNotIn("private original", message)

    @patch("core.slicer_worker_client._session")
    @patch("core.slicer_worker_client.worker_settings",
           return_value=("http://slicer-worker:8088", "x" * 40))
    def test_unknown_reason_does_not_leak_raw_diagnostics(self, settings, session):
        import json
        response = Mock()
        response.status_code = 422
        payload = json.dumps({"reason": "secret/private/path", "error": "password=secret"}).encode()
        response.headers = {"Content-Length": str(len(payload))}
        response.iter_content.return_value = [payload]
        session.return_value.post.return_value = response
        with self.assertRaises(SlicerWorkerError) as caught:
            run_remote_job(uuid.uuid4(), "orcaslicer", "2.4.2",
                           b"model", b"printer", b"filament", b"process")
        self.assertIn("rejected the job", str(caught.exception))
        self.assertNotIn("password", str(caught.exception))
        self.assertNotIn("secret/private", str(caught.exception))


    def test_bambu_engine_failure_explains_bambu_not_orca(self):
        from core.slicer_failure_messages import explain_worker_failure
        text = explain_worker_failure("bambu-cli-exited", 422)
        self.assertIn("Bambu Studio", text)
        self.assertNotIn("OrcaSlicer", text)
        abort = explain_worker_failure("bambu-cli-aborted", 422)
        self.assertIn("SIGABRT", abort)
        self.assertIn("Bambu Studio", abort)
        self.assertNotIn("OrcaSlicer", abort)
        runtime = explain_worker_failure("bambu-runtime-exit-126", 422)
        self.assertIn("exit 126", runtime)
        self.assertIn("runtime", runtime)
        self.assertNotIn("OrcaSlicer", runtime)
        self.assertIn("selected slicer", explain_worker_failure("engine-exited", 422))

    def test_creality_region_rejection_has_bounded_help_categories(self):
        from core.slicer_failure_messages import explain_worker_failure
        for reason in ("creality-region-archive-invalid",
                       "creality-region-graph-invalid",
                       "creality-region-parts-invalid",
                       "creality-region-metadata-invalid",
                       "creality-region-profiles-invalid"):
            with self.subTest(reason=reason):
                explanation = explain_worker_failure(reason, 422)
                self.assertIn("Creality", explanation)
                self.assertNotIn("OrcaSlicer", explanation)
