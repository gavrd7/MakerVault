import unittest

from core.catalogue_profiles import apply_board_profile, apply_component_profile


class CatalogueProfileTests(unittest.TestCase):
    def test_pico_profile_adds_complete_baseline(self):
        item = apply_board_profile({
            "manufacturer": "Raspberry Pi",
            "name": "Raspberry Pi Pico",
            "mcu": "RP2040",
            "specifications": {},
        })
        self.assertEqual(item["flash_mb"], 2)
        self.assertEqual(item["ram_kb"], 264)
        self.assertEqual(item["gpio_count"], 26)
        self.assertEqual(item["specifications"]["clock_mhz"], 133)
        self.assertEqual(item["specifications"]["uart_count"], 2)

    def test_profile_never_overwrites_explicit_values(self):
        item = apply_board_profile({
            "manufacturer": "Raspberry Pi",
            "name": "Raspberry Pi Pico",
            "mcu": "RP2040",
            "ram_kb": 999,
            "specifications": {"clock_mhz": 200},
        })
        self.assertEqual(item["ram_kb"], 999)
        self.assertEqual(item["specifications"]["clock_mhz"], 200)

    def test_component_profile_fills_missing_part_metadata(self):
        item = apply_component_profile({
            "name": "BME280 sensor",
            "part_number": "BME280",
            "specifications": {"interface": "I2C/SPI"},
        })
        self.assertEqual(item["specifications"]["interface"], "I2C/SPI")
        self.assertIn("0x76", item["specifications"]["i2c_addresses"])


if __name__ == "__main__":
    unittest.main()
