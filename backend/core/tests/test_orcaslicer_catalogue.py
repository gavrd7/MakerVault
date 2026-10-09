import json
from unittest.mock import patch

from django.test import TestCase, override_settings

from core.models import PrinterCatalogModel, PrinterManufacturer
from core.orcaslicer_catalogue import (
    ORCA_DIRECTORY_URL,
    _canonical_vendor,
    _load_supplemental_printers,
    _merge_model,
    _merge_supplemental_model,
    _normalise_model_name,
    _volume_from_machine_values,
    sync_orcaslicer_printer_catalogue,
)


class FakeResponse:
    def __init__(self, *, payload=None, text="", status_code=200):
        self._payload = payload
        self._text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if self._payload is None:
            return json.loads(self._text)
        return self._payload

    def iter_content(self, chunk_size=32768, decode_unicode=False):
        for start in range(0, len(self._text), chunk_size):
            yield self._text[start:start + chunk_size]

    def close(self):
        pass


class OrcaSlicerPrinterCatalogueTests(TestCase):
    def test_vendor_and_optional_addon_names_are_normalised(self):
        self.assertEqual(_canonical_vendor("Bambulab"), "Bambu Lab")
        self.assertEqual(_canonical_vendor("Qidi"), "QIDI")
        self.assertEqual(
            _normalise_model_name("Creality", "Creality K1C_CFS-C"),
            ("K1C", "creality_cfs"),
        )
        self.assertEqual(
            _normalise_model_name("Bambu Lab", "Bambu Lab A1 mini"),
            ("A1 mini", ""),
        )

    def test_machine_printable_area_maps_to_build_volume(self):
        volume = _volume_from_machine_values({
            "printable_area": ["0x0", "256x0", "256x256", "0x256"],
            "printable_height": "256",
        })
        self.assertEqual(volume["build_volume_x_mm"], 256)
        self.assertEqual(volume["build_volume_y_mm"], 256)
        self.assertEqual(volume["build_volume_z_mm"], 256)

    def test_orca_provenance_does_not_overwrite_curated_makervault_specs(self):
        maker = PrinterManufacturer.objects.create(name="Creality")
        model = PrinterCatalogModel.objects.create(
            manufacturer=maker,
            name="K2",
            build_volume_x_mm="260",
            build_volume_y_mm="260",
            build_volume_z_mm="260",
            max_nozzle_temp_c=300,
            enclosed=True,
            multi_material_system="creality_cfs",
            features={"camera": True, "auto_leveling": True},
            source_url="https://www.creality.com/example-k2",
        )

        _merge_model({
            "vendor": "Creality",
            "name": "K2",
            "raw_name": "Creality K2",
            "vendor_file": "Creality.json",
            "sub_path": "machine/Creality K2.json",
            "multi_material_system": "",
            "source_url": "https://github.com/OrcaSlicer/OrcaSlicer/blob/main/resources/profiles/Creality/machine/Creality%20K2.json",
        }, "main")

        model.refresh_from_db()
        self.assertEqual(str(model.build_volume_x_mm), "260.00")
        self.assertEqual(model.max_nozzle_temp_c, 300)
        self.assertTrue(model.enclosed)
        self.assertEqual(model.source_url, "https://www.creality.com/example-k2")
        self.assertTrue(model.features["camera"])
        self.assertIn("orcaslicer", model.features)
        self.assertEqual(model.features["orcaslicer"]["upstream_name"], "Creality K2")

    @override_settings(ORCASLICER_PRINTER_CATALOGUE_REF="main")
    @patch("core.orcaslicer_catalogue._load_supplemental_printers", return_value=[])
    @patch("core.orcaslicer_catalogue.requests.get")
    def test_sync_adds_models_and_collapses_cfs_profile_variants(self, get, supplements):
        listing = [
            {
                "type": "file",
                "name": "Creality.json",
                "download_url": "https://raw.githubusercontent.com/OrcaSlicer/OrcaSlicer/main/resources/profiles/Creality.json",
            },
            {
                "type": "file",
                "name": "BBL.json",
                "download_url": "https://raw.githubusercontent.com/OrcaSlicer/OrcaSlicer/main/resources/profiles/BBL.json",
            },
            {
                "type": "file",
                "name": "OrcaFilamentLibrary.json",
                "download_url": "https://raw.githubusercontent.com/OrcaSlicer/OrcaSlicer/main/resources/profiles/OrcaFilamentLibrary.json",
            },
        ]
        creality = json.dumps({
            "name": "Creality",
            "machine_model_list": [
                {"name": "Creality K1C", "sub_path": "machine/Creality K1C.json"},
                {"name": "Creality K1C_CFS-C", "sub_path": "machine/Creality K1C_CFS-C.json"},
            ],
            "process_list": [{"name": "ignored"}],
        })
        bambu = json.dumps({
            "name": "Bambulab",
            "machine_model_list": [
                {"name": "Bambu Lab A1 mini", "sub_path": "machine/Bambu Lab A1 mini.json"},
            ],
        })

        def response_for(url, *args, **kwargs):
            if url == ORCA_DIRECTORY_URL:
                return FakeResponse(payload=listing)
            if url.endswith("/Creality.json"):
                return FakeResponse(text=creality)
            if url.endswith("/BBL.json"):
                return FakeResponse(text=bambu)
            raise AssertionError(f"Unexpected URL: {url}")

        get.side_effect = response_for

        result = sync_orcaslicer_printer_catalogue(max_workers=2)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["vendors_seen"], 2)
        self.assertEqual(result["models_seen"], 2)
        self.assertEqual(result["models_created"], 2)

        k1c = PrinterCatalogModel.objects.get(
            manufacturer__name="Creality",
            name="K1C",
        )
        self.assertEqual(k1c.multi_material_system, "creality_cfs")
        self.assertIsNone(k1c.enclosed)
        self.assertFalse(
            PrinterCatalogModel.objects.filter(name__icontains="CFS-C").exists()
        )

        a1mini = PrinterCatalogModel.objects.get(
            manufacturer__name="Bambu Lab",
            name="A1 mini",
        )
        self.assertEqual(a1mini.multi_material_system, "bambu_ams")
        self.assertEqual(
            a1mini.features["orcaslicer"]["vendor_file"],
            "BBL.json",
        )


    @override_settings(ORCASLICER_PRINTER_CATALOGUE_REF="main")
    @patch("core.orcaslicer_catalogue._load_supplemental_printers", return_value=[])
    @patch("core.orcaslicer_catalogue.requests.get")
    def test_sync_enriches_missing_build_volume_from_machine_profile_inheritance(self, get, supplements):
        listing = [{
            "type": "file",
            "name": "BBL.json",
            "download_url": "https://raw.githubusercontent.com/OrcaSlicer/OrcaSlicer/main/resources/profiles/BBL.json",
        }]
        manifest = json.dumps({
            "name": "Bambulab",
            "machine_model_list": [
                {"name": "Bambu Lab A1", "sub_path": "machine/Bambu Lab A1.json"},
            ],
            "machine_list": [
                {"name": "Bambu Lab A1 0.4 nozzle", "sub_path": "machine/Bambu Lab A1 0.4 nozzle.json"},
            ],
        })
        machine = {
            "type": "machine",
            "name": "Bambu Lab A1 0.4 nozzle",
            "inherits": "fdm_bbl_3dp_001_common",
            "printable_height": "256",
        }
        common = {
            "type": "machine",
            "name": "fdm_bbl_3dp_001_common",
            "printable_area": ["0x0", "256x0", "256x256", "0x256"],
            "printer_structure": "i3",
        }

        def response_for(url, *args, **kwargs):
            if url == ORCA_DIRECTORY_URL:
                return FakeResponse(payload=listing)
            if url.endswith("/BBL.json"):
                return FakeResponse(text=manifest)
            if url.endswith("/BBL/machine/Bambu%20Lab%20A1%200.4%20nozzle.json"):
                return FakeResponse(payload=machine)
            if url.endswith("/BBL/machine/fdm_bbl_3dp_001_common.json"):
                return FakeResponse(payload=common)
            raise AssertionError(f"Unexpected URL: {url}")

        get.side_effect = response_for

        result = sync_orcaslicer_printer_catalogue(max_workers=2)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["hardware_profiles_enriched"], 1)

        model = PrinterCatalogModel.objects.get(
            manufacturer__name="Bambu Lab",
            name="A1",
        )
        self.assertEqual(str(model.build_volume_x_mm), "256.00")
        self.assertEqual(str(model.build_volume_y_mm), "256.00")
        self.assertEqual(str(model.build_volume_z_mm), "256.00")
        self.assertEqual(model.features["printer_structure"], "i3")
        self.assertEqual(
            model.features["orcaslicer"]["hardware_profile"],
            "machine/Bambu Lab A1 0.4 nozzle.json",
        )


    def test_verified_supplemental_build_volume_fills_only_missing_fields(self):
        maker = PrinterManufacturer.objects.create(name="Creality")
        item = PrinterCatalogModel.objects.create(
            manufacturer=maker, name="Fixture Printer",
            build_volume_x_mm=245,
            source_url="https://example.com/manual",
        )
        row = {
            "manufacturer": "Creality", "name": "Fixture Printer",
            "family": "Test", "source_url": "https://example.com/catalogue",
            "build_volume_mm": [220, 220, 250],
            "build_volume_source_url": "https://www.creality.com/products/test",
        }
        _merge_supplemental_model(row)
        item.refresh_from_db()
        self.assertEqual(str(item.build_volume_x_mm), "245.00")
        self.assertEqual(str(item.build_volume_y_mm), "220.00")
        self.assertEqual(str(item.build_volume_z_mm), "250.00")
        self.assertEqual(item.source_url, "https://example.com/manual")
        self.assertEqual(
            item.features["makervault_supplemental"]["build_volume_source_url"],
            row["build_volume_source_url"],
        )

    def test_supplemental_volumes_require_valid_reference_and_dimensions(self):
        maker = PrinterManufacturer.objects.create(name="Creality")
        for index, bad in enumerate((
            {"build_volume_mm": [220, 220, 250]},
            {"build_volume_mm": [-1, 220, 250],
             "build_volume_source_url": "https://www.creality.com/test"},
            {"build_volume_mm": [220, 250],
             "build_volume_source_url": "https://www.creality.com/test"},
        )):
            row = {
                "manufacturer": "Creality", "name": f"Invalid {index}",
                "source_url": "", **bad,
            }
            _merge_supplemental_model(row)
            item = PrinterCatalogModel.objects.get(manufacturer=maker, name=row["name"])
            self.assertIsNone(item.build_volume_x_mm)

    def test_supplemental_catalogue_has_verified_creality_volumes(self):
        records = {
            row["name"]: row for row in _load_supplemental_printers()
            if row["manufacturer"] == "Creality"
        }
        self.assertEqual(records["K2 Pro"]["build_volume_mm"], [300, 300, 300])
        self.assertEqual(records["K1 SE"]["build_volume_mm"], [220, 220, 250])
        self.assertTrue(records["K1 SE"]["build_volume_source_url"].startswith("https://"))

    def test_supplemental_catalogue_is_fdm_only_and_includes_known_creality_families(self):
        rows = _load_supplemental_printers()
        creality = [row for row in rows if row["manufacturer"] == "Creality"]
        names = {row["name"] for row in creality}

        self.assertIn("K2 Pro", names)
        self.assertIn("K1 SE", names)
        self.assertIn("Ender-3 V3 KE", names)
        self.assertIn("Ender-5 Max", names)
        self.assertIn("CR-30", names)
        self.assertIn("CR-M4", names)
        self.assertIn("Sermoon S1", names)
        self.assertIn("SPARKX i7", names)
        self.assertFalse(any("HALOT" in name.upper() for name in names))

    def test_supplemental_model_adds_presence_without_overwriting_curated_specs(self):
        maker = PrinterManufacturer.objects.create(name="Creality")
        existing = PrinterCatalogModel.objects.create(
            manufacturer=maker,
            name="Ender-3 V3 KE",
            build_volume_x_mm="220",
            build_volume_y_mm="220",
            build_volume_z_mm="240",
            max_nozzle_temp_c=300,
            source_url="https://example.invalid/manual-source",
            features={"manual_note": "curated"},
        )

        maker_created, model_created, model_enriched = _merge_supplemental_model({
            "manufacturer": "Creality",
            "name": "Ender-3 V3 KE",
            "family": "Ender-3",
            "source_url": "https://store.creality.com/uk/collections/3d-printers",
            "multi_material_system": "",
        })

        self.assertFalse(maker_created)
        self.assertFalse(model_created)
        self.assertTrue(model_enriched)
        existing.refresh_from_db()
        self.assertEqual(str(existing.build_volume_x_mm), "220.00")
        self.assertEqual(existing.max_nozzle_temp_c, 300)
        self.assertEqual(existing.source_url, "https://example.invalid/manual-source")
        self.assertEqual(existing.features["manual_note"], "curated")
        self.assertEqual(existing.features["makervault_supplemental"]["technology"], "FDM/FFF")



    @patch("core.orcaslicer_catalogue._load_supplemental_printers", return_value=[])
    @patch("core.orcaslicer_catalogue.requests.get")
    @patch("core.orcaslicer_catalogue._fetch_vendor_manifest")
    def test_partial_vendor_retry_reuses_success_and_refetches_failure(self, fetch, get, _supplements):
        from core.orcaslicer_catalogue import sync_orcaslicer_printer_catalogue
        from core.orcaslicer_catalogue import OrcaCatalogueError

        listing = [
            {"type": "file", "name": "Alpha.json", "sha": "first"},
            {"type": "file", "name": "Beta.json", "sha": "second"},
        ]
        get.return_value = FakeResponse(payload=listing)
        saved = {}
        class FakeCache:
            def get(self, key): return saved.get(key)
            def set(self, key, value, timeout=None): saved[key] = value
        counts = {"Alpha.json": 0, "Beta.json": 0}
        def fetch_vendor(entry, ref):
            name = entry["name"]
            counts[name] += 1
            if name == "Beta.json" and counts[name] == 1:
                raise OrcaCatalogueError("temporary vendor failure")
            return name.removesuffix(".json"), []
        fetch.side_effect = fetch_vendor

        with patch("core.orcaslicer_catalogue.cache", FakeCache()):
            first = sync_orcaslicer_printer_catalogue(max_workers=1)
            second = sync_orcaslicer_printer_catalogue(max_workers=1, retry_failed_only=True)
        self.assertEqual(first["status"], "partial")
        self.assertEqual(second["status"], "complete")
        self.assertEqual(counts["Alpha.json"], 1)
        self.assertEqual(counts["Beta.json"], 2)

class OrcaPrinterTaskRetryTests(TestCase):
    @patch("core.tasks.backup_in_progress", return_value=False)
    @patch("core.tasks.sync_orcaslicer_printer_catalogue")
    def test_partial_sync_requeues_once(self, sync, _backup):
        from core.tasks import sync_orcaslicer_printer_catalogue_task

        sync.return_value = {"status": "partial", "hardware_profiles_failed": 1}
        with patch.object(sync_orcaslicer_printer_catalogue_task, "apply_async") as queue:
            sync_orcaslicer_printer_catalogue_task()
            queue.assert_called_once_with(
                kwargs={"retry_attempt": 1}, countdown=600,
            )
            sync_orcaslicer_printer_catalogue_task(retry_attempt=1)
            self.assertEqual(sync.call_args.kwargs, {"retry_failed_only": True})
            self.assertEqual(queue.call_count, 1)

    @patch("core.tasks.backup_in_progress", return_value=False)
    @patch("core.tasks.sync_orcaslicer_printer_catalogue",
           return_value={"status": "complete", "hardware_profiles_incomplete": 3})
    def test_missing_unavailable_hardware_does_not_trigger_retry(self, _sync, _backup):
        from core.tasks import sync_orcaslicer_printer_catalogue_task

        with patch.object(sync_orcaslicer_printer_catalogue_task, "apply_async") as queue:
            self.assertEqual(
                sync_orcaslicer_printer_catalogue_task()["status"], "complete",
            )
            queue.assert_not_called()

    @patch("core.tasks.backup_in_progress", return_value=True)
    @patch("core.tasks.sync_orcaslicer_printer_catalogue")
    def test_backup_skips_sync_and_retry(self, sync, _backup):
        from core.tasks import sync_orcaslicer_printer_catalogue_task

        with patch.object(sync_orcaslicer_printer_catalogue_task, "apply_async") as queue:
            self.assertEqual(
                sync_orcaslicer_printer_catalogue_task()["status"],
                "backup-in-progress",
            )
            queue.assert_not_called()
            sync.assert_not_called()
