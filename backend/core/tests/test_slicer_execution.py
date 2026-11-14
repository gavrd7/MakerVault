"""Execution admission must fail closed for mismatched or unverified worker images."""
from unittest.mock import patch
from django.test import SimpleTestCase

from core.slicer_execution import verified_installation, _single_unmodified_stl, _validate_plate_execution, SlicerExecutionError


class IntendedMaterialSafetyTests(SimpleTestCase):
    def test_mapped_draft_cannot_silently_produce_single_filament_gcode(self):
        from types import SimpleNamespace
        for count in (1, 2):
            with self.subTest(count=count):
                models = [{
                    "instance_id": str(index),
                    "material_slot": {
                        "printer_id": "printer", "slot_id": "slot-" + str(index),
                        "slot_index": index,
                    },
                } for index in range(count)]
                job = SimpleNamespace(
                    settings={"plate_objects": models},
                    engine="orcaslicer",
                )
                with self.assertRaisesRegex(SlicerExecutionError, "not yet verified"):
                    _validate_plate_execution(job)


    def test_native_slicing_rejects_v1_and_v2_paint_regions(self):
        from types import SimpleNamespace
        cases = (
            {"version": 1, "faces": {"0": 0}},
            {"version": 2, "regions": [{"slot": 0, "patches": []}]},
        )
        for paint in cases:
            with self.subTest(version=paint["version"]):
                job = SimpleNamespace(
                    settings={"plate_objects": [{
                        "instance_id": "one", "colour_paint": paint,
                    }]},
                    engine="orcaslicer",
                )
                with self.assertRaisesRegex(SlicerExecutionError, "native region-to-tool"):
                    _validate_plate_execution(job)

    def test_unhandled_flush_matrix_cannot_be_silently_ignored(self):
        from types import SimpleNamespace
        for models in (None, [], [{"instance_id": "one"}]):
            with self.subTest(models=models):
                job = SimpleNamespace(
                    settings={"plate_objects": models, "flush_settings": {
                        "multiplier": None, "prime_tower": "enabled",
                        "transitions": [],
                    }},
                    engine="orcaslicer",
                )
                with self.assertRaisesRegex(SlicerExecutionError, "flushing/prime-tower"):
                    _validate_plate_execution(job)


class WorkerApprovalTests(SimpleTestCase):
    def setUp(self):
        self.digest = "sha256:" + "a" * 64
        self.approved = {
            "MAKERVAULT_SLICER_EXECUTION_ENABLED": "1",
            "MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST": self.digest,
            "MAKERVAULT_SLICER_ENGINE_VERSION": "2.9.7",
            "MAKERVAULT_SLICER_ENGINE_BINARY_SHA256": "b" * 64,
            "MAKERVAULT_SLICER_ENGINE": "orcaslicer",
            "MAKERVAULT_SLICER_WORKER_IMAGE": "registry.example.invalid/slicer@" + self.digest,
        }

    @patch("core.slicer_execution.health", return_value={
        "ready": True, "engine": "orcaslicer", "version": "2.9.7",
        "binary_sha256": "b" * 64,
    })
    def test_requires_explicit_enablement_matching_digest_and_worker_version(self, worker):
        with patch.dict("os.environ", self.approved, clear=True):
            installed = verified_installation()
            self.assertTrue(installed["orcaslicer"]["verified"])
        for changes in (
            {"MAKERVAULT_SLICER_EXECUTION_ENABLED": "0"},
            {"MAKERVAULT_SLICER_WORKER_IMAGE": "registry/slicer:latest"},
            {"MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST": "sha256:" + "b" * 64},
            {"MAKERVAULT_SLICER_ENGINE_VERSION": "2.9.6"},
        ):
            with self.subTest(changes=changes):
                with patch.dict("os.environ", {**self.approved, **changes}, clear=True):
                    self.assertEqual(verified_installation(), {})

    @patch("core.slicer_execution.health", return_value={
        "ready": True, "engine": "orcaslicer", "version": "2.9.7",
        "binary_sha256": "b" * 64,
    })
    def test_staging_immutable_local_image_id_is_allowed_only_on_exact_match(self, worker):
        environment = {**self.approved, "MAKERVAULT_SLICER_WORKER_IMAGE": self.digest}
        with patch.dict("os.environ", environment, clear=True):
            self.assertEqual(verified_installation()["orcaslicer"]["image_digest"], self.digest)
        with patch.dict("os.environ", {
            **environment, "MAKERVAULT_SLICER_WORKER_IMAGE": "sha256:" + "f" * 64
        }, clear=True):
            self.assertEqual(verified_installation(), {})

    @patch("core.slicer_execution.health", return_value={
        "ready": True, "engine": "orcaslicer", "version": "2.9.7",
        "binary_sha256": "c" * 64,
    })
    def test_worker_binary_hash_mismatch_disables_execution(self, worker):
        with patch.dict("os.environ", self.approved, clear=True):
            self.assertEqual(verified_installation(), {})

    @patch("core.slicer_execution.health")
    def test_two_independent_approved_engines_share_one_worker(self, worker):
        import json
        worker.return_value = {
            "ready": True,
            "engines": {
                "orcaslicer": {"ready": True, "version": "2.4.2", "binary_sha256": "b" * 64},
                "crealityprint": {"ready": True, "version": "7.3.0", "binary_sha256": "c" * 64},
            },
        }
        approvals = {
            "orcaslicer": {"version": "2.4.2", "binary_sha256": "b" * 64},
            "crealityprint": {"version": "7.3.0", "binary_sha256": "c" * 64},
        }
        settings = {
            **self.approved,
            "MAKERVAULT_SLICER_ENGINES_JSON": json.dumps(approvals),
        }
        with patch.dict("os.environ", settings, clear=True):
            available = verified_installation()
            self.assertEqual(set(available), {"orcaslicer", "crealityprint"})
            self.assertEqual(available["crealityprint"]["version"], "7.3.0")
            worker.return_value["engines"]["orcaslicer"]["binary_sha256"] = "d" * 64
            available = verified_installation()
            self.assertEqual(set(available), {"crealityprint"})
            worker.return_value["engines"]["crealityprint"]["ready"] = False
            self.assertEqual(verified_installation(), {})

    @patch("core.slicer_execution.health", return_value={
        "ready": True,
        "engines": {
            "crealityprint": {"ready": True, "version": "7.3.0", "binary_sha256": "c" * 64},
        },
    })
    def test_creality_only_does_not_require_orca(self, worker):
        import json
        with patch.dict("os.environ", {
            **self.approved,
            "MAKERVAULT_SLICER_ENGINES_JSON": json.dumps({
                "crealityprint": {"version": "7.3.0", "binary_sha256": "c" * 64}
            }),
        }, clear=True):
            self.assertEqual(set(verified_installation()), {"crealityprint"})

    @patch("core.slicer_execution.health", return_value={
        "ready": False, "engine": "orcaslicer", "version": "2.9.7",
        "binary_sha256": "b" * 64,
    })
    def test_unready_worker_does_not_enable_slice(self, worker):
        with patch.dict("os.environ", self.approved, clear=True):
            self.assertEqual(verified_installation(), {})


class PrivateSlicerSourceReadTests(SimpleTestCase):
    def test_repeated_reads_open_fresh_storage_streams(self):
        from io import BytesIO
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from core.slicer_execution import _read_owned_file

        storage = MagicMock()
        storage.open.side_effect = lambda path, mode: BytesIO(b'{"type":"machine"}')
        field = SimpleNamespace(name="private/ab/opaque.blob", storage=storage)
        asset = SimpleNamespace(pk="asset-id", owner_id=7, file=field)

        self.assertEqual(_read_owned_file(asset, 7, 1024, "Native profile"),
                         b'{"type":"machine"}')
        self.assertEqual(_read_owned_file(asset, 7, 1024, "Native profile"),
                         b'{"type":"machine"}')
        self.assertEqual(storage.open.call_count, 2)
        storage.open.assert_called_with("private/ab/opaque.blob", "rb")


class DirectSingleModelSliceTests(SimpleTestCase):
    def test_unmodified_single_instance_can_use_native_stl_path(self):
        item = {"asset_id": "source", "x_mm": 0, "y_mm": 0,
                "rotation_deg": 0, "scale_percent": 100, "color": "#ffffff"}
        self.assertTrue(_single_unmodified_stl([item]))
        self.assertTrue(_single_unmodified_stl([
            {**item, "scale_xyz_percent": [100, 100, 100]}
        ]))

    def test_single_object_native_overrides_must_never_use_unconfigured_stl(self):
        item = {"asset_id": "source", "x_mm": 0, "y_mm": 0,
                "rotation_deg": 0, "scale_percent": 100,
                "process_overrides": {"wall_loops": 5}}
        self.assertFalse(_single_unmodified_stl([item]))

    def test_transforms_or_multiple_instances_require_project_path(self):
        item = {"asset_id": "source", "x_mm": 0, "y_mm": 0,
                "rotation_deg": 0, "scale_percent": 100}
        self.assertFalse(_single_unmodified_stl([item, item]))
        for changed in (
            {"x_mm": 5}, {"y_mm": -2}, {"rotation_deg": 90},
            {"scale_percent": 120}, {"scale_xyz_percent": [110, 100, 100]},
        ):
            with self.subTest(changed=changed):
                self.assertFalse(_single_unmodified_stl([{**item, **changed}]))


class NativePlateAdmissionTests(SimpleTestCase):
    def test_single_unmodified_stl_does_not_need_3mf_bed_geometry(self):
        from types import SimpleNamespace
        plate = [{"asset_id": "model", "x_mm": 0, "y_mm": 0,
                  "rotation_deg": 0, "scale_percent": 100}]
        job = SimpleNamespace(settings={"plate_objects": plate},
                              engine="orcaslicer", printer_profile_id="printer",
                              printer_profile=SimpleNamespace())
        with patch("core.slicer_execution.trusted_plate_dimensions",
                   side_effect=ValueError("Missing polygon")) as inspect:
            self.assertTrue(_validate_plate_execution(job))
            inspect.assert_not_called()

    def test_edited_3mf_still_requires_native_bed(self):
        from types import SimpleNamespace
        plate = [{"asset_id": "model", "x_mm": 2, "y_mm": 0,
                  "rotation_deg": 0, "scale_percent": 100}]
        job = SimpleNamespace(settings={"plate_objects": plate},
                              engine="orcaslicer", printer_profile_id="printer",
                              printer_profile=SimpleNamespace())
        with patch("core.slicer_execution.trusted_plate_dimensions",
                   side_effect=ValueError("Missing polygon")):
            with self.assertRaisesRegex(SlicerExecutionError, "3MF plate"):
                _validate_plate_execution(job)


class PerObjectExecutionRoutingTests(SimpleTestCase):
    def test_global_only_plates_keep_approved_compound_path(self):
        from core.slicer_execution import _plate_builder
        from core.slicer_plate_3mf import build_compound_plate_3mf
        objects = [({"instance_id": "one"}, b"stl"),
                   ({"instance_id": "two"}, b"stl")]
        self.assertIs(_plate_builder(objects), build_compound_plate_3mf)

    def test_native_object_overrides_select_independent_3mf_builder(self):
        from core.slicer_execution import _plate_builder, _validate_plate_execution
        from core.slicer_plate_3mf import build_plate_3mf
        from types import SimpleNamespace
        objects = [({"instance_id": "one"}, b"stl"),
                   ({"instance_id": "two",
                     "process_overrides": {"wall_loops": 5}}, b"stl")]
        self.assertIs(_plate_builder(objects), build_plate_3mf)
        job = SimpleNamespace(settings={"plate_objects": [row for row, _ in objects]},
                              engine="orcaslicer", printer_profile_id="printer",
                              printer_profile=SimpleNamespace())
        with patch("core.slicer_execution.trusted_plate_dimensions", return_value=(220, 220)):
            self.assertTrue(_validate_plate_execution(job))
        job.settings["plate_objects"][1]["process_overrides"] = {
            "wall_loops": 5, "sparse_infill_density": 37,
        }
        with patch("core.slicer_execution.trusted_plate_dimensions", return_value=(220, 220)):
            self.assertTrue(_validate_plate_execution(job))
        job.settings["plate_objects"][1]["process_overrides"]["enable_support"] = "1"
        with self.assertRaisesRegex(SlicerExecutionError, "not passed real Orca"):
            _validate_plate_execution(job)


class TemporarySlicerInputRetentionTests(SimpleTestCase):
    def test_removed_failed_job_does_not_delete_unsaved_plate_inputs(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from core.slicer_api import _cleanup_temporary_job_sources

        job = SimpleNamespace(
            input_asset_id="temporary-stl", owner_id=1,
            settings={"plate_objects": [{"asset_id": "temporary-stl"}]},
        )
        # A browser plate may still reference the STL after deleting this job.
        # Temporary files must not be removed on job deletion alone.
        with patch("core.slicer_api.FileAsset.objects") as files:
            self.assertIsNone(_cleanup_temporary_job_sources(job))
            files.filter.assert_not_called()


class NativeOrcaCustomPrinterCompatibilityTests(SimpleTestCase):
    def setUp(self):
        import json
        from types import SimpleNamespace
        self.source = SimpleNamespace(
            pk="original", name="Creality K2 0.4 nozzle", owner_id=1,
            engine="orcaslicer", engine_version="2.4.2", kind="printer",
        )
        self.custom = SimpleNamespace(
            owner_id=1, engine="orcaslicer", engine_version="2.4.2",
            file_asset=SimpleNamespace(metadata={
                "slicer_custom_source_profile_id": "d22683d1-36da-42dd-812e-6222808ca909",
            }),
        )
        self.native = {
            "name": "Creality K2 0.4 nozzle",
            "printer_model": "Creality K2",
            "printer_variant": "0.4",
            "nozzle_diameter": ["0.4"],
            "printable_area": ["0x0", "260x0", "260x260", "0x260"],
            "printable_height": "260",
            "bed_exclude_area": ["0x0"],
            "retraction_distances_when_cut": "30",
        }
        self.custom_json = {**self.native,
            "name": "K2 18mm custom",
            "retraction_distances_when_cut": "18",
        }
        self.process = json.dumps({
            "name": "0.20mm Standard @Creality K2 0.4 nozzle",
            "compatible_printers": ["Creality K2 0.4 nozzle"],
        }).encode()

    def test_custom_copy_uses_original_machine_identity_only_in_worker_payload(self):
        import json
        from core.slicer_execution import _execution_printer_profile
        with patch("core.slicer_execution.SlicerProfile.objects") as manager, patch(
            "core.slicer_execution.resolved_native_profile",
            return_value=json.dumps(self.native).encode(),
        ):
            manager.filter.return_value.select_related.return_value.first.return_value = self.source
            submitted = _execution_printer_profile(
                self.custom, json.dumps(self.custom_json).encode(), self.process
            )
        resolved = json.loads(submitted)
        self.assertEqual(resolved["name"], "Creality K2 0.4 nozzle")
        self.assertEqual(resolved["retraction_distances_when_cut"], "18")
        self.assertEqual(self.custom_json["name"], "K2 18mm custom")

    def test_changed_nozzle_fails_closed(self):
        import json
        from core.slicer_execution import _execution_printer_profile
        changed = {**self.custom_json, "nozzle_diameter": ["0.6"]}
        with patch("core.slicer_execution.SlicerProfile.objects") as manager, patch(
            "core.slicer_execution.resolved_native_profile",
            return_value=json.dumps(self.native).encode(),
        ):
            manager.filter.return_value.select_related.return_value.first.return_value = self.source
            with self.assertRaisesRegex(SlicerExecutionError, "nozzle or build geometry"):
                _execution_printer_profile(self.custom, json.dumps(changed).encode(), self.process)

    def test_unrelated_process_profile_is_rejected(self):
        import json
        from core.slicer_execution import _execution_printer_profile
        unrelated = json.dumps({
            "compatible_printers": ["Other Machine"],
        }).encode()
        with patch("core.slicer_execution.SlicerProfile.objects") as manager, patch(
            "core.slicer_execution.resolved_native_profile",
            return_value=json.dumps(self.native).encode(),
        ):
            manager.filter.return_value.select_related.return_value.first.return_value = self.source
            with self.assertRaises(SlicerExecutionError):
                _execution_printer_profile(self.custom, json.dumps(self.custom_json).encode(), unrelated)
