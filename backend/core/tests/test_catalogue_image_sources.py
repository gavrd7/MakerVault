import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings

from core.catalogue_coverage import _printer_coverage
from core.catalogue_image_sources import (
    CatalogueImageError,
    _board_image_queries,
    _candidate_source_pages,
    _is_computer_board,
    _page_image_candidates,
    _curated_sbc_source_page,
    _curated_board_source_pages,
    _curated_sbc_source_pages,
    _commons_license_allowed,
    _component_image_queries,
    _espboards_slug_candidates,
    _openverse_license_name,
    _printer_image_queries,
    _printer_multi_material_image_queries,
    _structured_product_image,
    find_curated_printer_image,
    find_orcaslicer_printer_cover,
    find_source_page_image,
    run_catalogue_image_seed,
    search_openverse,
    search_wikimedia_commons,
)
from core.models import BoardModel, ComponentCategory, ComponentModel, PrinterCatalogModel, PrinterManufacturer


class DummyManufacturer:
    name = "Seeed Studio"


class DummyBoard:
    name = "XIAO ESP32C3"
    manufacturer = DummyManufacturer()




class DummyGenericManufacturer:
    name = "Generic"


class DummyGenericBoard:
    name = "ESP32 C3 Super Mini"
    mcu = "ESP32-C3"
    manufacturer = DummyGenericManufacturer()


class DummyComponent:
    name = "BME280 temperature/humidity/pressure sensor"
    part_number = "BME280"
    specifications = {"type": "environment"}


class DummyPrinterManufacturer:
    name = "Creality"


class DummyPrinterModel:
    name = "K2"
    manufacturer = DummyPrinterManufacturer()
    multi_material_system = "creality_cfs"
    MULTI_MATERIAL_SYSTEMS = [
        ("", "None / unknown"),
        ("creality_cfs", "Creality CFS"),
    ]


class CatalogueImageSourceTests(unittest.TestCase):
    def test_espboards_slug_candidates_are_stable(self):
        slugs = _espboards_slug_candidates(DummyBoard())
        self.assertIn("xiao-esp32c3", slugs)

    @patch("core.catalogue_image_sources.requests.get")
    def test_commons_search_filters_and_returns_free_licensed_raster(self, get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "query": {
                "pages": [
                    {
                        "title": "File:BME280 sensor module.jpg",
                        "imageinfo": [{
                            "mime": "image/jpeg",
                            "thumburl": "https://upload.wikimedia.org/example.jpg",
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:BME280_sensor_module.jpg",
                            "extmetadata": {
                                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                                "Artist": {"value": "Example Author"},
                            },
                        }],
                    }
                ]
            }
        }
        get.return_value = response
        candidate = search_wikimedia_commons("BME280 sensor module", minimum_score=0.1)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.provider, "Wikimedia Commons")
        self.assertEqual(candidate.license_name, "CC BY-SA 4.0")
        self.assertEqual(candidate.author, "Example Author")

    @patch("core.catalogue_image_sources.requests.get")
    def test_commons_search_rejects_non_free_license(self, get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "query": {
                "pages": [{
                    "title": "File:Example.jpg",
                    "imageinfo": [{
                        "mime": "image/jpeg",
                        "url": "https://upload.wikimedia.org/example.jpg",
                        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Example.jpg",
                        "extmetadata": {"LicenseShortName": {"value": "All rights reserved"}},
                    }],
                }]
            }
        }
        get.return_value = response
        self.assertIsNone(search_wikimedia_commons("Example", minimum_score=0.0))

    def test_commons_license_filter_rejects_noncommercial_and_nd(self):
        self.assertTrue(_commons_license_allowed("CC BY 4.0"))
        self.assertTrue(_commons_license_allowed("CC BY-SA 4.0"))
        self.assertTrue(_commons_license_allowed("CC0 1.0"))
        self.assertTrue(_commons_license_allowed("Public domain"))
        self.assertFalse(_commons_license_allowed("CC BY-NC 4.0"))
        self.assertFalse(_commons_license_allowed("CC BY-ND 4.0"))
        self.assertFalse(_commons_license_allowed("CC BY-NC-SA 4.0"))


    def test_computer_board_detection_uses_catalogue_classification(self):
        board = BoardModel(name="ROCK 5B", specifications={"board_type": "sbc"})
        module = BoardModel(name="CM5", specifications={"board_type": "compute_module"})
        mcu = BoardModel(name="Pico", specifications={"board_type": "microcontroller"})
        self.assertTrue(_is_computer_board(board))
        self.assertTrue(_is_computer_board(module))
        self.assertFalse(_is_computer_board(mcu))

    def test_query_generation_prefers_exact_names(self):
        self.assertEqual(_board_image_queries(DummyGenericBoard())[0], "ESP32 C3 Super Mini")
        queries = _component_image_queries(DummyComponent())
        self.assertEqual(queries[0], "BME280 module")
        self.assertIn("BME280", queries)

    def test_component_query_preserves_slide_potentiometer_form_factor(self):
        component = DummyComponent()
        component.name = "10k slide potentiometer"
        component.part_number = ""
        component.specifications = {"type": "potentiometer", "value": "10 kΩ"}
        queries = _component_image_queries(component)
        self.assertEqual(queries[0], "10k slide potentiometer")
        self.assertIn("10k slide potentiometer linear slider", queries)
        self.assertIn("slide potentiometer electronics", queries)

    def test_structured_product_image_supports_schema_org_product(self):
        html = """
        <html><head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Example Sensor",
          "image": ["/media/example-sensor.jpg"]
        }
        </script>
        </head></html>
        """
        soup = __import__("bs4").BeautifulSoup(html, "html.parser")
        self.assertEqual(
            _structured_product_image(soup, "https://vendor.example/products/example"),
            "https://vendor.example/media/example-sensor.jpg",
        )

    def test_structured_product_image_supports_graph_and_image_src(self):
        graph_html = """
        <script type="application/ld+json">
        {"@graph":[{"@type":"Product","image":{"url":"https://cdn.example/product.webp"}}]}
        </script>
        """
        soup = __import__("bs4").BeautifulSoup(graph_html, "html.parser")
        self.assertEqual(
            _structured_product_image(soup, "https://vendor.example/product"),
            "https://cdn.example/product.webp",
        )

        fallback_html = '<html><head><link rel="image_src" href="/img/fallback.png"></head></html>'
        fallback_soup = __import__("bs4").BeautifulSoup(fallback_html, "html.parser")
        self.assertEqual(
            _structured_product_image(fallback_soup, "https://vendor.example/product"),
            "https://vendor.example/img/fallback.png",
        )

    def test_structured_product_image_resolves_linked_image_object(self):
        html = """
        <script type="application/ld+json">
        {
          "@graph": [
            {"@type":"Product","name":"Linked Widget","image":{"@id":"https://vendor.example/product#primaryimage"}},
            {"@type":"ImageObject","@id":"https://vendor.example/product#primaryimage","contentUrl":"/media/linked-widget.jpg"}
          ]
        }
        </script>
        """
        soup = __import__("bs4").BeautifulSoup(html, "html.parser")
        self.assertEqual(
            _structured_product_image(soup, "https://vendor.example/product"),
            "https://vendor.example/media/linked-widget.jpg",
        )

    def test_printer_source_page_participates_in_shared_authoritative_resolution(self):
        printer = SimpleNamespace(
            name="P1S",
            manufacturer=SimpleNamespace(name="Bambu Lab"),
            features={},
            source_url="https://bambulab.com/en/p1",
            source=None,
        )

        pages = _candidate_source_pages(printer)

        self.assertEqual(pages[0]["url"], "https://bambulab.com/en/p1")
        self.assertEqual(pages[0]["source_type"], "manufacturer")
        self.assertEqual(pages[0]["provider"], "Bambu Lab official")

    def test_curated_mcu_source_pages_cover_known_board_failures(self):
        cases = [
            ("Adafruit", "Feather RP2040", "https://www.adafruit.com/product/4884"),
            ("Arduino", "Nano ESP32", "https://docs.arduino.cc/hardware/nano-esp32"),
            ("DFRobot", "FireBeetle 2 ESP32-E", "https://www.dfrobot.com/product-2195.html"),
            ("Espressif", "ESP32-P4-Function-EV-Board", "https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32p4/esp32-p4-function-ev-board/index.html"),
        ]
        for manufacturer_name, board_name, expected in cases:
            with self.subTest(board=board_name):
                board = SimpleNamespace(
                    name=board_name,
                    manufacturer=SimpleNamespace(name=manufacturer_name),
                    specifications={"board_type": "microcontroller"},
                )
                self.assertEqual(_curated_board_source_pages(board), [expected])

    def test_orange_pi_5_plus_prefers_official_wiki_source(self):
        board = SimpleNamespace(
            name="Orange Pi 5 Plus",
            manufacturer=SimpleNamespace(name="Orange Pi"),
            specifications={"board_type": "sbc"},
        )
        pages = _curated_board_source_pages(board)
        self.assertEqual(
            pages[0],
            "https://www.orangepi.org/orangepiwiki/index.php/Orange_Pi_5_Plus",
        )

    def test_curated_sbc_source_mapping_is_exact(self):
        manufacturer = SimpleNamespace(name="NVIDIA")
        board = SimpleNamespace(
            name="Jetson Orin Nano Super Developer Kit",
            manufacturer=manufacturer,
            specifications={"board_type": "sbc"},
        )
        self.assertEqual(
            _curated_sbc_source_page(board),
            "https://docs.nvidia.com/jetson/orin-nano-devkit/user-guide/latest/",
        )

    def test_curated_sbc_source_mappings_cover_major_vendor_families(self):
        cases = [
            ("Banana Pi", "BPI-M5", "https://www.banana-pi.org/en/banana-pi-sbcs/55.html"),
            ("BeagleBoard.org", "BeagleY-AI", "https://docs.beagleboard.org/latest/boards/beagley/ai/01-introduction.html"),
            ("Hardkernel", "ODROID-C5", "https://www.hardkernel.com/shop/odroid-c5/"),
            ("LattePanda", "LattePanda Mu", "https://www.lattepanda.com/lattepanda-mu"),
            ("Khadas", "VIM4", "https://www.khadas.com/vim4"),
            ("Radxa", "ROCK 5B", "https://docs.radxa.com/en/rock5/rock5b/getting-started/introduction"),
        ]
        for manufacturer_name, board_name, expected in cases:
            with self.subTest(board=board_name):
                board = SimpleNamespace(
                    name=board_name,
                    manufacturer=SimpleNamespace(name=manufacturer_name),
                    specifications={"board_type": "sbc"},
                )
                self.assertEqual(_curated_sbc_source_page(board), expected)

    def test_curated_sbc_source_pages_include_exact_fallbacks(self):
        beagleplay = SimpleNamespace(
            name="BeaglePlay",
            manufacturer=SimpleNamespace(name="BeagleBoard.org"),
            specifications={"board_type": "sbc"},
        )
        orange_plus = SimpleNamespace(
            name="Orange Pi 5 Plus",
            manufacturer=SimpleNamespace(name="Orange Pi"),
            specifications={"board_type": "sbc"},
        )

        self.assertIn(
            "https://www.beagleboard.org/boards/beagleplay",
            _curated_sbc_source_pages(beagleplay),
        )
        pages = _curated_sbc_source_pages(orange_plus)
        self.assertIn(
            "https://www.orangepi.org/orangepiwiki/index.php/Orange_Pi_5_Plus",
            pages,
        )
        self.assertIn("https://www.orangepi.org/", pages)

    def test_curated_sbc_source_mapping_ignores_microcontrollers(self):
        manufacturer = SimpleNamespace(name="NVIDIA")
        board = SimpleNamespace(
            name="Jetson Orin Nano Super Developer Kit",
            manufacturer=manufacturer,
            specifications={"board_type": "microcontroller"},
        )
        self.assertEqual(_curated_sbc_source_page(board), "")

    def test_page_image_candidates_prefer_structured_product_image(self):
        html = """
        <html><head>
          <meta property="og:image" content="/social-card.jpg">
          <script type="application/ld+json">
            {"@type":"Product","name":"Board","image":"/product-board.jpg"}
          </script>
        </head></html>
        """
        soup = __import__("bs4").BeautifulSoup(html, "html.parser")
        candidates = _page_image_candidates(soup, "https://vendor.example/board")
        self.assertEqual(candidates[0], ("https://vendor.example/product-board.jpg", "structured"))

    @patch("core.catalogue_image_sources.fetch_catalogue_source_html")
    @patch("core.catalogue_image_sources._candidate_source_pages")
    def test_source_page_image_uses_catalogue_source_fetcher(self, pages, fetch):
        pages.return_value = [{
            "url": "https://docs.beagleboard.org/latest/boards/beagleplay/index.html",
            "source_type": "manufacturer",
            "provider": "BeagleBoard.org",
        }]
        fetch.return_value = (
            "https://docs.beagleboard.org/latest/boards/beagleplay/index.html",
            '<html><head><meta property="og:image" content="/img/beagleplay.jpg"></head></html>',
        )

        result = find_source_page_image(SimpleNamespace())

        self.assertEqual(
            result["external_image_url"],
            "https://docs.beagleboard.org/img/beagleplay.jpg",
        )
        fetch.assert_called_once_with(
            "https://docs.beagleboard.org/latest/boards/beagleplay/index.html"
        )

    @patch("core.catalogue_image_sources.fetch_catalogue_source_html")
    @patch("core.catalogue_image_sources._candidate_source_pages")
    def test_source_page_diagnostics_record_missing_image_candidate(self, pages, fetch):
        pages.return_value = [{
            "url": "https://docs.example.test/board",
            "source_type": "manufacturer",
            "provider": "Example",
        }]
        fetch.return_value = (
            "https://docs.example.test/board",
            "<html><body><h1>Board documentation</h1></body></html>",
        )
        diagnostics = []

        result = find_source_page_image(SimpleNamespace(), diagnostics=diagnostics)

        self.assertIsNone(result)
        self.assertEqual(diagnostics[0]["result"], "no-image-candidate")
        self.assertEqual(diagnostics[0]["tier"], "manufacturer")

    def test_page_image_candidates_support_lazy_product_images(self):
        html = """
        <html><body>
          <img class="woocommerce-product-gallery__image"
               src="data:image/gif;base64,placeholder"
               data-large_image="/uploads/odroid-c5-main.webp"
               alt="ODROID-C5">
        </body></html>
        """
        soup = __import__("bs4").BeautifulSoup(html, "html.parser")
        candidates = _page_image_candidates(soup, "https://www.hardkernel.com/shop/odroid-c5/")
        self.assertEqual(
            candidates[0],
            ("https://www.hardkernel.com/uploads/odroid-c5-main.webp", "page-image"),
        )

    def test_page_image_candidates_support_gallery_anchor_images(self):
        html = """
        <html><body>
          <a class="woocommerce-product-gallery__image" href="/uploads/rock5b.jpg">
            <img src="/tiny-placeholder.gif" alt="ROCK 5B">
          </a>
        </body></html>
        """
        soup = __import__("bs4").BeautifulSoup(html, "html.parser")
        candidates = _page_image_candidates(soup, "https://example.test/product/")
        self.assertIn(
            ("https://example.test/uploads/rock5b.jpg", "gallery-image"),
            candidates,
        )

    def test_page_image_candidates_support_documentation_page_images(self):
        html = """
        <html><body>
          <img src="/logo.png" alt="Vendor logo">
          <img data-src="/images/board-front.webp" alt="Example Board front view">
        </body></html>
        """
        soup = __import__("bs4").BeautifulSoup(html, "html.parser")
        candidates = _page_image_candidates(soup, "https://docs.vendor.example/boards/example")
        self.assertEqual(candidates[0], ("https://docs.vendor.example/images/board-front.webp", "page-image"))

    @patch("core.catalogue_image_sources.fetch_catalogue_source_html")
    def test_source_page_remote_image_supports_secure_opengraph_variant(self, fetch_html):
        class Source:
            url = "https://vendor.example/products/widget"
            source_type = "manufacturer"
            name = "Vendor"

        component = DummyComponent()
        component.source = Source()
        component.specifications = {}
        fetch_html.return_value = (
            "https://vendor.example/products/widget",
            '<html><head><meta property="og:image:secure_url" content="/images/widget-secure.jpg"></head></html>',
        )
        found = find_source_page_image(component)
        self.assertEqual(found["external_image_url"], "https://vendor.example/images/widget-secure.jpg")
        self.assertEqual(found["image_source_discovery"], "meta")

    @patch("core.catalogue_image_sources.fetch_catalogue_source_html")
    def test_source_page_remote_image_uses_opengraph_without_caching(self, fetch_html):
        class Source:
            url = "https://vendor.example/products/widget"

        component = DummyComponent()
        component.source = Source()
        fetch_html.return_value = (
            "https://vendor.example/products/widget",
            '<html><head><meta property="og:image" content="/media/widget.jpg"></head></html>',
        )
        found = find_source_page_image(component)
        self.assertEqual(found["external_image_url"], "https://vendor.example/media/widget.jpg")
        self.assertEqual(found["image_source_provider"], "vendor.example")
        self.assertEqual(found["image_source_type"], "source-page-remote")

    @patch("core.catalogue_image_sources.fetch_catalogue_source_html")
    def test_source_page_remote_image_uses_structured_metadata_when_meta_missing(self, fetch_html):
        class Source:
            url = "https://vendor.example/products/widget"
            source_type = "manufacturer"
            name = "Vendor"

        component = DummyComponent()
        component.source = Source()
        component.specifications = {}
        fetch_html.return_value = (
            "https://vendor.example/products/widget",
            '<script type="application/ld+json">{"@type":"Product","image":"/images/widget.jpg"}</script>',
        )
        found = find_source_page_image(component)
        self.assertEqual(found["external_image_url"], "https://vendor.example/images/widget.jpg")
        self.assertEqual(found["image_source_discovery"], "structured")

    @patch("core.catalogue_image_sources.fetch_catalogue_source_html")
    def test_source_pages_try_manufacturer_before_generic(self, fetch_html):
        class Source:
            url = "https://example.net/widget"
            source_type = "generic"
            name = "Generic source"

        component = DummyComponent()
        component.source = Source()
        component.specifications = {
            "type": "environment",
            "reference_url": "https://www.adafruit.com/product/1234",
            "reference_provider": "Adafruit",
        }

        fetch_html.return_value = (
            "https://www.adafruit.com/product/1234",
            '<html><head><meta property="og:image" content="https://cdn.example/official.jpg"></head></html>',
        )
        found = find_source_page_image(component)
        self.assertEqual(found["image_source_tier"], "manufacturer")
        self.assertEqual(found["image_source_priority"], 10)
        self.assertEqual(fetch_html.call_args.args[0], "https://www.adafruit.com/product/1234")

    def test_printer_image_query_disambiguates_short_model_names(self):
        queries = _printer_image_queries(DummyPrinterModel())
        self.assertEqual(queries[0], "Creality K2")
        self.assertIn("Creality K2 3D printer", queries)
        self.assertIn("Creality K2 printer", queries)

    def test_printer_combo_image_queries_include_combo_and_system(self):
        queries = _printer_multi_material_image_queries(DummyPrinterModel())
        self.assertEqual(queries[0], "Creality K2 Combo 3D printer")
        self.assertIn("Creality K2 Creality CFS 3D printer", queries)

    @patch("core.catalogue_image_sources.requests.get")
    def test_orcaslicer_cover_uses_exact_profile_asset_without_caching(self, get):
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Type": "image/png"}
        get.return_value = response

        printer = DummyPrinterModel()
        printer.features = {
            "orcaslicer": {
                "ref": "main",
                "vendor_file": "Creality.json",
                "upstream_name": "Creality K2",
            }
        }

        found = find_orcaslicer_printer_cover(printer)
        self.assertEqual(
            found["external_image_url"],
            "https://raw.githubusercontent.com/OrcaSlicer/OrcaSlicer/main/resources/profiles/Creality/Creality%20K2_cover.png",
        )
        self.assertEqual(found["image_source_provider"], "OrcaSlicer")
        self.assertEqual(found["image_source_discovery"], "exact-profile-cover")
        self.assertEqual(found["image_source_tier"], "specialist")
        response.close.assert_called_once()

    def test_openverse_license_mapping_is_restrictive(self):
        self.assertEqual(_openverse_license_name("by", "4.0"), "CC BY 4.0")
        self.assertEqual(_openverse_license_name("by-sa", "4.0"), "CC BY-SA 4.0")
        self.assertEqual(_openverse_license_name("cc0", "1.0"), "CC0 1.0")
        self.assertEqual(_openverse_license_name("pdm", "1.0"), "Public Domain 1.0")
        self.assertEqual(_openverse_license_name("by-nc", "4.0"), "")

    @patch("core.catalogue_image_sources.requests.get")
    def test_openverse_returns_attributed_open_image(self, get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "results": [{
                "title": "BME280 module breakout",
                "thumbnail": "https://example.org/thumb.jpg",
                "foreign_landing_url": "https://example.org/work",
                "license": "by-sa",
                "license_version": "4.0",
                "creator": "Example Creator",
                "source": "wikimedia",
                "tags": [],
            }]
        }
        get.return_value = response
        candidate = search_openverse("BME280 module", minimum_score=0.1)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.license_name, "CC BY-SA 4.0")
        self.assertEqual(candidate.author, "Example Creator")
        self.assertTrue(candidate.provider.startswith("Openverse /"))



class PrinterCoverageTests(TestCase):
    def test_remote_printer_image_counts_as_complete(self):
        maker = PrinterManufacturer.objects.create(name="Coverage Test Printers")
        printer = PrinterCatalogModel.objects.create(
            manufacturer=maker,
            name="Remote Image 42",
            image_metadata={
                "external_image_url": "https://raw.githubusercontent.com/example/printer.png",
                "image_source_provider": "OrcaSlicer",
            },
        )

        coverage = _printer_coverage()
        images = next(metric for metric in coverage["metrics"] if metric["key"] == "images")
        sample = next(
            (item for item in coverage["missing_samples"] if item["id"] == str(printer.id)),
            None,
        )

        self.assertEqual(images["complete"], 1)
        self.assertIsNotNone(sample)
        self.assertNotIn("image", sample["missing"])


class CatalogueImagePriorityTests(TestCase):
    def setUp(self):
        self.printer_maker = PrinterManufacturer.objects.create(name="Image Test Printers")
        self.printer = PrinterCatalogModel.objects.create(
            manufacturer=self.printer_maker,
            name="Exact Model 42",
        )
        self.board = BoardModel.objects.create(name="Image Test Board")
        category = ComponentCategory.objects.create(name="Image Test Components", slug="image-test-components")
        self.component = ComponentModel.objects.create(
            category=category,
            name="Image Test Component",
            specifications={"type": "sensor"},
        )

    @override_settings(
        CATALOGUE_IMAGE_MAX_PER_RUN=1,
        CATALOGUE_IMAGE_RETRY_DAYS=1,
        CATALOGUE_IMAGE_WIKIMEDIA=True,
        CATALOGUE_IMAGE_OPENVERSE=True,
    )
    @patch("core.catalogue_image_sources.cache.delete")
    @patch("core.catalogue_image_sources.cache.add", return_value=True)
    @patch("core.catalogue_image_sources.find_source_page_image", return_value=None)
    @patch("core.catalogue_image_sources.resolve_catalogue_image", return_value=None)
    def test_component_without_exact_image_uses_generic_artwork(
        self,
        resolve_image,
        source_image,
        cache_add,
        cache_delete,
    ):
        result = run_catalogue_image_seed(
            limit=1,
            force_retry=True,
            kinds=["components"],
        )

        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["artwork"], 1)
        self.assertEqual(result["by_kind"]["components"]["artwork"], 1)
        self.component.refresh_from_db()
        self.assertEqual(
            self.component.specifications["auto_image_last_result"],
            "generic-artwork",
        )
        cache_add.assert_called_once()
        cache_delete.assert_called_once()

    @override_settings(
        CATALOGUE_IMAGE_MAX_PER_RUN=1,
        CATALOGUE_IMAGE_RETRY_DAYS=1,
        CATALOGUE_IMAGE_WIKIMEDIA=True,
        CATALOGUE_IMAGE_OPENVERSE=True,
    )
    @patch("core.catalogue_image_sources.cache.delete")
    @patch("core.catalogue_image_sources.cache.add", return_value=True)
    @patch("core.catalogue_image_sources.cache_candidate", side_effect=CatalogueImageError("HTTP 424"))
    @patch("core.catalogue_image_sources.resolve_catalogue_image")
    @patch("core.catalogue_image_sources.find_source_page_image", return_value=None)
    def test_component_cache_error_falls_back_to_generic_artwork(
        self,
        source_image,
        resolve_image,
        cache_candidate,
        cache_add,
        cache_delete,
    ):
        from core.catalogue_image_sources import ImageCandidate

        resolve_image.return_value = ImageCandidate(
            image_url="https://example.test/component.jpg",
            source_page_url="https://example.test/component",
            provider="Wikimedia Commons",
            license_name="CC BY-SA 4.0",
            query="test component",
        )

        result = run_catalogue_image_seed(
            limit=1,
            force_retry=True,
            kinds=["components"],
        )

        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["artwork"], 1)
        self.component.refresh_from_db()
        self.assertEqual(
            self.component.specifications["auto_image_last_result"],
            "generic-artwork-after-image-error",
        )
        self.assertEqual(
            self.component.specifications["auto_image_last_error"],
            "HTTP 424",
        )
        cache_add.assert_called_once()
        cache_delete.assert_called_once()

    @override_settings(
        CATALOGUE_IMAGE_MAX_PER_RUN=1,
        CATALOGUE_IMAGE_RETRY_DAYS=1,
        CATALOGUE_IMAGE_WIKIMEDIA=True,
        CATALOGUE_IMAGE_OPENVERSE=True,
    )
    @patch("core.catalogue_image_sources.cache.delete")
    @patch("core.catalogue_image_sources.cache.add", return_value=True)
    @patch("core.catalogue_image_sources.cache_candidate")
    @patch("core.catalogue_image_sources._search_open_media_with_diagnostics")
    def test_targeted_printer_pass_does_not_spend_limit_on_other_catalogues(
        self,
        search,
        cache_candidate,
        cache_add,
        cache_delete,
    ):
        from core.catalogue_image_sources import ImageCandidate

        candidate = ImageCandidate(
            image_url="https://upload.wikimedia.org/example.jpg",
            source_page_url="https://commons.wikimedia.org/example",
            provider="Wikimedia Commons",
            license_name="CC BY-SA 4.0",
            query="Image Test Printers Exact Model 42",
        )
        search.return_value = (
            candidate,
            {"attempts": [{"provider": "Wikimedia Commons", "query": candidate.query, "matched": True}]},
        )

        result = run_catalogue_image_seed(
            limit=1,
            force_retry=True,
            kinds=["printers"],
        )

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["by_kind"]["printers"]["cached"], 1)
        self.assertEqual(result["order"], ["printers"])
        cache_candidate.assert_called_once()
        cached_obj = cache_candidate.call_args.args[0]
        self.assertEqual(cached_obj.pk, self.printer.pk)
        cache_add.assert_called_once()
        cache_delete.assert_called_once()

    @override_settings(
        CATALOGUE_IMAGE_MAX_PER_RUN=1,
        CATALOGUE_IMAGE_RETRY_DAYS=1,
        CATALOGUE_IMAGE_WIKIMEDIA=True,
        CATALOGUE_IMAGE_OPENVERSE=True,
    )
    @patch("core.catalogue_image_sources.cache.delete")
    @patch("core.catalogue_image_sources.cache.add", return_value=True)
    @patch("core.catalogue_image_sources._search_open_media_with_diagnostics")
    @patch("core.catalogue_image_sources.find_orcaslicer_printer_cover")
    def test_exact_orcaslicer_cover_precedes_fuzzy_open_media(
        self,
        cover,
        search,
        cache_add,
        cache_delete,
    ):
        self.printer.features = {
            "orcaslicer": {
                "ref": "main",
                "vendor_file": "Image Test Printers.json",
                "upstream_name": "Image Test Printers Exact Model 42",
            }
        }
        self.printer.save(update_fields=["features", "updated_at"])
        cover.return_value = {
            "external_image_url": "https://raw.githubusercontent.com/example/cover.png",
            "image_source_page": "https://github.com/example/cover.png",
            "image_source_provider": "OrcaSlicer",
            "image_source_type": "orcaslicer-cover-remote",
            "image_source_discovery": "exact-profile-cover",
            "image_source_tier": "specialist",
            "image_source_priority": 30,
            "image_license": "",
            "image_author": "",
        }

        result = run_catalogue_image_seed(
            limit=1,
            force_retry=True,
            kinds=["printers"],
        )

        self.assertEqual(result["remote"], 1)
        self.assertEqual(result["by_kind"]["printers"]["remote"], 1)
        self.assertEqual(result["by_provider"]["OrcaSlicer"], 1)
        search.assert_not_called()
        self.printer.refresh_from_db()
        self.assertEqual(
            self.printer.image_metadata["external_image_url"],
            "https://raw.githubusercontent.com/example/cover.png",
        )
        self.assertEqual(
            self.printer.image_metadata["source_trace"][-1]["tier"],
            "specialist",
        )
        cache_add.assert_called_once()
        cache_delete.assert_called_once()

    @override_settings(
        CATALOGUE_IMAGE_MAX_PER_RUN=1,
        CATALOGUE_IMAGE_RETRY_DAYS=1,
        CATALOGUE_IMAGE_WIKIMEDIA=True,
        CATALOGUE_IMAGE_OPENVERSE=True,
    )
    @patch("core.catalogue_image_sources.cache.delete")
    @patch("core.catalogue_image_sources.cache.add", return_value=True)
    @patch("core.catalogue_image_sources._search_open_media_with_diagnostics")
    def test_multi_material_without_authoritative_image_is_deferred(
        self,
        search,
        cache_add,
        cache_delete,
    ):
        self.printer.multi_material_system = "bambu_ams"
        self.printer.image_metadata = {
            "external_image_url": "https://raw.githubusercontent.com/example/base.png",
        }
        self.printer.save(update_fields=["multi_material_system", "image_metadata", "updated_at"])

        result = run_catalogue_image_seed(
            limit=1,
            force_retry=False,
            kinds=["printers"],
        )

        self.assertEqual(result["processed"], 0)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["by_kind"]["printers"]["skipped"], 2)
        search.assert_not_called()
        self.printer.refresh_from_db()
        self.assertEqual(
            self.printer.image_multi_material_metadata["auto_image_last_result"],
            "deferred-no-authoritative-multi-material-image",
        )
        cache_add.assert_called_once()
        cache_delete.assert_called_once()

    @override_settings(
        CATALOGUE_IMAGE_MAX_PER_RUN=1,
        CATALOGUE_IMAGE_RETRY_DAYS=1,
        CATALOGUE_IMAGE_WIKIMEDIA=True,
        CATALOGUE_IMAGE_OPENVERSE=True,
    )
    @patch("core.catalogue_image_sources.cache.delete")
    @patch("core.catalogue_image_sources.cache.add", return_value=True)
    @patch("core.catalogue_image_sources._search_open_media_with_diagnostics")
    def test_curated_multi_material_image_is_recorded_without_fuzzy_search(
        self,
        search,
        cache_add,
        cache_delete,
    ):
        self.printer.multi_material_system = "creality_cfs"
        self.printer.image_metadata = {
            "external_image_url": "https://raw.githubusercontent.com/example/base.png",
        }
        self.printer.features = {
            "official_image_multi_material_url": "https://cdn.example/printer-combo.png",
            "official_image_multi_material_source_page": "https://vendor.example/printer-combo",
            "official_image_multi_material_source_provider": "Vendor official",
        }
        self.printer.save(update_fields=[
            "multi_material_system", "image_metadata", "features", "updated_at"
        ])

        result = run_catalogue_image_seed(
            limit=1,
            force_retry=False,
            kinds=["printers"],
        )

        self.assertEqual(result["processed"], 0)
        self.assertEqual(result["remote"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["by_provider"]["Vendor official"], 1)
        search.assert_not_called()
        self.printer.refresh_from_db()
        self.assertEqual(
            self.printer.image_multi_material_metadata["external_image_url"],
            "https://cdn.example/printer-combo.png",
        )
        cache_add.assert_called_once()
        cache_delete.assert_called_once()

    @override_settings(
        CATALOGUE_IMAGE_MAX_PER_RUN=1,
        CATALOGUE_IMAGE_RETRY_DAYS=1,
        CATALOGUE_IMAGE_WIKIMEDIA=True,
        CATALOGUE_IMAGE_OPENVERSE=True,
    )
    @patch("core.catalogue_image_sources.cache.delete")
    @patch("core.catalogue_image_sources.cache.add", return_value=True)
    @patch("core.catalogue_image_sources.resolve_catalogue_image")
    @patch("core.catalogue_image_sources.find_source_page_image")
    def test_manufacturer_remote_image_precedes_open_media(
        self,
        source_image,
        open_media,
        cache_add,
        cache_delete,
    ):
        self.component.specifications = {
            **self.component.specifications,
            "reference_url": "https://www.adafruit.com/product/999",
        }
        self.component.save(update_fields=["specifications", "updated_at"])
        source_image.return_value = {
            "external_image_url": "https://cdn.example/official.jpg",
            "image_source_page": "https://www.adafruit.com/product/999",
            "image_source_provider": "Adafruit",
            "image_source_type": "source-page-remote",
            "image_source_tier": "manufacturer",
            "image_source_priority": 10,
            "image_license": "",
            "image_author": "",
        }

        result = run_catalogue_image_seed(
            limit=1,
            force_retry=True,
            kinds=["components"],
        )

        self.assertEqual(result["remote"], 1)
        self.assertEqual(result["by_kind"]["components"]["remote"], 1)
        open_media.assert_not_called()
        self.component.refresh_from_db()
        self.assertEqual(
            self.component.specifications["external_image_url"],
            "https://cdn.example/official.jpg",
        )
        self.assertEqual(
            self.component.specifications["source_trace"][-1]["tier"],
            "manufacturer",
        )
        cache_add.assert_called_once()
        cache_delete.assert_called_once()

    @override_settings(CATALOGUE_IMAGE_MAX_PER_RUN=0)
    @patch("core.catalogue_image_sources.cache.delete")
    @patch("core.catalogue_image_sources.cache.add", return_value=True)
    @patch("core.catalogue_image_sources.resolve_catalogue_image", return_value=None)
    @patch("core.catalogue_image_sources.find_source_page_image", return_value=None)
    def test_board_type_filter_targets_only_sbc_records(
        self,
        source_image,
        resolve_image,
        cache_add,
        cache_delete,
    ):
        self.board.specifications = {"board_type": "microcontroller"}
        self.board.save(update_fields=["specifications", "updated_at"])
        BoardModel.objects.create(
            name="Test SBC",
            family="Test",
            specifications={"board_type": "sbc"},
        )

        result = run_catalogue_image_seed(
            limit=0,
            force_retry=True,
            kinds=["boards"],
            board_types=["sbc"],
        )

        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["by_kind"]["boards"]["processed"], 1)
        resolve_image.assert_called_once()
        self.assertEqual(resolve_image.call_args.args[0].name, "Test SBC")

    @override_settings(
        CATALOGUE_IMAGE_MAX_PER_RUN=1,
        CATALOGUE_IMAGE_RETRY_DAYS=1,
        CATALOGUE_IMAGE_WIKIMEDIA=True,
        CATALOGUE_IMAGE_OPENVERSE=True,
    )
    @patch("core.catalogue_image_sources.cache.delete")
    @patch("core.catalogue_image_sources.cache.add", return_value=True)
    @patch("core.catalogue_image_sources.resolve_catalogue_image", return_value=None)
    @patch("core.catalogue_image_sources.find_source_page_image", return_value=None)
    def test_force_retry_reprocesses_remote_board_reference(
        self,
        source_image,
        resolve_image,
        cache_add,
        cache_delete,
    ):
        self.board.specifications = {
            "board_type": "sbc",
            "external_image_url": "https://stale.example/board.jpg",
            "auto_image_attempt_version": "older-generation",
        }
        self.board.save(update_fields=["specifications", "updated_at"])

        result = run_catalogue_image_seed(
            limit=1,
            force_retry=True,
            kinds=["boards"],
        )

        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["by_kind"]["boards"]["skipped"], 0)
        self.assertEqual(result["by_kind"]["boards"]["failed"], 1)
        source_image.assert_called()
        resolve_image.assert_called_once()
        cache_add.assert_called_once()
        cache_delete.assert_called_once()

    @override_settings(
        CATALOGUE_IMAGE_MAX_PER_RUN=0,
        CATALOGUE_IMAGE_RETRY_DAYS=1,
        CATALOGUE_IMAGE_WIKIMEDIA=True,
        CATALOGUE_IMAGE_OPENVERSE=True,
    )
    def test_unknown_target_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            run_catalogue_image_seed(kinds=["not-a-catalogue"])


if __name__ == "__main__":
    unittest.main()
