import json
from unittest.mock import patch

from django.test import TestCase, override_settings

from core.models import PrinterCatalogModel, PrinterManufacturer
from core.orcaslicer_catalogue import (
    ORCA_DIRECTORY_URL,
    _canonical_vendor,
    _merge_model,
    _normalise_model_name,
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
    @patch("core.orcaslicer_catalogue.requests.get")
    def test_sync_adds_models_and_collapses_cfs_profile_variants(self, get):
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
