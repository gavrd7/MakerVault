import unittest
from unittest.mock import patch

from core.importers import ImporterError, parse_espboards_html, validate_import_url


SAMPLE_HTML = """
<html><head>
<meta name="description" content="Tiny ESP32-C3 board for IoT projects.">
<meta property="og:image" content="https://www.espboards.dev/img/c3.png">
<link rel="canonical" href="https://www.espboards.dev/esp32/esp32-c3-super-mini/">
</head><body>
<h1>ESP32 C3 Super Mini</h1>
<div>by Generic</div>
<div>22.5 × 18 mm</div>
<div>ESP32-C3 RISC-V MCU</div>
<div>160 MHz clock</div>
<div>4 MB flash</div>
<div>400 KB SRAM</div>
<div>13 · 6 ADC GPIO</div>
<div>BLE 5.0 + WiFi</div>
<div>USB-C Native USB</div>
<h2>Getting started</h2><p>Arduino IDE PlatformIO ESPHome</p>
<a href="https://example.com/datasheet.pdf">Datasheet</a>
</body></html>
"""


class ImporterTests(unittest.TestCase):
    @patch("core.importers._host_is_public", return_value=True)
    def test_validate_allows_espboards(self, _):
        safe = validate_import_url("https://www.espboards.dev/esp32/esp32-c3-super-mini/")
        self.assertEqual(safe.host, "www.espboards.dev")

    @patch("core.importers._host_is_public", return_value=True)
    def test_validate_rejects_other_hosts(self, _):
        with self.assertRaises(ImporterError):
            validate_import_url("https://example.com/product")

    def test_parser_extracts_common_board_fields(self):
        data = parse_espboards_html("https://www.espboards.dev/esp32/esp32-c3-super-mini/", SAMPLE_HTML)
        self.assertEqual(data["name"], "ESP32 C3 Super Mini")
        self.assertEqual(data["manufacturer"], "Generic")
        self.assertEqual(data["family"], "ESP32-C3")
        self.assertEqual(data["architecture"], "RISC-V")
        self.assertEqual(data["flash_mb"], 4.0)
        self.assertEqual(data["ram_kb"], 400.0)
        self.assertEqual(data["gpio_count"], 13)
        self.assertTrue(data["wifi"])
        self.assertTrue(data["bluetooth"])
        self.assertEqual(data["usb_connector"], "USB-C")
        self.assertEqual(
            {x["platform"] for x in data["compatibility"]},
            {"Arduino", "PlatformIO", "ESPHome"},
        )


if __name__ == "__main__":
    unittest.main()
